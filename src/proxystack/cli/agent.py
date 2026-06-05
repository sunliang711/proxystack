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
app.add_typer(render_app, name="render")


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


def format_service_node(node: ServiceNode) -> str:
    """格式化服务节点，供 CLI plan 输出使用。"""
    return f"{node.label()} ({node.service_name()})"


def run() -> None:
    """console script 入口，交给 Typer 处理命令解析。"""
    app()
