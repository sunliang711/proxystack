"""构建 proxystack wheel 和 sdist 发布产物。"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import shutil

from setuptools import build_meta


def parse_args() -> ArgumentParser:
    """创建命令行参数解析器，供项目构建脚本复用。"""
    parser = ArgumentParser(description="Build proxystack wheel and sdist artifacts.")
    parser.add_argument("--dist-dir", default="dist", help="Directory for build artifacts.")
    parser.add_argument("--no-clean", action="store_true", help="Do not remove dist directory before building.")
    return parser


def clean_build_state(
    dist_dir: Path,
    no_clean: bool,
    build_dir: Path = Path("build"),
    egg_info_dir: Path = Path("src/proxystack.egg-info"),
) -> None:
    """按需清理构建状态，避免旧文件混入本次 wheel 或 sdist。"""
    if no_clean:
        return
    shutil.rmtree(dist_dir, ignore_errors=True)
    shutil.rmtree(build_dir, ignore_errors=True)
    shutil.rmtree(egg_info_dir, ignore_errors=True)


def build_artifacts(dist_dir: Path) -> tuple[str, str]:
    """使用 setuptools build backend 生成 sdist 和 wheel。"""
    dist_dir.mkdir(parents=True, exist_ok=True)
    sdist_name = build_meta.build_sdist(str(dist_dir))
    wheel_name = build_meta.build_wheel(str(dist_dir))
    return sdist_name, wheel_name


def main() -> None:
    """执行项目发布构建并输出生成的文件名。"""
    parser = parse_args()
    args = parser.parse_args()
    dist_dir = Path(args.dist_dir)
    clean_build_state(dist_dir, args.no_clean)
    sdist_name, wheel_name = build_artifacts(dist_dir)
    print(f"Built sdist: {dist_dir / sdist_name}")
    print(f"Built wheel: {dist_dir / wheel_name}")


if __name__ == "__main__":
    main()
