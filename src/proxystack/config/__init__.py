"""配置加载入口。"""

from proxystack.config.loader import DEFAULT_CONFIG_PATH
from proxystack.config.loader import load_config
from proxystack.config.loader import load_config_file
from proxystack.config.loader import load_stack
from proxystack.config.loader import load_stacks

__all__ = ["DEFAULT_CONFIG_PATH", "load_config", "load_config_file", "load_stack", "load_stacks"]
