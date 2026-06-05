"""Xray 配置生成器入口。"""

from proxystack.generator.xray.config import XrayGeneratorError
from proxystack.generator.xray.config import dumps_xray_config
from proxystack.generator.xray.config import normalize_internal_endpoint_address
from proxystack.generator.xray.config import render_xray_config

__all__ = [
    "XrayGeneratorError",
    "dumps_xray_config",
    "normalize_internal_endpoint_address",
    "render_xray_config",
]
