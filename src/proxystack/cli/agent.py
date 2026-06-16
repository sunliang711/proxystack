"""proxystack-agent 本地管理 CLI 入口。"""

from __future__ import annotations

from pathlib import Path
import shlex
import sys
from typing import Callable
from typing import Optional
from typing import TextIO

from pydantic import ValidationError
import typer

from proxystack.cli.common import get_distribution_version
from proxystack.cli.lifecycle import RuntimePlan
from proxystack.cli.lifecycle import SUB_SERVICE_NAME
from proxystack.cli.lifecycle import StackMember
from proxystack.cli.lifecycle import TargetScope
from proxystack.cli.lifecycle import add_stack
from proxystack.cli.lifecycle import add_stack_member
from proxystack.cli.lifecycle import apply_runtime_plan
from proxystack.cli.lifecycle import build_runtime_plan
from proxystack.cli.lifecycle import clone_stack
from proxystack.cli.lifecycle import doctor_report
from proxystack.cli.lifecycle import edit_config_or_stack
from proxystack.cli.lifecycle import ensure_managed_directory
from proxystack.cli.lifecycle import ensure_managed_file_metadata
from proxystack.cli.lifecycle import ensure_project_dirs
from proxystack.cli.lifecycle import file_sha256
from proxystack.cli.lifecycle import init_project
from proxystack.cli.lifecycle import list_stack_members
from proxystack.cli.lifecycle import list_stacks
from proxystack.cli.lifecycle import normalize_target
from proxystack.cli.lifecycle import remove_stack_member
from proxystack.cli.lifecycle import remove_stack
from proxystack.cli.lifecycle import render_model_json
from proxystack.cli.lifecycle import resolve_service_scope
from proxystack.cli.lifecycle import resolve_target_scope
from proxystack.cli.lifecycle import write_bytes_if_changed
from proxystack.config import DEFAULT_CONFIG_PATH
from proxystack.config import load_config
from proxystack.config import load_stacks
from proxystack.diagnostics.ipinfo import IpInfoError
from proxystack.diagnostics.ipinfo import format_ipinfo_report
from proxystack.diagnostics.ipinfo import query_ipinfo
from proxystack.domain import ConfigValidationError
from proxystack.domain.models import GlobalConfig
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.generator.backup import NativeBackupError
from proxystack.generator.backup import NativeBackupPlan
from proxystack.generator.backup import read_native_backup
from proxystack.generator.backup import write_native_backup
from proxystack.generator.mihomo import dumps_mihomo_config
from proxystack.generator.sub import SubscriptionGeneratorError
from proxystack.generator.sub import SubscriptionBundleSummary
from proxystack.generator.sub import index_to_json
from proxystack.generator.sub import merge_input_files
from proxystack.generator.sub import render_clash_subscription
from proxystack.generator.sub import render_premium_clash_subscription
from proxystack.generator.sub import render_surge_subscription
from proxystack.generator.sub import render_stack_index
from proxystack.generator.sub import render_stack_input
from proxystack.generator.sub import stack_input_file
from proxystack.generator.sub import summarize_input_files
from proxystack.generator.sub import write_bundle
from proxystack.generator.xray import dumps_xray_config
from proxystack.graph import DependencyPlan
from proxystack.graph import ServiceNode
from proxystack.install import InstallResult
from proxystack.install import SelfUpdateRequest
from proxystack.install import build_install_request
from proxystack.install import detect_component_version
from proxystack.install import expand_artifact_targets
from proxystack.install import install_artifact
from proxystack.install import run_self_update
from proxystack.logging import configure_logging
from proxystack.logging import StepLogger
from proxystack.logging import summarize_exception
from proxystack.systemd import CLASH_TEMPLATE_UNIT
from proxystack.systemd import SUB_UNIT
from proxystack.systemd import SYSTEMD_UNIT_DIR
from proxystack.systemd import UNIT_NAMES
from proxystack.systemd import XRAY_TEMPLATE_UNIT
from proxystack.systemd import CommandRunner
from proxystack.systemd import SystemdCommandError
from proxystack.systemd import SystemdManager

CONFIG_HELP_PANEL = "配置管理"
INSTALL_HELP_PANEL = "安装更新"
VALIDATE_HELP_PANEL = "校验与渲染"
SERVICE_HELP_PANEL = "服务控制"
SUBSCRIPTION_HELP_PANEL = "订阅发布"
DIAGNOSTIC_HELP_PANEL = "诊断工具"

app = typer.Typer(
    help="本地代理栈管理命令。",
    no_args_is_help=True,
)
render_app = typer.Typer(
    help="渲染生成配置，不写入运行目录。",
    no_args_is_help=True,
)
member_app = typer.Typer(
    help="管理 auto/load-balance stack 的 xrelay-socks5 成员。",
    no_args_is_help=True,
)
sub_app = typer.Typer(
    help="订阅 input 校验和导出命令。",
    no_args_is_help=True,
)
service_app = typer.Typer(
    help="systemd unit 安装和服务生命周期管理命令。",
    no_args_is_help=True,
)
app.add_typer(render_app, name="render", rich_help_panel=VALIDATE_HELP_PANEL)
app.add_typer(member_app, name="member", rich_help_panel=CONFIG_HELP_PANEL)
app.add_typer(sub_app, name="sub", rich_help_panel=SUBSCRIPTION_HELP_PANEL)
app.add_typer(service_app, name="service", rich_help_panel=SERVICE_HELP_PANEL)

SYSTEMD_RUNNER: Optional[CommandRunner] = None
SYSTEMD_UNIT_DIR_OVERRIDE = SYSTEMD_UNIT_DIR
SCRIPTABLE_SUBCOMMANDS = {"list", "render"}
INSTALL_SOURCE_HELP = "安装源。mihomo/xray/geo 可用 auto/github/r2、本地文件或 http(s) URL；geo 默认下载 MetaCubeX geoip.metadb，普通远端 URL 需要 --sha256。"
DOWNLOAD_PROGRESS_PREFIXES = ("download: start ", "download: progress ", "download: complete ", "download: slow ")
SUBSCRIPTION_CONFIG_TYPES = ("sub", "premium_sub", "surge_sub")


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出调试级日志。"),
) -> None:
    """初始化 agent CLI 的通用选项。"""
    configure_logging("DEBUG" if verbose else "INFO")
    echo_command_progress("proxystack-agent", ctx.invoked_subcommand)


@sub_app.callback()
def sub_main(ctx: typer.Context) -> None:
    """输出 agent sub 命令组的执行提示。"""
    echo_command_progress("proxystack-agent sub", ctx.invoked_subcommand)


@member_app.callback()
def member_main(ctx: typer.Context) -> None:
    """输出 agent member 命令组的执行提示。"""
    echo_command_progress("proxystack-agent member", ctx.invoked_subcommand)


@service_app.callback()
def service_main(ctx: typer.Context) -> None:
    """输出 agent service 命令组的执行提示。"""
    echo_command_progress("proxystack-agent service", ctx.invoked_subcommand)


def echo_command_progress(command_prefix: str, subcommand: Optional[str]) -> None:
    """保留回调入口，实际进度由具体命令的 step 日志输出。"""
    return


def echo_command_error(exc: BaseException) -> None:
    """输出未进入 step 前的命令错误摘要。"""
    summary = summarize_exception(exc)
    typer.echo(f"Command failed: {summary.text}", err=True)
    if summary.detail_path is not None:
        typer.echo(f"Full output: {summary.detail_path}", err=True)


@app.command(rich_help_panel=CONFIG_HELP_PANEL)
def init(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    base_dir: Optional[Path] = typer.Option(None, "--base-dir", help="base_dir；缺省使用 config.yaml 所在目录。"),
    external_host: Optional[str] = typer.Option(None, "--external-host", help="订阅默认 external_host；缺省时需要之后在 config.yaml 中填写。"),
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


@app.command(rich_help_panel=INSTALL_HELP_PANEL)
def setup(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    base_dir: Optional[Path] = typer.Option(None, "--base-dir", help="base_dir；缺省使用 config.yaml 所在目录。"),
    external_host: Optional[str] = typer.Option(None, "--external-host", help="订阅默认 external_host；缺省时需要之后在 config.yaml 中填写。"),
    force: bool = typer.Option(False, "--force", help="覆盖已存在的 config.yaml。"),
) -> None:
    """初始化项目，幂等安装代理运行依赖和 systemd unit。"""
    step_logger = StepLogger()
    try:
        with step_logger.step("initialize project"):
            init_project(config, base_dir, external_host, force)
        run_artifact_operation("install", "all", None, None, None, None, config, step_logger=step_logger)
        with step_logger.step("install systemd units"):
            global_config = load_config(config)
            build_systemd_manager(global_config).install_units(UNIT_NAMES)
    except (ValidationError, ConfigValidationError, ValueError, OSError, SystemdCommandError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc


@app.command(rich_help_panel=CONFIG_HELP_PANEL)
def add(
    name: str = typer.Argument(..., help="新 stack 名称。"),
    template: str = typer.Option("pair", "--template", help="内置模板：pair/auto-url-test/load-balance。"),
    from_file: Optional[Path] = typer.Option(None, "--from-file", help="从已有 stack YAML 创建。"),
    members: Optional[str] = typer.Option(None, "--members", help="auto 模板成员 stack，逗号分隔。"),
    allocate_ports: bool = typer.Option(True, "--allocate-ports/--keep-template-ports", help="按 config.port_ranges 自动分配监听端口；需要保留来源端口时使用 --keep-template-ports。"),
    auto_edit: bool = typer.Option(True, "--edit/--no-edit", help="创建后自动编辑 stack；脚本化场景可用 --no-edit。"),
    editor: Optional[str] = typer.Option(None, "--editor", help="创建后编辑时覆盖 EDITOR，例如 --editor true。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """新增 stack 配置文件，不覆盖已存在 stack。"""
    try:
        path = add_stack(config, name, template, from_file, members, allocate_ports)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"新增 stack 失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"stack 已创建：{path}")
    if auto_edit:
        try:
            edit_config_or_stack(config, name, editor, check_only=False)
        except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
            typer.echo(f"编辑失败：\n{exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(f"编辑校验通过：{path}")


@app.command("clone", rich_help_panel=CONFIG_HELP_PANEL)
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


@app.command("list", rich_help_panel=CONFIG_HELP_PANEL)
def list_command(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    check_system_ports: bool = typer.Option(False, "--check-system-ports/--skip-system-ports", help="额外检查系统端口占用；默认跳过，避免运行中的服务阻断列表展示。"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="展示 API、controller 等管理端点。"),
) -> None:
    """列出 stack 名称、启用状态、角色和主要监听端口。"""
    try:
        rows = list_stacks(config, check_system_ports=check_system_ports)
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"读取 stack 列表失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    for line in format_stack_table(rows, verbose=verbose):
        typer.echo(line)


@member_app.command("list")
def member_list(
    stack: str = typer.Argument(..., help="要查看成员的 auto/load-balance stack 名称。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """列出 stack 中的 xrelay-socks5 成员。"""
    try:
        members = list_stack_members(config, stack)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"读取成员列表失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    for line in format_member_table(members):
        typer.echo(line)


@member_app.command("add")
def member_add(
    stack: str = typer.Argument(..., help="要修改的 auto/load-balance stack 名称。"),
    member: str = typer.Argument(..., help="要添加的成员 stack 名称，默认引用 <member>.relay。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """为 auto/load-balance stack 添加 xrelay-socks5 成员。"""
    try:
        path = add_stack_member(config, stack, member)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"添加成员失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"成员已添加：{stack} <- {member}")
    typer.echo(f"stack 已更新：{path}")


@member_app.command("remove")
def member_remove(
    stack: str = typer.Argument(..., help="要修改的 auto/load-balance stack 名称。"),
    member: str = typer.Argument(..., help="要删除的成员 stack 名称。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """从 auto/load-balance stack 删除 xrelay-socks5 成员。"""
    try:
        path = remove_stack_member(config, stack, member)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"删除成员失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"成员已删除：{stack} <- {member}")
    typer.echo(f"stack 已更新：{path}")


@app.command(rich_help_panel=CONFIG_HELP_PANEL)
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


@app.command("config", rich_help_panel=CONFIG_HELP_PANEL)
def config_command(
    name: Optional[str] = typer.Argument(None, help="stack 名称；缺省编辑全局 config.yaml。"),
    editor: Optional[str] = typer.Option(None, "--editor", help="覆盖 EDITOR，例如 --editor true。"),
    check_only: bool = typer.Option(False, "--check-only", help="只校验目标文件，不启动编辑器。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """安全编辑全局 config.yaml 或 stacks/<name>.yaml。"""
    try:
        original_sha256 = None
        if name is not None and not check_only:
            original_sha256 = stack_config_sha256(config, name)
        path = edit_config_or_stack(config, name, editor, check_only)
        stack_changed = original_sha256 is not None and file_sha256(path) != original_sha256
        if name is not None and stack_changed:
            restart_running_stack_after_config_edit(config, name)
    except SystemdCommandError as exc:
        typer.echo(f"自动重启失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"配置编辑失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"编辑校验通过：{path}")


def stack_config_sha256(config_path: Path, name: str) -> Optional[str]:
    """读取编辑前 stack 文件摘要；文件缺失时交给编辑流程输出原有错误。"""
    stack_path = load_config(config_path).stacks_dir / f"{name}.yaml"
    if not stack_path.exists():
        return None
    return file_sha256(stack_path)


def restart_running_stack_after_config_edit(config: Path, name: str) -> None:
    """stack 配置真实变更后，仅重启当前处于 active 的组件服务。"""
    step_logger = StepLogger()
    with step_logger.step("detect running stack services"):
        runtime_plan = build_runtime_plan(config, name, check_system_ports=False)
        manager = build_systemd_manager(runtime_plan.config)
        active_services = tuple(
            service_name
            for service_name in runtime_plan.scope.service_names
            if manager.is_active(service_name)
        )
        if active_services:
            ensure_proxy_binaries_installed(runtime_plan.config, active_services)
    if not active_services:
        return
    with step_logger.step("write runtime files"):
        apply_runtime_plan(runtime_plan)
    with step_logger.step("restart running stack services"):
        run_systemd_with_hint(name, config, lambda: manager.systemctl("restart", active_services))


@app.command("export", rich_help_panel=CONFIG_HELP_PANEL)
def export_backup(
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="原生配置备份包输出路径。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """导出 agent 原生配置备份包，仅包含 config.yaml 和 stacks/*.yaml。"""
    try:
        global_config = load_config(config)
        output_path = output or global_config.resolve_path(global_config.paths.publish) / "proxystack-backup.zip"
        ensure_managed_directory(output_path.parent)
        write_native_backup(output_path, config)
        ensure_managed_file_metadata(output_path)
    except (ValidationError, ConfigValidationError, ValueError, NativeBackupError, OSError) as exc:
        typer.echo(f"原生配置备份包导出失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"原生配置备份包已导出：{output_path}")


@app.command("import", rich_help_panel=CONFIG_HELP_PANEL)
def import_backup(
    backup_path: Path = typer.Argument(..., help="原生配置备份包 zip 路径。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="导入目标全局配置文件路径。"),
    base_dir: Optional[Path] = typer.Option(None, "--base-dir", help="导入后的 base_dir；缺省使用 config.yaml 所在目录。"),
    force: bool = typer.Option(False, "--force", help="允许覆盖已存在的 config.yaml 或同名 stack。"),
) -> None:
    """导入 agent 原生配置备份包，默认拒绝覆盖既有配置。"""
    try:
        target_base_dir = base_dir or config.parent
        plan = read_native_backup(backup_path, target_base_dir)
        imported_files = write_native_backup_plan(plan, config, force)
    except (ValidationError, ConfigValidationError, ValueError, NativeBackupError, OSError) as exc:
        typer.echo(f"原生配置备份包导入失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"原生配置备份包已导入：{backup_path}")
    for action, path in imported_files:
        if force:
            typer.echo(f"  - {action} {path}")
        else:
            typer.echo(f"  - {path}")


@app.command(rich_help_panel=INSTALL_HELP_PANEL)
def version(
    target: Optional[str] = typer.Argument(None, help="可选组件：mihomo/xray/geo。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """输出 proxystack-agent 或本地组件版本，用于验证命令入口是否可用。"""
    if target is None:
        typer.echo(f"proxystack-agent {get_distribution_version()}")
        return
    try:
        global_config = load_config(config)
        version_result = detect_component_version(global_config, target)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        typer.echo(f"版本检测失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    if version_result.status == "missing":
        typer.echo(f"{target} missing: {version_result.path}")
        return
    typer.echo(f"{target} {version_result.status}: {version_result.path}")
    if version_result.output:
        typer.echo(version_result.output)


@app.command(rich_help_panel=INSTALL_HELP_PANEL)
def install(
    target: str = typer.Argument(..., help="安装目标：mihomo/xray/geo/all。"),
    component_version: Optional[str] = typer.Option(None, "--version", help="目标版本标签。"),
    sha256: Optional[str] = typer.Option(None, "--sha256", help="源文件 sha256。"),
    source: Optional[str] = typer.Option(None, "--source", "--url", help=INSTALL_SOURCE_HELP),
    archive_member: Optional[str] = typer.Option(None, "--archive-member", help="归档内成员路径。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """安装 mihomo、xray 或 geo 数据；all 不安装 systemd unit。"""
    step_logger = StepLogger()
    try:
        run_artifact_operation("install", target, component_version, sha256, source, archive_member, config, step_logger=step_logger)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc


@app.command(rich_help_panel=INSTALL_HELP_PANEL)
def update(
    target: str = typer.Argument(..., help="更新目标：mihomo/xray/geo/all/self。"),
    package_spec: Optional[str] = typer.Argument(None, help="update self 使用的 package spec。"),
    wheel: Optional[Path] = typer.Option(None, "--wheel", help="update self 使用的 wheel 文件。"),
    component_version: Optional[str] = typer.Option(None, "--version", help="目标版本标签。"),
    sha256: Optional[str] = typer.Option(None, "--sha256", help="源文件或 wheel sha256。"),
    source: Optional[str] = typer.Option(None, "--source", "--url", help=INSTALL_SOURCE_HELP),
    archive_member: Optional[str] = typer.Option(None, "--archive-member", help="归档内成员路径。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """更新代理核心、geo 数据或 proxystack 自身；all 不包含 self。"""
    step_logger = StepLogger()
    try:
        if target == "self":
            if source is not None or archive_member is not None or component_version is not None:
                raise ValueError("update self only supports --wheel, package spec and --sha256")
            global_config = load_config(config)
            with step_logger.step("update proxystack package"):
                run_self_update(
                    global_config,
                    SelfUpdateRequest(wheel=wheel, package_spec=package_spec, sha256=sha256),
                )
            return
        if wheel is not None or package_spec is not None:
            raise ValueError("--wheel and package spec are only supported by update self")
        run_artifact_operation("update", target, component_version, sha256, source, archive_member, config, step_logger=step_logger)
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc


@app.command(rich_help_panel=VALIDATE_HELP_PANEL)
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


@app.command(rich_help_panel=VALIDATE_HELP_PANEL)
def check(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """校验配置并展示生成变更预览，不写文件、不操作服务。"""
    try:
        runtime_plan = build_runtime_plan(config, target, check_system_ports=not skip_system_ports)
    except (ValidationError, ConfigValidationError, ValueError) as exc:
        typer.echo(f"检查失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"配置校验通过：{len(runtime_plan.stack_set.stacks)} 个 stack")
    echo_runtime_plan(runtime_plan)


@app.command(rich_help_panel=SERVICE_HELP_PANEL)
def start(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """先写入生成配置，再重启变化服务并启动未变化服务。"""
    step_logger = StepLogger()
    try:
        if normalize_target(target) == "sub":
            with step_logger.step("start subscription service"):
                global_config = load_config(config)
                run_systemd_with_hint(
                    target,
                    config,
                    lambda: build_systemd_manager(global_config).systemctl("start", (SUB_SERVICE_NAME,)),
                )
            return
        with step_logger.step("build runtime plan"):
            runtime_plan = build_runtime_plan(config, target, check_system_ports=False)
            service_scope = resolve_service_scope(config, target, check_system_ports=False)
            ensure_proxy_binaries_installed(runtime_plan.config, service_scope.service_names)
        with step_logger.step("write runtime files"):
            apply_runtime_plan(runtime_plan)
    except SystemdCommandError as exc:
        if step_logger.step_index == 0:
            echo_command_error(ValueError(format_systemd_command_error(exc, target, config)))
        raise typer.Exit(code=1) from exc
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc
    service_names = set(service_scope.service_names)
    restart_services = [service_name for service_name in runtime_plan.changed_services if service_name in service_names]
    start_services = [service_name for service_name in service_scope.service_names if service_name not in restart_services]
    if not restart_services and not start_services:
        with step_logger.step("start selected services"):
            pass
        return
    try:
        manager = build_systemd_manager(runtime_plan.config)
        if restart_services:
            with step_logger.step("restart changed services"):
                run_systemd_with_hint(target, config, lambda: manager.systemctl("restart", restart_services))
        if start_services:
            with step_logger.step("start selected services"):
                run_systemd_with_hint(target, config, lambda: manager.systemctl("start", start_services))
    except SystemdCommandError as exc:
        if step_logger.step_index == 0:
            echo_command_error(ValueError(format_systemd_command_error(exc, target, config)))
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc


@app.command(rich_help_panel=SERVICE_HELP_PANEL)
def stop(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """停止目标 systemd 服务，不删除配置和生成文件。"""
    run_service_adapter("stop", target, config, skip_system_ports)


@app.command(rich_help_panel=SERVICE_HELP_PANEL)
def restart(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """先写入生成配置，再重启目标 systemd 服务。"""
    step_logger = StepLogger()
    try:
        if normalize_target(target) == "sub":
            with step_logger.step("restart subscription service"):
                global_config = load_config(config)
                run_systemd_with_hint(
                    target,
                    config,
                    lambda: build_systemd_manager(global_config).systemctl("restart", (SUB_SERVICE_NAME,)),
                )
            return
        with step_logger.step("build runtime plan"):
            runtime_plan = build_runtime_plan(config, target, check_system_ports=False)
            service_scope = resolve_service_scope(config, target, check_system_ports=False)
            ensure_proxy_binaries_installed(runtime_plan.config, service_scope.service_names)
        with step_logger.step("write runtime files"):
            apply_runtime_plan(runtime_plan)
        with step_logger.step("restart selected services"):
            manager = build_systemd_manager(runtime_plan.config)
            run_systemd_with_hint(target, config, lambda: manager.systemctl("restart", service_scope.service_names))
    except SystemdCommandError as exc:
        if step_logger.step_index == 0:
            echo_command_error(ValueError(format_systemd_command_error(exc, target, config)))
        raise typer.Exit(code=1) from exc
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc


@app.command(rich_help_panel=SERVICE_HELP_PANEL)
def status(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """查询目标 systemd 服务状态。"""
    run_service_adapter("status", target, config, skip_system_ports)


@app.command(rich_help_panel=SERVICE_HELP_PANEL)
def logs(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    follow: bool = typer.Option(False, "--follow", "-f", help="持续跟随 journalctl 输出。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """读取目标 systemd 服务日志。"""
    run_service_adapter("log", target, config, skip_system_ports, follow=follow)


@app.command(rich_help_panel=DIAGNOSTIC_HELP_PANEL)
def ipinfo(
    name: str = typer.Argument(..., help="要查询出口 IP 的 stack 名称。"),
    family: str = typer.Option("all", "--family", help="查询 IP 类型：all/ipv4/ipv6。"),
    timeout: float = typer.Option(8.0, "--timeout", help="单个来源请求超时时间，单位秒。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """通过 stack 的 mihomo socks listener 查询出口 IP。"""
    has_streamed_output = False

    def echo_ipinfo_line(line: str) -> None:
        """逐行输出 ipinfo 查询进度，避免等待所有来源完成后才展示。"""
        nonlocal has_streamed_output
        has_streamed_output = True
        typer.echo(line)

    try:
        report = query_ipinfo(
            config,
            name,
            family=family,
            timeout=timeout,
            line_callback=echo_ipinfo_line,
        )
    except (ValidationError, ConfigValidationError, IpInfoError, ValueError, OSError) as exc:
        typer.echo(f"查询出口 IP 失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not has_streamed_output:
        for line in format_ipinfo_report(report):
            typer.echo(line)


@app.command(rich_help_panel=SERVICE_HELP_PANEL)
def enable(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """启用目标 systemd 服务开机自启。"""
    run_service_adapter("enable", target, config, skip_system_ports)


@app.command(rich_help_panel=SERVICE_HELP_PANEL)
def disable(
    target: Optional[str] = typer.Argument(None, help="可选 stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
    skip_system_ports: bool = typer.Option(False, "--skip-system-ports", help="跳过系统端口占用检查。"),
) -> None:
    """禁用目标 systemd 服务开机自启。"""
    run_service_adapter("disable", target, config, skip_system_ports)


@service_app.command("install")
def service_install(
    target: Optional[str] = typer.Argument(None, help="可选目标：all、stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """安装 systemd unit 文件；这是唯一 unit 安装入口。"""
    run_unit_operation("install", target, config)


@service_app.command("uninstall")
def service_uninstall(
    target: Optional[str] = typer.Argument(None, help="可选目标：all、stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """卸载 systemd unit 文件；不删除 config 或 stacks。"""
    run_unit_operation("uninstall", target, config)


@service_app.command("enable")
def service_enable(
    target: Optional[str] = typer.Argument(None, help="可选目标：all、stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """启用目标 systemd 服务开机自启。"""
    run_service_group_action("enable", target, config)


@service_app.command("disable")
def service_disable(
    target: Optional[str] = typer.Argument(None, help="可选目标：all、stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """禁用目标 systemd 服务开机自启。"""
    run_service_group_action("disable", target, config)


@service_app.command("start")
def service_start(
    target: Optional[str] = typer.Argument(None, help="可选目标：all、stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """启动目标 systemd 服务。"""
    run_service_group_action("start", target, config)


@service_app.command("stop")
def service_stop(
    target: Optional[str] = typer.Argument(None, help="可选目标：all、stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """停止目标 systemd 服务。"""
    run_service_group_action("stop", target, config)


@service_app.command("restart")
def service_restart(
    target: Optional[str] = typer.Argument(None, help="可选目标：all、stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """重启目标 systemd 服务。"""
    run_service_group_action("restart", target, config)


@service_app.command("status")
def service_status(
    target: Optional[str] = typer.Argument(None, help="可选目标：all、stack、xrelay/name、clash/name 或 sub。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """查询目标 systemd 服务状态。"""
    run_service_group_action("status", target, config)


@service_app.command("log")
def service_log(
    target: Optional[str] = typer.Argument(None, help="可选目标：all、stack、xrelay/name、clash/name 或 sub。"),
    follow: bool = typer.Option(False, "--follow", "-f", help="持续跟随 journalctl 输出。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """读取目标 systemd 服务 journal。"""
    run_service_group_action("log", target, config, follow=follow)


@app.command(rich_help_panel=VALIDATE_HELP_PANEL)
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
    """输出服务依赖和建议操作顺序，供 check 展示。"""
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


def format_systemd_command_error(exc: SystemdCommandError, target: Optional[str], config: Path) -> str:
    """为 systemd unit 缺失错误补充下一步安装命令。"""
    message = str(exc)
    if "Unit " not in message or " not found" not in message:
        return message
    return "\n".join(
        [
            message,
            "",
            "systemd unit 未安装，请先执行：",
            f"  {format_service_install_hint(target, config)}",
            "然后重新执行当前命令。",
        ]
    )


def format_service_install_hint(target: Optional[str], config: Path) -> str:
    """生成和当前目标匹配的 service install 命令提示。"""
    normalized_target = normalize_target(target)
    command_parts = ["ps-agent", "service", "install"]
    if normalized_target is not None:
        command_parts.append(normalized_target)
    if config != DEFAULT_CONFIG_PATH:
        command_parts.extend(["-c", str(config)])
    return " ".join(shlex.quote(part) for part in command_parts)


def run_systemd_with_hint(target: Optional[str], config: Path, action: Callable[[], object]) -> object:
    """执行 systemd 操作，并把 unit 缺失错误转换为带安装提示的摘要。"""
    try:
        return action()
    except SystemdCommandError as exc:
        raise SystemdCommandError(format_systemd_command_error(exc, target, config)) from exc


def ensure_proxy_binaries_installed(config: GlobalConfig, service_names: tuple[str, ...]) -> None:
    """校验启动目标需要的代理核心二进制已安装且带可执行权限。"""
    required_binaries = required_proxy_binaries(service_names)
    if not required_binaries:
        return
    bin_dir = config.resolve_path(config.paths.bin)
    missing_lines: list[str] = []
    for binary_name in required_binaries:
        path = bin_dir / binary_name
        if not path.exists():
            missing_lines.append(f"  - {binary_name}: missing {path}")
            continue
        if not path.is_file():
            missing_lines.append(f"  - {binary_name}: not a file {path}")
            continue
        if path.stat().st_mode & 0o111 == 0:
            missing_lines.append(f"  - {binary_name}: not executable {path}")
    if not missing_lines:
        return
    raise ValueError(
        "\n".join(
            [
                "代理核心未安装或不可执行：",
                *missing_lines,
                "请先执行：",
                "  ps-agent install all",
                "或按需执行：",
                "  ps-agent install mihomo",
                "  ps-agent install xray",
            ]
        )
    )


def required_proxy_binaries(service_names: tuple[str, ...]) -> tuple[str, ...]:
    """根据 systemd 服务名推导启动前必须存在的代理核心二进制。"""
    binary_names: list[str] = []
    for service_name in service_names:
        if service_name.startswith("proxystack-clash@"):
            append_unique(binary_names, "mihomo")
        elif service_name.startswith("proxystack-xray@"):
            append_unique(binary_names, "xray")
    return tuple(binary_names)


def run_service_adapter(
    action: str,
    target: Optional[str],
    config: Path,
    skip_system_ports: bool,
    follow: bool = False,
) -> None:
    """解析顶层生命周期目标并调用真实 systemd runner。"""
    step_logger = StepLogger()
    try:
        if action == "log":
            scope = resolve_service_scope(config, target, check_system_ports=False)
            global_config = load_config(config)
            manager = build_systemd_manager(global_config)
            lines = manager.journalctl(scope.service_names, follow=follow)
            echo_service_lines(lines)
            return
        if action == "status":
            scope = resolve_service_scope(config, target, check_system_ports=False)
            global_config = load_config(config)
            manager = build_systemd_manager(global_config)
            lines = manager.systemctl(action, scope.service_names)
            echo_service_lines(lines)
            return
        else:
            with step_logger.step(f"{action} selected services"):
                scope = resolve_service_scope(config, target, check_system_ports=False)
                global_config = load_config(config)
                manager = build_systemd_manager(global_config)
                run_systemd_with_hint(target, config, lambda: manager.systemctl(action, scope.service_names))
    except SystemdCommandError as exc:
        if step_logger.step_index == 0:
            echo_command_error(ValueError(format_systemd_command_error(exc, target, config)))
        raise typer.Exit(code=1) from exc
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc


def run_unit_operation(operation: str, target: Optional[str], config: Path) -> None:
    """执行 systemd unit 安装或卸载操作。"""
    step_logger = StepLogger()
    try:
        with step_logger.step(f"{operation} systemd units"):
            global_config = load_config(config)
            manager = build_systemd_manager(global_config)
            unit_names = resolve_unit_names(config, target)
            if operation == "install":
                manager.install_units(unit_names)
            else:
                manager.uninstall_units(unit_names)
    except (ValidationError, ConfigValidationError, ValueError, OSError, SystemdCommandError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc


def run_service_group_action(
    action: str,
    target: Optional[str],
    config: Path,
    follow: bool = False,
) -> None:
    """执行 service 分组下的 systemd 生命周期命令。"""
    step_logger = StepLogger()
    try:
        if action == "log":
            scope = resolve_service_group_scope(config, target)
            global_config = load_config(config)
            manager = build_systemd_manager(global_config)
            lines = manager.journalctl(scope.service_names, follow=follow)
            echo_service_lines(lines)
            return
        if action == "status":
            scope = resolve_service_group_scope(config, target)
            global_config = load_config(config)
            manager = build_systemd_manager(global_config)
            lines = manager.systemctl(action, scope.service_names)
            echo_service_lines(lines)
            return
        else:
            with step_logger.step(f"{action} selected services"):
                scope = resolve_service_group_scope(config, target)
                global_config = load_config(config)
                manager = build_systemd_manager(global_config)
                run_systemd_with_hint(target, config, lambda: manager.systemctl(action, scope.service_names))
    except SystemdCommandError as exc:
        if step_logger.step_index == 0:
            echo_command_error(ValueError(format_systemd_command_error(exc, target, config)))
        raise typer.Exit(code=1) from exc
    except (ValidationError, ConfigValidationError, ValueError, OSError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc


def build_systemd_manager(global_config: GlobalConfig) -> SystemdManager:
    """创建 systemd manager，测试可通过模块变量替换 runner 和 unit_dir。"""
    return SystemdManager(global_config, runner=SYSTEMD_RUNNER, unit_dir=SYSTEMD_UNIT_DIR_OVERRIDE)


def resolve_service_group_scope(config_path: Path, target: Optional[str]) -> TargetScope:
    """解析 service 分组目标；缺省 all 包含 sub 服务。"""
    target = normalize_target(target)
    global_config = load_config(config_path)
    if target == "sub":
        return TargetScope(raw_target=target, components=frozenset(), include_sub=True, all_targets=False)
    stack_set = load_stacks(global_config, check_system_ports=False)
    return resolve_target_scope(stack_set, target)


def resolve_unit_names(config_path: Path, target: Optional[str]) -> tuple[str, ...]:
    """把 service install/uninstall 目标转换为 unit 模板文件名。"""
    target = normalize_target(target)
    if target is None:
        return UNIT_NAMES
    if target == "sub":
        return (SUB_UNIT,)
    scope = resolve_service_group_scope(config_path, target)
    return unit_names_for_services(scope.service_names)


def unit_names_for_services(service_names: tuple[str, ...]) -> tuple[str, ...]:
    """把服务实例名转换为需要安装或卸载的 unit 文件名。"""
    unit_names: list[str] = []
    for service_name in service_names:
        if service_name.startswith("proxystack-xray@"):
            append_unique(unit_names, XRAY_TEMPLATE_UNIT)
        elif service_name.startswith("proxystack-clash@"):
            append_unique(unit_names, CLASH_TEMPLATE_UNIT)
        elif service_name == SUB_SERVICE_NAME:
            append_unique(unit_names, SUB_UNIT)
        else:
            raise ValueError(f"unsupported service name: {service_name}")
    return tuple(unit_names)


def append_unique(values: list[str], value: str) -> None:
    """按顺序追加不重复的字符串。"""
    if value not in values:
        values.append(value)


def echo_service_lines(lines: list[str]) -> None:
    """逐行输出 service adapter 或 doctor 报告。"""
    for line in lines:
        typer.echo(line)


def format_member_table(members: list[StackMember]) -> list[str]:
    """把 xrelay-socks5 成员列表格式化为对齐表格。"""
    if not members:
        return ["未找到 xrelay-socks5 成员。"]
    rows = [
        {
            "member": member.member,
            "upstream": member.upstream,
            "ref": member.ref,
        }
        for member in members
    ]
    columns = [
        ("member", "Member"),
        ("upstream", "Upstream"),
        ("ref", "Ref"),
    ]
    widths = {
        key: max(len(title), *(len(row[key]) for row in rows))
        for key, title in columns
    }
    header = "  ".join(title.ljust(widths[key]) for key, title in columns).rstrip()
    separator = "  ".join("-" * widths[key] for key, _title in columns).rstrip()
    body = [
        "  ".join(row[key].ljust(widths[key]) for key, _title in columns).rstrip()
        for row in rows
    ]
    return [header, separator, *body]


def format_stack_table(rows: list[dict[str, str]], verbose: bool = False) -> list[str]:
    """把 stack 列表格式化为对齐表格，便于终端阅读。"""
    if not rows:
        return ["未找到 stack。"]
    display_groups = []
    for row in rows:
        display_groups.append(format_stack_component_rows(row, verbose=verbose))
    display_rows = [component_row for group in display_groups for component_row in group]
    columns = [
        ("name", "Name"),
        ("role", "Role"),
        ("enabled", "Enabled"),
        ("component", "Component"),
        ("running", "Running"),
        ("generated", "Generated"),
        ("endpoints", "Endpoints" if verbose else "Ports"),
    ]
    widths = {
        key: max(len(title), *(len(row[key]) for row in display_rows))
        for key, title in columns
    }
    header = "  ".join(title.ljust(widths[key]) for key, title in columns).rstrip()
    separator = "  ".join("-" * widths[key] for key, _title in columns).rstrip()
    body = []
    for group_index, group in enumerate(display_groups):
        body.extend(
            "  ".join(row[key].ljust(widths[key]) for key, _title in columns).rstrip()
            for row in group
        )
        if group_index < len(display_groups) - 1:
            body.append("")
    return [header, separator, *body]


def format_stack_component_rows(row: dict[str, str], verbose: bool = False) -> list[dict[str, str]]:
    """把单个 stack 展开为 xrelay/clash 两行展示。"""
    return [
        {
            "name": row["name"],
            "role": row["role"],
            "enabled": row["enabled"],
            "component": "xrelay",
            "running": format_stack_component_status(row, "xrelay", "running"),
            "generated": format_stack_component_status(row, "xrelay", "generated"),
            "endpoints": format_stack_xrelay_endpoints(row, verbose=verbose),
        },
        {
            "name": "",
            "role": "",
            "enabled": "",
            "component": "clash",
            "running": format_stack_component_status(row, "clash", "running"),
            "generated": format_stack_component_status(row, "clash", "generated"),
            "endpoints": format_stack_clash_endpoints(row, verbose=verbose),
        },
    ]


def format_stack_component_status(row: dict[str, str], component: str, field: str) -> str:
    """把 stack 级组件列表拆成单组件状态。"""
    if row[component] != "yes":
        return "disabled"
    components = {
        item.strip()
        for item in row[field].split(",")
        if item.strip() and item.strip() != "-"
    }
    return "yes" if component in components else "no"


def format_stack_xrelay_endpoints(row: dict[str, str], verbose: bool = False) -> str:
    """格式化 xrelay 组件端点摘要。"""
    inbounds = row["xrelay_ports"] or "-"
    api = row["xrelay_api_port"] or "-"
    if not verbose:
        return inbounds
    if inbounds == "-" and api == "-":
        return "-"
    return f"inbounds: {inbounds} | api:{api}"


def format_stack_clash_endpoints(row: dict[str, str], verbose: bool = False) -> str:
    """格式化 clash 组件端点摘要。"""
    socks = row["clash_socks"] or "-"
    http = row["clash_http"] or "-"
    controller = row["clash_controller"] or "-"
    if not verbose:
        if socks == "-" and http == "-":
            return "-"
        return f"socks:{socks} | http:{http}"
    if socks == "-" and http == "-" and controller == "-":
        return "-"
    return f"socks:{socks} | http:{http} | controller:{controller}"


def run_artifact_operation(
    operation: str,
    target: str,
    component_version: Optional[str],
    sha256: Optional[str],
    source: Optional[str],
    archive_member: Optional[str],
    config_path: Path,
    step_logger: Optional[StepLogger] = None,
) -> list[InstallResult]:
    """执行 install/update 代理核心和 geo 数据，all 只读取配置内分目标来源。"""
    if target == "all" and component_version is not None:
        raise ValueError("all target uses config.install.<target>.version or install a single target")
    if target == "all" and (source is not None or sha256 is not None or archive_member is not None):
        raise ValueError("all target uses config.install.* source, sha256 and archive_member")
    global_config = load_config(config_path)
    results: list[InstallResult] = []
    logger = step_logger or StepLogger()
    progress_printer = InstallProgressPrinter(step_logger=logger)
    try:
        for artifact_target in expand_artifact_targets(target):
            with logger.step(f"{operation} {artifact_target}"):
                try:
                    request = build_install_request(
                        global_config,
                        artifact_target,
                        component_version,
                        source,
                        sha256,
                        archive_member,
                    )
                    results.append(install_artifact(global_config, request, operation=operation, progress=progress_printer))
                finally:
                    progress_printer.finish()
    finally:
        progress_printer.finish()
    return results


class InstallProgressPrinter:
    """在交互式终端内单行刷新下载进度，非 TTY 保持逐行日志。"""

    def __init__(self, stream: Optional[TextIO] = None, step_logger: Optional[StepLogger] = None) -> None:
        """初始化输出流；测试可注入假 stream。"""
        self.stream = stream or sys.stderr
        self.step_logger = step_logger
        self.current_progress_width = 0

    def __call__(self, message: str) -> None:
        """只输出下载进度，隐藏安装步骤内部细节。"""
        if not is_download_progress_message(message):
            return
        if self.step_logger is not None:
            self.step_logger.break_line()
        if self.is_interactive():
            self.write_download_progress(message)
            return
        self.finish()
        typer.echo(message, err=True)

    def is_interactive(self) -> bool:
        """判断 stderr 是否支持交互式回车刷新。"""
        isatty = getattr(self.stream, "isatty", None)
        return bool(isatty is not None and isatty())

    def write_download_progress(self, message: str) -> None:
        """用回车覆盖当前下载进度行，完成时换行收尾。"""
        padded_message = message.ljust(self.current_progress_width)
        self.stream.write(f"\r{padded_message}")
        self.stream.flush()
        self.current_progress_width = max(self.current_progress_width, len(message))
        if message.startswith("download: complete "):
            self.finish()

    def finish(self) -> None:
        """结束尚未换行的下载进度，避免后续日志粘在同一行。"""
        if self.current_progress_width == 0:
            return
        self.stream.write("\n")
        self.stream.flush()
        self.current_progress_width = 0


def is_download_progress_message(message: str) -> bool:
    """识别可在终端单行刷新的下载进度消息。"""
    return any(message.startswith(prefix) for prefix in DOWNLOAD_PROGRESS_PREFIXES)


def echo_install_results(results: list[InstallResult]) -> None:
    """输出安装或更新结果，包含 sha256 和可测试服务计划。"""
    for result in results:
        if result.skipped:
            typer.echo(f"{result.target} {result.operation} 跳过：已存在")
            for path in result.installed_paths:
                typer.echo(f"  - {path}")
            continue
        typer.echo(f"{result.target} {result.operation} 完成：{result.version}")
        for path in result.installed_paths:
            typer.echo(f"  - {path}")
        typer.echo(f"  sha256: {result.source_sha256}")
        if result.service_plan:
            typer.echo("  服务计划：")
            for line in result.service_plan:
                typer.echo(f"    {line}")


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


@sub_app.command("export")
def export_subscription(
    stack: Optional[str] = typer.Argument(None, help="可选 stack 名称；缺省导出全部 stack。"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="订阅发布包输出路径。"),
    summary: bool = typer.Option(False, "--summary", "--dry-run", help="只预览发布包内容，不写入 zip。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """生成 ps-sub 可导入的订阅发布包。"""
    try:
        global_config = load_config(config)
        external_host = require_external_host_for_subscription_export(global_config)
        stack_set = load_stacks(global_config, check_system_ports=False)
        bundle_source, input_files = build_subscription_bundle_inputs(stack_set, stack)
        bundle_summary = summarize_input_files(bundle_source, input_files)
        output_path = output or default_subscription_bundle_path(global_config, stack)
        if summary:
            echo_subscription_bundle_summary(
                bundle_summary,
                output_path=output_path,
                external_host=external_host,
                preview=True,
            )
            return
        write_bundle(output_path, bundle_source, input_files)
        ensure_managed_directory(output_path.parent)
        ensure_managed_file_metadata(output_path)
    except (ValidationError, ConfigValidationError, ValueError, SubscriptionGeneratorError, OSError) as exc:
        typer.echo(f"订阅发布包导出失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"订阅发布包已导出：{output_path}")
    echo_subscription_bundle_summary(
        bundle_summary,
        output_path=output_path,
        external_host=external_host,
        preview=False,
    )


def require_external_host_for_subscription_export(global_config: GlobalConfig) -> str:
    """确保导出订阅前已设置对外 host，避免发布不可用的默认 server。"""
    if not global_config.external_host:
        raise ValueError(
            "external_host is required before exporting subscriptions; "
            "run `ps-agent config` and set external_host to the public domain/IP"
        )
    return global_config.external_host


@sub_app.command("export-config")
def export_subscription_config(
    subscription_type: str = typer.Argument(..., help="订阅类型：sub/premium_sub/surge_sub。"),
    user: str = typer.Argument(..., help="订阅用户。"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="全局配置文件路径。"),
) -> None:
    """直接输出指定用户的最终订阅配置文本，不写入发布包。"""
    try:
        rendered_config = render_subscription_config(config, subscription_type, user)
    except (ValidationError, ConfigValidationError, ValueError, SubscriptionGeneratorError) as exc:
        typer.echo(f"订阅配置导出失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(rendered_config, nl=False)


def render_subscription_config(config_path: Path, subscription_type: str, user: str) -> str:
    """从 agent 当前 stack 配置直接渲染指定用户的一种订阅配置。"""
    if subscription_type not in SUBSCRIPTION_CONFIG_TYPES:
        supported_types = ", ".join(SUBSCRIPTION_CONFIG_TYPES)
        raise ValueError(f"unsupported subscription config type: {subscription_type}; supported: {supported_types}")
    global_config = load_config(config_path)
    require_external_host_for_subscription_export(global_config)
    stack_set = load_stacks(global_config, check_system_ports=False)
    index = render_stack_index(stack_set, global_config.subscription.source)
    if subscription_type == "sub":
        return render_clash_subscription(index, user)
    if subscription_type == "premium_sub":
        return render_premium_clash_subscription(index, user)
    return render_surge_subscription(index, user)


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


def build_subscription_bundle_inputs(stack_set: StackSet, stack: Optional[str]) -> tuple[str, list[tuple[str, bytes]]]:
    """根据可选 stack 名称生成发布包内的 input 文件列表。"""
    if stack is not None:
        selected_stacks = [find_stack_for_subscription_export(stack_set, stack)]
        bundle_source = stack
    else:
        selected_stacks = list(stack_set.stacks)
        bundle_source = stack_set.config.subscription.source
    input_files: list[tuple[str, bytes]] = []
    for selected_stack in selected_stacks:
        scoped_stack_set = stack_set.model_copy(update={"stacks": [selected_stack]})
        subscription_input = render_stack_input(scoped_stack_set, selected_stack.name)
        input_files.append(stack_input_file(selected_stack.name, subscription_input))
    return bundle_source, input_files


def find_stack_for_subscription_export(stack_set: StackSet, stack: str) -> Stack:
    """查找要导出的 stack；不存在时给出明确错误。"""
    for candidate_stack in stack_set.stacks:
        if candidate_stack.name == stack:
            return candidate_stack
    raise ValueError(f"stack does not exist: {stack}")


def default_subscription_bundle_path(global_config: GlobalConfig, stack: Optional[str]) -> Path:
    """返回订阅发布包默认输出路径。"""
    publish_dir = global_config.resolve_path(global_config.paths.publish)
    if stack is None:
        return publish_dir / "sub-bundle.zip"
    return publish_dir / f"{stack}-sub-bundle.zip"


def echo_subscription_bundle_summary(
    summary: SubscriptionBundleSummary,
    output_path: Path,
    external_host: str,
    preview: bool,
) -> None:
    """输出订阅发布包内容摘要，不包含任何连接凭据。"""
    title = "订阅发布包预览" if preview else "订阅发布包摘要"
    typer.echo(
        f"{title}: output={output_path} source={summary.source} "
        f"external_host={external_host} inputs={summary.input_count} "
        f"nodes={summary.node_count} users={summary.user_count}"
    )
    for input_summary in summary.inputs:
        typer.echo(
            f"  - {input_summary.name}: source={input_summary.source} "
            f"nodes={input_summary.nodes} users={input_summary.users}"
        )
        for remark in input_summary.remarks:
            typer.echo(f"    - {remark}")


def write_native_backup_plan(plan: NativeBackupPlan, config_path: Path, force: bool) -> list[tuple[str, Path]]:
    """把已校验的原生备份计划写入目标 agent 目录，并标记写入动作。"""
    ensure_import_stacks_dir_inside_base_dir(plan)
    target_files = [(config_path, plan.config_content)]
    target_files.extend((plan.config.stacks_dir / stack_file.name, stack_file.content) for stack_file in plan.stack_files)
    if not force:
        existing_paths = [path for path, _content in target_files if path.exists()]
        if existing_paths:
            raise ValueError(f"target file already exists: {existing_paths[0]}")
    ensure_project_dirs(plan.config)
    written_files: list[tuple[str, Path]] = []
    for path, content in target_files:
        action = "overwritten" if path.exists() else "created"
        write_bytes_if_changed(path, content)
        written_files.append((action, path))
    return written_files


def ensure_import_stacks_dir_inside_base_dir(plan: NativeBackupPlan) -> None:
    """限制导入写入的 stacks 目录位于目标 base_dir 下，避免备份包改写任意路径。"""
    base_dir = plan.config.base_dir.resolve()
    stacks_dir = plan.config.stacks_dir.resolve()
    try:
        stacks_dir.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(f"import stacks directory must be inside base_dir: {stacks_dir}") from exc


def format_service_node(node: ServiceNode) -> str:
    """格式化服务节点，供 CLI check 输出使用。"""
    return f"{node.label()} ({node.service_name()})"


def run() -> None:
    """console script 入口，交给 Typer 处理命令解析。"""
    app()
