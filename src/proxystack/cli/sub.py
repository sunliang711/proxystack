"""proxystack-sub 订阅服务 CLI 入口。"""

from __future__ import annotations

import logging
from pathlib import Path
import tempfile
from typing import Optional

import typer
import uvicorn

from proxystack.cli.common import get_distribution_version
from proxystack.cli.lifecycle import run_editor
from proxystack.cli.lifecycle import write_text_if_changed
from proxystack.generator.sub import BundleImportResult
from proxystack.generator.sub import clear_managed_input_files
from proxystack.generator.sub import SubscriptionGeneratorError
from proxystack.generator.sub import extract_bundle_inputs_with_result
from proxystack.generator.sub import find_subscription_template_source
from proxystack.logging import configure_logging
from proxystack.logging import StepLogger
from proxystack.logging import summarize_exception
from proxystack.subserver import SubscriptionState
from proxystack.subserver import create_app
from proxystack.subserver.config import apply_cli_overrides
from proxystack.subserver.config import default_sub_server_config
from proxystack.subserver.config import load_sub_server_config
from proxystack.subserver.config import load_sub_server_config_file
from proxystack.subserver.config import resolve_sub_config_path
from proxystack.subserver.config import sub_server_config_to_yaml
from proxystack.subserver.config import SubServerConfig
from proxystack.subserver.watcher import create_input_watcher

LOGGER = logging.getLogger(__name__)
SUBSCRIPTION_TEMPLATE_NAMES = ("clash.yaml.j2", "premium-clash.yaml.j2", "surge.conf.j2")

app = typer.Typer(
    help="订阅服务管理命令。",
    no_args_is_help=True,
)


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出调试级日志。"),
) -> None:
    """初始化 sub CLI 的通用选项。"""
    configure_logging("DEBUG" if verbose else "INFO")
    echo_command_progress(ctx.invoked_subcommand)


def echo_command_progress(subcommand: str | None) -> None:
    """保留回调入口，实际进度由具体命令的 step 日志输出。"""
    return


def echo_command_error(exc: BaseException) -> None:
    """输出未进入 step 前的命令错误摘要。"""
    summary = summarize_exception(exc)
    typer.echo(f"Command failed: {summary.text}", err=True)
    if summary.detail_path is not None:
        typer.echo(f"Full output: {summary.detail_path}", err=True)


@app.command()
def version() -> None:
    """输出 proxystack-sub 版本，用于验证命令入口是否可用。"""
    typer.echo(f"proxystack-sub {get_distribution_version()}")


@app.command("config")
def config_command(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="ps-sub 配置文件路径。"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", help="订阅服务数据目录；未指定 --config 时用于推导配置路径。"),
    editor: Optional[str] = typer.Option(None, "--editor", help="覆盖 EDITOR，例如 --editor true。"),
    check_only: bool = typer.Option(False, "--check-only", help="只校验目标文件，不启动编辑器。"),
) -> None:
    """安全编辑 ps-sub config.yaml。"""
    try:
        config_path = resolve_sub_config_path(config, data_dir)
        default_data_dir = data_dir or config_path.parent
        ensure_sub_config_file(config_path, default_data_dir)
        path = edit_sub_config(config_path, default_data_dir, editor, check_only)
    except (OSError, ValueError) as exc:
        typer.echo(f"配置编辑失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"编辑校验通过：{path}")


@app.command("import")
def import_bundle(
    bundle_path: Path = typer.Argument(..., help="订阅发布包 zip 路径。"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="ps-sub 配置文件路径。"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", help="订阅服务数据目录；覆盖配置文件。"),
    replace_all: bool = typer.Option(False, "--replace-all", help="清空旧 inputs 后导入本发布包。"),
) -> None:
    """导入订阅发布包，只写入 inputs 目录。"""
    step_logger = StepLogger()
    try:
        sub_config = apply_cli_overrides(load_sub_server_config(config, data_dir=data_dir), data_dir=data_dir)
        with step_logger.step("import subscription bundle"):
            import_result = extract_bundle_inputs_with_result(bundle_path, sub_config.data_dir, replace_all=replace_all)
    except (OSError, ValueError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc
    echo_import_result(import_result)


@app.command("clear")
def clear(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="ps-sub 配置文件路径。"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", help="订阅服务数据目录；覆盖配置文件。"),
) -> None:
    """清空 inputs 目录中已导入的订阅节点。"""
    try:
        sub_config = apply_cli_overrides(load_sub_server_config(config, data_dir=data_dir), data_dir=data_dir)
        input_dir = sub_config.data_dir / "inputs"
        input_dir.mkdir(parents=True, exist_ok=True)
        removed_inputs = clear_managed_input_files(input_dir)
    except (OSError, ValueError) as exc:
        typer.echo(f"清空导入节点失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"已清空导入节点：inputs={len(removed_inputs)}")
    for input_name in removed_inputs:
        typer.echo(f"  - {input_name}")


@app.command("serve")
def serve(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="ps-sub 配置文件路径。"),
    host: Optional[str] = typer.Option(None, "--host", help="HTTP 服务监听 host；覆盖配置文件。"),
    port: Optional[int] = typer.Option(None, "--port", help="HTTP 服务监听端口；覆盖配置文件。"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", help="订阅服务数据目录；覆盖配置文件。"),
) -> None:
    """启动从 inputs 动态生成内存订阅索引的 HTTP 服务。"""
    step_logger = StepLogger()
    try:
        sub_config = apply_cli_overrides(
            load_sub_server_config(config, data_dir=data_dir, require_existing=True),
            data_dir=data_dir,
            host=host,
            port=port,
        )
        state = SubscriptionState(sub_config.data_dir, access=sub_config.access)
        log_subscription_server_configuration(sub_config)
        with step_logger.step("load subscription inputs"):
            state.load()
            log_subscription_server_loaded(sub_config, state)
        watcher = create_input_watcher(
            state.input_dir,
            state.reload,
            sub_config.watch_interval,
            sub_config.watch_debounce,
        )
        with step_logger.step("start subscription server"):
            uvicorn.run(
                create_app(
                    state,
                    watcher,
                    templates_dir=sub_config.templates_dir,
                    data_dir=sub_config.data_dir,
                    managed_config=sub_config.managed_config,
                ),
                host=sub_config.host,
                port=sub_config.port,
            )
    except (OSError, ValueError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc


def echo_import_result(import_result: BundleImportResult) -> None:
    """输出发布包导入摘要，不包含任何连接凭据。"""
    summary = import_result.summary
    typer.echo(
        f"订阅发布包已导入：source={summary.source} inputs={summary.input_count} "
        f"nodes={summary.node_count} users={summary.user_count} replace_all={str(import_result.replace_all).lower()}"
    )
    for input_summary in summary.inputs:
        action = "overwritten" if input_summary.name in import_result.replaced_inputs else "written"
        typer.echo(
            f"  - {action} {input_summary.name}: source={input_summary.source} "
            f"nodes={input_summary.nodes} users={input_summary.users}"
        )
    if import_result.removed_inputs:
        typer.echo("已删除旧 input：")
        for input_name in import_result.removed_inputs:
            typer.echo(f"  - {input_name}")


def ensure_sub_config_file(config_path: Path, default_data_dir: Path) -> None:
    """确保 ps-sub config.yaml 存在；缺失时写入可编辑默认配置。"""
    if config_path.exists():
        return
    config = default_sub_server_config(default_data_dir)
    write_text_if_changed(config_path, sub_server_config_to_yaml(config))


def edit_sub_config(
    config_path: Path,
    default_data_dir: Path,
    editor: Optional[str],
    check_only: bool,
) -> Path:
    """安全编辑 ps-sub config.yaml，校验通过后再替换原文件。"""
    if check_only:
        load_sub_server_config_file(config_path, default_data_dir)
        return config_path
    original_text = config_path.read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(original_text)
    try:
        run_editor(editor, temp_path)
        load_sub_server_config_file(temp_path, default_data_dir)
        edited_text = temp_path.read_text(encoding="utf-8")
        write_text_if_changed(config_path, edited_text)
    finally:
        temp_path.unlink(missing_ok=True)
    return config_path


def log_subscription_server_configuration(sub_config: SubServerConfig) -> None:
    """记录 ps-sub 启动配置摘要，避免日志中出现 token 明文。"""
    access_type = getattr(sub_config.access, "type", "unknown")
    LOGGER.info(
        "Subscription server configuration: data_dir=%s input_dir=%s listen=%s access=%s templates_dir=%s watch_interval=%s watch_debounce=%s",
        sub_config.data_dir,
        sub_config.data_dir / "inputs",
        sub_config.listen,
        access_type,
        sub_config.templates_dir,
        sub_config.watch_interval,
        sub_config.watch_debounce,
    )
    LOGGER.info(
        "Subscription server template sources: %s",
        format_template_sources(sub_config.templates_dir, sub_config.data_dir),
    )
    LOGGER.info(
        "Subscription server managed config: enabled=%s public_base_url=%s interval=%s strict=%s",
        str(sub_config.managed_config.enabled).lower(),
        sub_config.managed_config.public_base_url or "request-url",
        sub_config.managed_config.interval,
        str(sub_config.managed_config.strict).lower(),
    )


def log_subscription_server_loaded(sub_config: SubServerConfig, state: SubscriptionState) -> None:
    """记录启动时已加载内存索引的摘要。"""
    index = state.snapshot()
    LOGGER.info(
        "Subscription server loaded inputs: data_dir=%s input_dir=%s inputs=%d sources=%d nodes=%d users=%d",
        sub_config.data_dir,
        state.input_dir,
        len(index.sources),
        len(index.sources),
        len(index.nodes),
        len(index.users),
    )


def format_template_sources(templates_dir: Optional[Path], data_dir: Path) -> str:
    """格式化三类订阅模板的实际来源，用于启动日志。"""
    sources: list[str] = []
    for template_name in SUBSCRIPTION_TEMPLATE_NAMES:
        try:
            source = find_subscription_template_source(template_name, template_dir=templates_dir, data_dir=data_dir)
        except SubscriptionGeneratorError as exc:
            source = f"unavailable:{exc.__class__.__name__}"
        sources.append(f"{template_name}={source}")
    return " ".join(sources)


def run() -> None:
    """console script 入口，交给 Typer 处理命令解析。"""
    app()
