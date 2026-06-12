"""订阅服务独立配置加载。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Optional

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic import field_validator
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from proxystack.domain.models import parse_listen
from proxystack.generator.sub import SubscriptionAccess
from proxystack.generator.sub import SubscriptionGeneratorError

DEFAULT_SUB_DATA_DIR = Path("/opt/proxystack/sub")
DEFAULT_SUB_CONFIG_PATH = DEFAULT_SUB_DATA_DIR / "config.yaml"


class SubServerConfig(BaseModel):
    """ps-sub 运行配置，只描述订阅服务自身需要的参数。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    data_dir: Path = DEFAULT_SUB_DATA_DIR
    listen: str = "127.0.0.1:3003"
    access: SubscriptionAccess = Field(default_factory=SubscriptionAccess)
    watch_interval: float = Field(default=2.0, gt=0)
    watch_debounce: float = Field(default=0.3, ge=0)

    @field_validator("listen")
    @classmethod
    def validate_listen(cls, value: str) -> str:
        """校验监听地址格式，避免 serve 阶段才暴露配置错误。"""
        parse_listen(value)
        return value

    @property
    def host(self) -> str:
        """返回 listen 中的 host，供 uvicorn.run 使用。"""
        host, _port = parse_listen(self.listen)
        return host

    @property
    def port(self) -> int:
        """返回 listen 中的 port，供 uvicorn.run 使用。"""
        _host, port = parse_listen(self.listen)
        return port


def load_sub_server_config(
    path: Optional[Path],
    data_dir: Optional[Path] = None,
    require_existing: bool = False,
) -> SubServerConfig:
    """读取 ps-sub 配置；未显式指定且文件缺失时使用默认值。"""
    config_path = resolve_sub_config_path(path, data_dir)
    if not config_path.exists():
        if path is not None or require_existing:
            raise SubscriptionGeneratorError(f"sub config file could not be read: {config_path}")
        return SubServerConfig(data_dir=data_dir or DEFAULT_SUB_DATA_DIR)
    try:
        config_data = load_yaml_mapping(config_path)
        if "data_dir" not in config_data:
            config_data["data_dir"] = config_path.parent
        return SubServerConfig.model_validate(config_data)
    except (ValueError, ValidationError) as exc:
        raise SubscriptionGeneratorError(f"invalid sub config file: {config_path}") from exc


def resolve_sub_config_path(path: Optional[Path], data_dir: Optional[Path]) -> Path:
    """按 CLI 参数推导默认 ps-sub 配置路径。"""
    if path is not None:
        return path
    if data_dir is not None:
        return data_dir / "config.yaml"
    return DEFAULT_SUB_CONFIG_PATH


def apply_cli_overrides(
    config: SubServerConfig,
    data_dir: Optional[Path] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> SubServerConfig:
    """把 CLI 显式参数覆盖到 ps-sub 配置对象上。"""
    listen_host, listen_port = parse_listen(config.listen)
    next_listen = f"{host or listen_host}:{port or listen_port}"
    config_data = config.model_dump(mode="python")
    config_data["data_dir"] = data_dir or config.data_dir
    config_data["listen"] = next_listen
    return SubServerConfig.model_validate(config_data)


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """读取 ps-sub YAML 配置并要求顶层是 mapping。"""
    yaml = YAML(typ="safe")
    try:
        with path.open("r", encoding="utf-8") as config_file:
            loaded = yaml.load(config_file)
    except OSError as exc:
        raise ValueError(f"Sub config file could not be read: {path}") from exc
    except YAMLError as exc:
        raise ValueError(f"Sub config file contains invalid YAML: {path}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Sub config file must be a mapping: {path}")
    return loaded
