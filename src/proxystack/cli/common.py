"""CLI 共享工具函数。"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

from proxystack import __version__


def get_distribution_version(distribution_name: str = "proxystack") -> str:
    """读取已安装发行包版本，源码运行时回退到包内版本。"""
    try:
        return package_version(distribution_name)
    except PackageNotFoundError:
        return __version__
