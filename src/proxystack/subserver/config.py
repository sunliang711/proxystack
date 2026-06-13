"""订阅服务独立配置加载。"""

from __future__ import annotations

from importlib import resources
from io import StringIO
from pathlib import Path
from typing import Any
from typing import Optional
from urllib.parse import urlsplit

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic import field_validator
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from proxystack.domain.models import parse_listen
from proxystack.generator.sub import SubscriptionAccess
from proxystack.generator.sub import SubscriptionGeneratorError

DEFAULT_SUB_DATA_DIR = Path("/opt/proxystack/sub")
DEFAULT_SUB_CONFIG_PATH = DEFAULT_SUB_DATA_DIR / "config.yaml"
DEFAULT_SUB_LISTEN = "0.0.0.0:3003"
DEFAULT_SUB_TEMPLATE_NAME = "sub-config.yaml"
DEFAULT_SUB_TEMPLATES_DIR = DEFAULT_SUB_DATA_DIR / "templates"
DEFAULT_MANAGED_CONFIG_INTERVAL = 86400


class ManagedConfig(BaseModel):
    """Surge 托管配置头生成参数。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool = True
    public_base_url: Optional[str] = None
    interval: int = Field(default=DEFAULT_MANAGED_CONFIG_INTERVAL, gt=0)
    strict: bool = True

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: Optional[str]) -> Optional[str]:
        """校验公开 URL 前缀，只允许 http/https 且不携带 query 或 fragment。"""
        if value is None:
            return value
        parsed_url = urlsplit(value)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("managed_config.public_base_url must be an http or https URL")
        if parsed_url.query or parsed_url.fragment:
            raise ValueError("managed_config.public_base_url must not include query or fragment")
        return value.rstrip("/")


class SubServerConfig(BaseModel):
    """ps-sub 运行配置，只描述订阅服务自身需要的参数。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    data_dir: Path = DEFAULT_SUB_DATA_DIR
    listen: str = DEFAULT_SUB_LISTEN
    access: SubscriptionAccess = Field(default_factory=SubscriptionAccess)
    templates_dir: Optional[Path] = None
    watch_interval: float = Field(default=2.0, gt=0)
    watch_debounce: float = Field(default=0.3, ge=0)
    managed_config: ManagedConfig = Field(default_factory=ManagedConfig)

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
        return default_sub_server_config(data_dir or DEFAULT_SUB_DATA_DIR)
    try:
        return load_sub_server_config_file(config_path, data_dir or config_path.parent)
    except (ValueError, ValidationError) as exc:
        raise SubscriptionGeneratorError(f"invalid sub config file: {config_path}") from exc


def load_sub_server_config_file(path: Path, default_data_dir: Path) -> SubServerConfig:
    """读取指定 ps-sub 配置文件，并用给定目录补齐缺省 data_dir。"""
    config_data = load_yaml_mapping(path)
    if "data_dir" not in config_data:
        config_data["data_dir"] = default_data_dir
    return SubServerConfig.model_validate(config_data)


def default_sub_server_config(default_data_dir: Path = DEFAULT_SUB_DATA_DIR) -> SubServerConfig:
    """读取内置 ps-sub 模板并按目标 data_dir 生成默认配置。"""
    config_data = read_builtin_sub_config_template()
    if config_data is None:
        return SubServerConfig(data_dir=default_data_dir)
    config_data["data_dir"] = default_data_dir
    templates_dir = config_data.get("templates_dir")
    if templates_dir is not None and Path(str(templates_dir)) == DEFAULT_SUB_TEMPLATES_DIR:
        config_data["templates_dir"] = default_data_dir / "templates"
    return SubServerConfig.model_validate(config_data)


def read_builtin_sub_config_template() -> Optional[dict[str, Any]]:
    """读取包内 sub-config.yaml；缺失时返回 None 以便使用模型默认值。"""
    try:
        template_path = resources.files("proxystack").joinpath("templates", DEFAULT_SUB_TEMPLATE_NAME)
        template_text = template_path.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        return None
    return load_yaml_text_mapping(template_text, DEFAULT_SUB_TEMPLATE_NAME)


def sub_server_config_to_yaml(config: SubServerConfig) -> str:
    """把 ps-sub 配置对象编码为可编辑 YAML。"""
    yaml = YAML()
    yaml.default_flow_style = False
    stream = StringIO()
    yaml.dump(sub_server_config_to_commented_mapping(config), stream)
    return stream.getvalue()


def sub_server_config_to_mapping(config: SubServerConfig) -> dict[str, Any]:
    """把 ps-sub 配置对象转换为 YAML 输出 mapping，保留需要用户编辑的空占位。"""
    config_data = config.model_dump(mode="json", exclude_none=True)
    config_data["managed_config"] = config.managed_config.model_dump(mode="json", exclude_none=False)
    return config_data


def sub_server_config_to_commented_mapping(config: SubServerConfig) -> CommentedMap:
    """把 ps-sub 配置对象转换为带字段说明的 YAML mapping。"""
    config_data = to_commented_mapping(sub_server_config_to_mapping(config))
    apply_sub_config_comments(config_data)
    return config_data


def to_commented_mapping(config_data: dict[str, Any]) -> CommentedMap:
    """递归转换普通 dict，供 ruamel.yaml 输出注释。"""
    commented = CommentedMap()
    for key, value in config_data.items():
        if isinstance(value, dict):
            commented[key] = to_commented_mapping(value)
        else:
            commented[key] = value
    return commented


def apply_sub_config_comments(config_data: CommentedMap) -> None:
    """为 ps-sub 配置各字段添加可编辑说明。"""
    comments: dict[tuple[str, ...], str] = {
        ("data_dir",): "订阅服务数据目录；inputs 子目录会存放导入的订阅发布包内容。",
        ("listen",): "HTTP 服务监听地址，格式为 host:port。",
        ("access",): "订阅访问控制配置；生产环境建议使用 token。",
        ("access", "type"): "访问控制类型；支持 none、token。",
        ("access", "token"): "token 模式使用的访问令牌；type=token 时必须填写。",
        ("templates_dir",): "订阅模板覆盖目录；不需要自定义模板时可保持默认。",
        ("watch_interval",): "inputs 目录轮询间隔，单位秒；inotify 不可用时生效。",
        ("watch_debounce",): "inputs 变更防抖时间，单位秒；避免保存过程触发重复加载。",
        ("managed_config",): "Surge 托管配置头参数；用于 /surge_sub/:user 输出 #!MANAGED-CONFIG。",
        ("managed_config", "enabled"): "是否输出 Surge 托管配置头。",
        ("managed_config", "public_base_url"): "公网访问前缀；反代部署时填写，例如 https://example.com/api/sub；留空时使用请求 URL。",
        ("managed_config", "interval"): "Surge 托管配置刷新间隔，单位秒。",
        ("managed_config", "strict"): "是否启用 Surge strict 模式。",
    }
    for key_path, comment in comments.items():
        set_comment_before_key(config_data, key_path, comment)


def set_comment_before_key(config_data: CommentedMap, key_path: tuple[str, ...], comment: str) -> None:
    """按路径给存在的配置项添加前置注释。"""
    target = config_data
    for key in key_path[:-1]:
        next_target = target.get(key)
        if not isinstance(next_target, CommentedMap):
            return
        target = next_target
    final_key = key_path[-1]
    if final_key in target:
        target.yaml_set_comment_before_after_key(final_key, before=comment, indent=2 * (len(key_path) - 1))


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
    try:
        return load_yaml_text_mapping(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        raise ValueError(f"Sub config file could not be read: {path}") from exc


def load_yaml_text_mapping(text: str, source: str) -> dict[str, Any]:
    """读取 YAML 文本并要求顶层是 mapping。"""
    yaml = YAML(typ="safe")
    try:
        loaded = yaml.load(text)
    except YAMLError as exc:
        raise ValueError(f"Sub config file contains invalid YAML: {source}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Sub config file must be a mapping: {source}")
    return loaded
