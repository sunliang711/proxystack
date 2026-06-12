"""proxystack-sub 订阅服务 CLI 入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import uvicorn

from proxystack.cli.common import get_distribution_version
from proxystack.generator.sub import extract_bundle_inputs
from proxystack.logging import configure_logging
from proxystack.logging import StepLogger
from proxystack.logging import summarize_exception
from proxystack.subserver import SubscriptionState
from proxystack.subserver import create_app
from proxystack.subserver.config import apply_cli_overrides
from proxystack.subserver.config import load_sub_server_config
from proxystack.subserver.watcher import create_input_watcher

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
            extract_bundle_inputs(bundle_path, sub_config.data_dir, replace_all=replace_all)
    except (OSError, ValueError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc


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
        with step_logger.step("load subscription inputs"):
            state.load()
        watcher = create_input_watcher(
            state.input_dir,
            state.reload,
            sub_config.watch_interval,
            sub_config.watch_debounce,
        )
        with step_logger.step("start subscription server"):
            uvicorn.run(create_app(state, watcher), host=sub_config.host, port=sub_config.port)
    except (OSError, ValueError) as exc:
        if step_logger.step_index == 0:
            echo_command_error(exc)
        raise typer.Exit(code=1) from exc


def run() -> None:
    """console script 入口，交给 Typer 处理命令解析。"""
    app()
