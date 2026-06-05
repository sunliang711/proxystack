"""配置文件加载基础能力。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

DEFAULT_CONFIG_PATH = Path("/opt/proxystack/config.yaml")


def load_config_file(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """读取 YAML 配置文件并返回映射，后续 Task 会在此基础上接入 Pydantic 模型。"""
    yaml = YAML(typ="safe")
    with path.open("r", encoding="utf-8") as config_file:
        loaded_config = yaml.load(config_file)
    if loaded_config is None:
        return {}
    if not isinstance(loaded_config, dict):
        raise ValueError(f"Config file must be a mapping: {path}")
    return loaded_config
