"""mihomo 配置生成器入口。"""

from proxystack.generator.mihomo.config import MihomoGeneratorError
from proxystack.generator.mihomo.config import dumps_mihomo_config
from proxystack.generator.mihomo.config import normalize_internal_endpoint_address
from proxystack.generator.mihomo.config import render_mihomo_config

__all__ = [
    "MihomoGeneratorError",
    "dumps_mihomo_config",
    "normalize_internal_endpoint_address",
    "render_mihomo_config",
]
