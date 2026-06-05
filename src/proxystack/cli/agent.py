"""proxystack-agent 本地管理 CLI 入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import ValidationError
import typer

from proxystack.cli.common import get_distribution_version
from proxystack.cli.lifecycle import RuntimePlan
from proxystack.cli.lifecycle import add_stack
from proxystack.cli.lifecycle import apply_runtime_plan
from proxystack.cli.lifecycle import build_runtime_plan
from proxystack.cli.lifecycle import clone_stack
from proxystack.cli.lifecycle import doctor_report
from proxystack.cli.lifecycle import edit_config_or_stack
from proxystack.cli.lifecycle import init_project
from proxystack.cli.lifecycle import list_stacks
from proxystack.cli.lifecycle import remove_stack
from proxystack.cli.lifecycle import render_model_json
from proxystack.cli.lifecycle import resolve_service_scope
from proxystack.cli.lifecycle import service_action_lines
from proxystack.config import DEFAULT_CONFIG_PATH
from proxystack.config import load_config
from proxystack.config import load_stacks
from proxystack.domain import ConfigValidationError
from proxystack.generator.mihomo import dumps_mihomo_config
from proxystack.generator.sub import SubscriptionAccess
from proxystack.generator.sub import SubscriptionGeneratorError
from proxystack.generator.sub import index_to_json
from proxystack.generator.sub import input_dir_files
from proxystack.generator.sub import input_to_yaml
from proxystack.generator.sub import load_inputs
from proxystack.generator.sub import merge_input_files
from proxystack.generator.sub import merge_inputs
from proxystack.generator.sub import render_stack_index
from proxystack.generator.sub import render_stack_input
from proxystack.generator.sub import stack_input_file
from proxystack.generator.sub import validate_bundle_input_name
from proxystack.generator.sub import write_bundle
from proxystack.generator.xray import dumps_xray_config
from proxystack.graph import DependencyPlan
from proxystack.graph import ServiceNode
from proxystack.logging import configure_logging

app = typer.Typer(
    help="本地代理栈管理命令。",
    no_args_is_help=True,
)
render_app = typer.Typer(
    help="渲染生成配置，不写入运行目录。",
    no_args_is_help=True,
)
sub_app = typer.Typer(
    help="订阅 input 校验和导出命令。",
    no_args_is_help=True,
)
app.add_typer(render_app, name="render")
app.add_typer(sub_app, name="sub")


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出调试级日志。"),
) -> None:
    """初始化 agent CLI 的通用选项。"""
    configure_logging("DEBUG" if verbose else "INFO")


@app.command()
def init(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    base_dir: Optional[Path] = typer.Option(None, "--base-dir", help="base_dir；缺省使用 config.yaml 所在目录。"),
    external_host: str = typer.Option("proxy.example.com", "--external-host", help="默认 external_host。"),
    force: bool = typer.Option(False, "--force", help="覆盖已存在的 config.yaml。"),
) -> None:
    """初始化 proxystack 目录和默认配置。"""
    try:
        paths = init_project(config, base_dir, external_host, force)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"初始化失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"初始化完成：{config}")
    for path in paths:
        typer.echo(f"  - {path}")


@app.command()
def add(
    name: str = typer.Argument(..., help="新 stack 名称。"),
    template: str = typer.Option("pair", "--template", help="内置模板：pair/auto-url-test/load-balance。"),
    from_file: Optional[Path] = typer.Option(None, "--from-file", help="从已有 stack YAML 创建。"),
    members: Optional[str] = typer.Option(None, "--members", help="auto 模板成员 stack，逗号分隔。"),
    allocate_ports: bool = typer.Option(False, "--allocate-ports", help="按 config.port_ranges 自动分配监听端口。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """新增 stack 配置文件，不覆盖已存在 stack。"""
    try:
        path = add_stack(config, name, template, from_file, members, allocate_ports)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"新增 stack 失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"stack 已创建：{path}")


@app.command("clone")
def clone_command(
    source: str = typer.Argument(..., help="来源 stack 名称。"),
    target: str = typer.Argument(..., help="目标 stack 名称。"),
    allocate_ports: bool = typer.Option(False, "--allocate-ports", help="为目标 stack 重新分配监听端口。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """复制 stack YAML，并改写顶层 name 和自身 ref。"""
    try:
        path = clone_stack(config, source, target, allocate_ports)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"克隆 stack 失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"stack 已克隆：{path}")


@app.command("list")
def list_command(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """列出 stack 名称、启用状态、角色和主要监听端口。"""
    try:
        rows = list_stacks(config, check_system_ports=not skip_system_ports)
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"读取 stack 列表失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("name enabled role xrelay clash xrelay_ports clash_socks clash_controller")
    for row in rows:
        typer.echo(
            " ".join(
                [
                    row["name"],
                    row["enabled"],
                    row["role"],
                    row["xrelay"],
                    row["clash"],
                    row["xrelay_ports"],
                    row["clash_socks"],
                    row["clash_controller"],
                ]
            )
        )


@app.command()
def remove(
    name: str = typer.Argument(..., help="要删除的 stack 名称。"),
    purge: bool = typer.Option(False, "--purge", help="同时删除该 stack 对应生成文件。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """删除 stack YAML；默认不操作 systemd、不删除生成文件。"""
    try:
        paths = remove_stack(config, name, purge)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"删除 stack 失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("stack 已删除，未操作 systemd。")
    for path in paths:
        typer.echo(f"  - {path}")


@app.command()
def edit(
    name: Optional[str] = typer.Argument(None, help="stack 名称；缺省编辑 config.yaml。"),
    editor: Optional[str] = typer.Option(None, "--editor", help="覆盖 EDITOR，例如 --editor true。"),
    check_only: bool = typer.Option(False, "--check-only", help="只校验目标文件，不启动编辑器。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """安全编辑 config.yaml 或 stacks/<name>.yaml。"""
    try:
        path = edit_config_or_stack(config, name, editor, check_only)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"编辑失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"编辑校验通过：{path}")


@app.command()
def version() -> None:
    """输出 proxystack-agent 版本，用于验证命令入口是否可用。"""
    typer.echo(f"proxystack-agent {get_distribution_version()}")


@app.command()
def validate(
    target: Optional[str] = typer.Argument(None, help="可选 stack 名称；缺省为全部 stack。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """校验全局配置和所有 stack 文件。"""
    try:
        global_config = load_config(config)
        stack_set = load_stacks(global_config, check_system_ports=not skip_system_ports)
        if target is not None and target not in stack_set.by_name():
            raise ValueError(f"stack does not exist: {target}")
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"配置校验失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    target_label = target or "全部 stack"
    typer.echo(f"配置校验通过：{len(stack_set.stacks)} 个 stack，目标 {target_label}")


@app.command()
def plan(
    target: Optional[str] = typer.Argument(None, help="可选 stack 名称；缺省为全部 stack。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """展示将写入或删除的生成文件，不写入任何运行目录文件。"""
    try:
        runtime_plan = build_runtime_plan(config, target, check_system_ports=not skip_system_ports)
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"配置编译失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    echo_runtime_plan(runtime_plan)


@app.command()
def apply(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """写入生成文件和 manifest，不启动、不停止、不重启服务。"""
    try:
        runtime_plan = build_runtime_plan(config, target, check_system_ports=not skip_system_ports)
        apply_runtime_plan(runtime_plan)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"应用生成文件失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    changed_count = sum(1 for change in runtime_plan.changes if change.is_changed)
    typer.echo(f"apply 完成：{changed_count} 个文件变化；未操作 systemd。")
    echo_runtime_plan(runtime_plan)


@app.command()
def check(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """执行 validate + plan 包装，不写文件、不操作服务。"""
    try:
        runtime_plan = build_runtime_plan(config, target, check_system_ports=not skip_system_ports)
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"检查失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"配置校验通过：{len(runtime_plan.stack_set.stacks)} 个 stack")
    echo_runtime_plan(runtime_plan)


@app.command()
def up(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只展示服务动作，不写生成文件。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """准备启动目标服务；Task07 只输出服务动作，不调用 systemctl。"""
    try:
        if dry_run:
            scope = resolve_service_scope(config, target, check_system_ports=False)
            typer.echo("Service adapter dry-run; Task09 will execute systemd.")
            echo_service_lines(service_action_lines("restart", scope))
            return
        runtime_plan = build_runtime_plan(config, target, check_system_ports=False)
        apply_runtime_plan(runtime_plan)
        service_scope = resolve_service_scope(config, target, check_system_ports=False)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"up 失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    service_names = set(service_scope.service_names)
    services = [service_name for service_name in runtime_plan.changed_services if service_name in service_names]
    typer.echo("Service adapter execute mode; Task09 will execute systemd.")
    if not services:
        typer.echo("restart: no services selected")
        return
    echo_service_lines([f"restart: {service_name}" for service_name in services])


@app.command()
def down(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """展示停止目标服务的动作，不调用 systemctl。"""
    run_service_adapter("stop", target, config, skip_system_ports)


@app.command()
def restart(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """展示重启目标服务的动作，不调用 systemctl。"""
    run_service_adapter("restart", target, config, skip_system_ports)


@app.command()
def status(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """展示查询目标服务状态的动作，不调用 systemctl。"""
    run_service_adapter("status", target, config, skip_system_ports)


@app.command()
def logs(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    follow: bool = typer.Option(False, "--follow", "-f", help="展示 follow 日志动作。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """展示读取目标服务日志的动作，不调用 journalctl。"""
    run_service_adapter("logs", target, config, skip_system_ports, follow=follow)


@app.command()
def enable(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """展示启用目标服务开机自启的动作，不调用 systemctl。"""
    run_service_adapter("enable", target, config, skip_system_ports)


@app.command()
def disable(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """展示禁用目标服务开机自启的动作，不调用 systemctl。"""
    run_service_adapter("disable", target, config, skip_system_ports)


@app.command()
def doctor(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """只读检查目录、二进制、systemd unit 和端口占用。"""
    try:
        lines = doctor_report(config)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"doctor 失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    echo_service_lines(lines)


@render_app.command("model")
def render_model(
    target: Optional[str] = typer.Argument(None, help="可选 stack 名称；缺省输出完整模型。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """输出解析后的模型 JSON，不写入运行目录。"""
    try:
        rendered_model = render_model_json(config, target, check_system_ports=not skip_system_ports)
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"模型渲染失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(rendered_model, nl=False)


def echo_runtime_plan(runtime_plan: RuntimePlan) -> None:
    """输出文件变化、受影响服务和依赖顺序。"""
    typer.echo(f"计划目标：{runtime_plan.scope.raw_target or '全部 stack'}")
    typer.echo("文件变更：")
    if not runtime_plan.changes:
        typer.echo("  无文件变化")
    for change in runtime_plan.changes:
        typer.echo(f"  - {change.action} {change.relative_path} -> {change.service_name}")
    typer.echo("受影响服务：")
    if not runtime_plan.changed_services:
        typer.echo("  无")
    for service_name in runtime_plan.changed_services:
        typer.echo(f"  - {service_name}")
    echo_dependency_plan(runtime_plan.dependency_plan)


def echo_dependency_plan(dependency_plan: Optional[DependencyPlan]) -> None:
    """输出服务依赖和建议操作顺序，兼容原有 plan 展示。"""
    typer.echo("依赖服务：")
    if dependency_plan is None or not dependency_plan.dependency_edges:
        typer.echo("  无服务依赖")
    if dependency_plan is not None:
        for source_node, dependency_node in dependency_plan.dependency_edges:
            typer.echo(f"  - {format_service_node(source_node)} 依赖 {format_service_node(dependency_node)}")
    typer.echo("建议操作顺序：")
    if dependency_plan is None or not dependency_plan.operation_order:
        typer.echo("  无代理服务")
        return
    for node_index, node in enumerate(dependency_plan.operation_order, start=1):
        typer.echo(f"  {node_index}. {format_service_node(node)}")


def run_service_adapter(
    action: str,
    target: Optional[str],
    config: Path,
    skip_system_ports: bool,
    follow: bool = False,
) -> None:
    """解析目标并输出可测试的服务动作说明。"""
    try:
        scope = resolve_service_scope(config, target, check_system_ports=False)
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"服务目标解析失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Service adapter dry-run; Task09 will execute systemd.")
    echo_service_lines(service_action_lines(action, scope, follow=follow))


def echo_service_lines(lines: list[str]) -> None:
    """逐行输出 service adapter 或 doctor 报告。"""
    for line in lines:
        typer.echo(line)


@render_app.command("xrelay")
def render_xrelay(
    name: str = typer.Argument(..., help="要渲染的 stack 名称。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """输出指定 stack 的 Xray JSON，不写入运行目录。"""
    try:
        global_config = load_config(config)
        stack_set = load_stacks(global_config, check_system_ports=not skip_system_ports)
        rendered_config = dumps_xray_config(stack_set, name)
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"Xray 配置渲染失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(rendered_config, nl=False)


@render_app.command("clash")
def render_clash(
    name: str = typer.Argument(..., help="要渲染的 stack 名称。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """输出指定 stack 的 mihomo YAML，不写入运行目录。"""
    try:
        global_config = load_config(config)
        stack_set = load_stacks(global_config, check_system_ports=not skip_system_ports)
        rendered_config = dumps_mihomo_config(stack_set, name)
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"mihomo 配置渲染失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(rendered_config, nl=False)


@render_app.command("sub")
def render_sub(
    input_dir: Optional[Path] = typer.Option(None, "--input-dir", help="订阅 inputs 目录；缺省时从当前 stack 生成。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """输出订阅索引 JSON，不写入运行目录。"""
    try:
        if input_dir is not None:
            rendered_index = merge_input_files(input_dir)
        else:
            global_config = load_config(config)
            stack_set = load_stacks(global_config, check_system_ports=not skip_system_ports)
            rendered_index = render_stack_index(stack_set, global_config.subscription.source)
    except (ValidationError, ConfigValidationError, ValueError, SubscriptionGeneratorError) as exc:
        typer.echo(f"订阅索引渲染失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(index_to_json(rendered_index), nl=False)


@sub_app.command("export-input")
def export_input(
    source: Optional[str] = typer.Option(None, "--source", help="订阅 input source；缺省使用 config.subscription.source。"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="输出 input YAML 路径。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """从当前 stack 生成订阅 input YAML。"""
    try:
        global_config = load_config(config)
        stack_set = load_stacks(global_config, check_system_ports=not skip_system_ports)
        input_source = source or global_config.subscription.source
        subscription_input = render_stack_input(stack_set, input_source)
        validate_bundle_input_name(f"{input_source}.yaml")
        output_path = output or Path(f"{input_source}.yaml")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(input_to_yaml(subscription_input), encoding="utf-8")
    except (ValidationError, ConfigValidationError, ValueError, SubscriptionGeneratorError) as exc:
        typer.echo(f"订阅 input 导出失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"订阅 input 已导出：{output_path}")


@sub_app.command("validate-inputs")
def validate_inputs(
    input_dir: Path = typer.Option(..., "--input-dir", help="订阅 inputs 目录。"),
) -> None:
    """校验订阅 inputs 目录并报告可合并节点数量。"""
    try:
        rendered_index = merge_input_files(input_dir)
    except (ValueError, SubscriptionGeneratorError) as exc:
        typer.echo(f"订阅 inputs 校验失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"订阅 inputs 校验通过：{len(rendered_index.nodes)} 个节点")


@app.command("publish")
def publish(
    source: Optional[str] = typer.Option(None, "--source", help="发布包 source；缺省使用 config.subscription.source。"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="发布包输出路径。"),
    input_dir: Optional[Path] = typer.Option(None, "--input-dir", help="订阅 inputs 目录。"),
    include_stack: bool = typer.Option(False, "--include-stack", help="与 --input-dir 合并当前 stack 生成的临时 input。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """生成订阅发布包，不包含完整 stack 或 clash 本地运行配置。"""
    try:
        bundle_source = source or "merged"
        access = None
        global_config = None
        stack_set = None
        input_files = []
        if input_dir is not None and not include_stack and not config.exists() and config != DEFAULT_CONFIG_PATH:
            raise ValueError(f"config file does not exist: {config}")
        if input_dir is None or include_stack or config.exists():
            global_config = load_config(config)
            bundle_source = source or global_config.subscription.source
            access = SubscriptionAccess.model_validate(global_config.subscription.access.model_dump())
        if input_dir is None or include_stack:
            if global_config is None:
                global_config = load_config(config)
                bundle_source = source or global_config.subscription.source
                access = SubscriptionAccess.model_validate(global_config.subscription.access.model_dump())
            stack_set = load_stacks(global_config, check_system_ports=not skip_system_ports)
        if input_dir is None:
            subscription_input = render_stack_input(stack_set, bundle_source)
            merge_inputs([(Path(f"{bundle_source}.yaml"), subscription_input)], access=access)
            input_files = [stack_input_file(bundle_source, subscription_input)]
        else:
            loaded_inputs = load_inputs(input_dir)
            input_files = input_dir_files(input_dir)
            if include_stack:
                subscription_input = render_stack_input(stack_set, bundle_source)
                loaded_inputs.append((Path(f"{bundle_source}.yaml"), subscription_input))
                input_files.append(stack_input_file(bundle_source, subscription_input))
            merge_inputs(loaded_inputs, access=access)
        if output is None:
            if input_dir is None or include_stack:
                output_path = global_config.resolve_path(global_config.paths.publish) / "sub-bundle.zip"
            else:
                output_path = Path("sub-bundle.zip")
        else:
            output_path = output
        write_bundle(output_path, bundle_source, input_files, access=access)
    except (ValidationError, ConfigValidationError, ValueError, SubscriptionGeneratorError) as exc:
        typer.echo(f"订阅发布包生成失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"订阅发布包已生成：{output_path}")


def format_service_node(node: ServiceNode) -> str:
    """格式化服务节点，供 CLI plan 输出使用。"""
    return f"{node.label()} ({node.service_name()})"


def run() -> None:
    """console script 入口，交给 Typer 处理命令解析。"""
    app()
