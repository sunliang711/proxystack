"""proxystack-agent 本地管理 CLI 入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import ValidationError
import typer

from proxystack.cli.common import get_distribution_version
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
from proxystack.graph import ServiceNode
from proxystack.graph import build_reference_graph
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
def version() -> None:
    """输出 proxystack-agent 版本，用于验证命令入口是否可用。"""
    typer.echo(f"proxystack-agent {get_distribution_version()}")


@app.command()
def validate(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """校验全局配置和所有 stack 文件。"""
    try:
        global_config = load_config(config)
        stack_set = load_stacks(global_config, check_system_ports=not skip_system_ports)
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"配置校验失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"配置校验通过：{len(stack_set.stacks)} 个 stack")


@app.command()
def plan(
    target: Optional[str] = typer.Argument(None, help="可选 stack 名称；缺省为全部 stack。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """展示依赖服务和建议操作顺序，不写入任何文件。"""
    try:
        global_config = load_config(config)
        stack_set = load_stacks(global_config, check_system_ports=not skip_system_ports)
        graph = build_reference_graph(stack_set)
        dependency_plan = graph.build_plan(target)
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"配置编译失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"计划目标：{dependency_plan.target or '全部 stack'}")
    typer.echo("依赖服务：")
    if not dependency_plan.dependency_edges:
        typer.echo("  无服务依赖")
    for source_node, dependency_node in dependency_plan.dependency_edges:
        typer.echo(f"  - {format_service_node(source_node)} 依赖 {format_service_node(dependency_node)}")
    typer.echo("建议操作顺序：")
    for node_index, node in enumerate(dependency_plan.operation_order, start=1):
        typer.echo(f"  {node_index}. {format_service_node(node)}")


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
