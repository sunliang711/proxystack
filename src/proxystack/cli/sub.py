"""proxystack-sub 订阅服务 CLI 入口。"""

from __future__ import annotations

from pathlib import Path
import json
import os

import typer
import uvicorn

from proxystack.cli.common import get_distribution_version
from proxystack.generator.sub import SubscriptionAccess
from proxystack.generator.sub import SubscriptionGeneratorError
from proxystack.generator.sub import extract_bundle_inputs
from proxystack.generator.sub import index_to_json
from proxystack.generator.sub import merge_input_files
from proxystack.logging import configure_logging
from proxystack.subserver import create_app

DEFAULT_DATA_DIR = Path("/opt/proxystack/sub")

app = typer.Typer(
    help="订阅服务管理命令。",
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


@app.command("import")
def import_bundle(
    bundle_path: Path = typer.Argument(..., help="订阅发布包 zip 路径。"),
    data_dir: Path = typer.Option(DEFAULT_DATA_DIR, "--data-dir", help="订阅服务数据目录。"),
    no_rebuild: bool = typer.Option(False, "--no-rebuild", help="仅导入 inputs，不自动 rebuild。"),
) -> None:
    """导入订阅发布包，校验 manifest 和 input hash。"""
    try:
        manifest = extract_bundle_inputs(bundle_path, data_dir)
        write_access_file(data_dir, manifest.access)
        if not no_rebuild:
            rebuild_data_dir(data_dir)
    except (OSError, SubscriptionGeneratorError) as exc:
        typer.echo(f"订阅发布包导入失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"订阅发布包已导入：{bundle_path}")


@app.command("rebuild")
def rebuild(
    data_dir: Path = typer.Option(DEFAULT_DATA_DIR, "--data-dir", help="订阅服务数据目录。"),
) -> None:
    """扫描 data_dir/inputs 并原子写入 current/index.json。"""
    try:
        index_path = rebuild_data_dir(data_dir)
    except (OSError, SubscriptionGeneratorError) as exc:
        typer.echo(f"订阅索引重建失败：\n{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"订阅索引已重建：{index_path}")


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="HTTP 服务监听 host。"),
    port: int = typer.Option(3003, "--port", help="HTTP 服务监听端口。"),
    data_dir: Path = typer.Option(DEFAULT_DATA_DIR, "--data-dir", help="订阅服务数据目录。"),
) -> None:
    """启动只读取 current/index.json 的订阅 HTTP 服务。"""
    uvicorn.run(create_app(data_dir), host=host, port=port)


def rebuild_data_dir(data_dir: Path) -> Path:
    """根据 data_dir/inputs 生成订阅索引并原子写入 current/index.json。"""
    access = read_access_file(data_dir)
    index = merge_input_files(data_dir / "inputs", access=access)
    current_dir = data_dir / "current"
    current_dir.mkdir(parents=True, exist_ok=True)
    index_path = current_dir / "index.json"
    tmp_path = current_dir / "index.json.tmp"
    tmp_path.write_text(index_to_json(index), encoding="utf-8")
    os.replace(tmp_path, index_path)
    return index_path


def write_access_file(data_dir: Path, access: SubscriptionAccess) -> None:
    """保存发布包中的 access 信息，供 rebuild 写入 index。"""
    access_dir = data_dir / "bundles"
    access_dir.mkdir(parents=True, exist_ok=True)
    access_path = access_dir / "access.json"
    access_path.write_text(json.dumps(access.model_dump(mode="json", exclude_none=True), indent=2), encoding="utf-8")


def read_access_file(data_dir: Path) -> SubscriptionAccess:
    """读取 data_dir/bundles/access.json；缺失时默认不启用 token 鉴权。"""
    access_path = data_dir / "bundles" / "access.json"
    if not access_path.exists():
        return SubscriptionAccess()
    try:
        return SubscriptionAccess.model_validate(json.loads(access_path.read_text(encoding="utf-8")))
    except ValueError as exc:
        raise SubscriptionGeneratorError(f"invalid access file: {access_path}") from exc


def run() -> None:
    """console script 入口，交给 Typer 处理命令解析。"""
    app()
