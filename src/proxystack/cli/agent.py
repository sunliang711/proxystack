"""proxystack-agent 本地管理 CLI 入口。"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
import typer

from proxystack.cli.common import get_distribution_version
from proxystack.config import DEFAULT_CONFIG_PATH
from proxystack.config import load_config
from proxystack.config import load_stacks
from proxystack.domain import ConfigValidationError
from proxystack.logging import configure_logging

app = typer.Typer(
    help="本地代理栈管理命令。",
    no_args_is_help=True,
)


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


def run() -> None:
    """console script 入口，交给 Typer 处理命令解析。"""
    app()
