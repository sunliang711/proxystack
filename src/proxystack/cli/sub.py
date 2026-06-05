"""proxystack-sub 订阅服务 CLI 入口。"""

from __future__ import annotations

import typer

from proxystack.cli.common import get_distribution_version
from proxystack.logging import configure_logging

app = typer.Typer(
    help="订阅服务管理命令。当前 Task 01 仅提供项目骨架和版本检查。",
    no_args_is_help=True,
)


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出调试级日志。"),
) -> None:
    """初始化 sub CLI 的通用选项。"""
    configure_logging("DEBUG" if verbose else "INFO")


@app.command()
def version() -> None:
    """输出 proxystack-sub 版本，用于验证命令入口是否可用。"""
    typer.echo(f"proxystack-sub {get_distribution_version()}")


def run() -> None:
    """console script 入口，交给 Typer 处理命令解析。"""
    app()
