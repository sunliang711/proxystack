"""proxystack 配置领域模型。"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from string import Formatter
from typing import Annotated
from typing import Any
from typing import Optional
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

Port = Annotated[int, Field(ge=1, le=65535)]
Name = Annotated[str, Field(min_length=1)]
Region = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
BUILTIN_RULE_TARGETS = {"DIRECT", "REJECT"}
SUBSCRIPTION_REMARK_TEMPLATE_FIELDS = {"source", "inbound", "protocol", "port", "user", "remark"}
SHADOWSOCKS_2022_METHODS = {
    "2022-blake3-aes-128-gcm",
    "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305",
}
SHADOWSOCKS_2022_KEY_LENGTHS = {
    "2022-blake3-aes-128-gcm": 16,
    "2022-blake3-aes-256-gcm": 32,
    "2022-blake3-chacha20-poly1305": 32,
}


class ProxystackModel(BaseModel):
    """项目配置模型基类，保留未来生成器可能需要的扩展字段。"""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class ConfigPaths(ProxystackModel):
    """全局路径配置，所有相对路径都相对 base_dir 解析。"""

    bin: str = "bin"
    geo: str = "geo"
    stacks: str = "stacks"
    runtime: str = "runtime"
    generated: str = "runtime/generated"
    publish: str = "publish"
    downloads: str = "downloads"
    sub: str = "sub"


class SubscriptionConfig(ProxystackModel):
    """订阅服务和发布包默认配置。"""

    source: Literal["local"] = "local"
    remark_policy: Literal["preserve", "prefix-source", "template"] = "prefix-source"
    remark_template: Optional[str] = None

    @field_validator("remark_template")
    @classmethod
    def validate_remark_template(cls, value: Optional[str]) -> Optional[str]:
        """校验订阅节点名模板只使用明确支持的占位符。"""
        if value is None:
            return value
        for _literal_text, field_name, _format_spec, _conversion in Formatter().parse(value):
            if field_name is None:
                continue
            if field_name not in SUBSCRIPTION_REMARK_TEMPLATE_FIELDS:
                raise ValueError(f"unsupported subscription remark template field: {field_name}")
        return value

    @model_validator(mode="after")
    def validate_remark_policy(self) -> "SubscriptionConfig":
        """校验 template 策略必须提供订阅节点名模板。"""
        if self.remark_policy == "template" and not self.remark_template:
            raise ValueError("remark_template is required when remark_policy is template")
        return self


class PortRange(ProxystackModel):
    """端口池范围，支持从 `start-end` 字符串解析。"""

    start: Port
    end: Port

    @model_validator(mode="before")
    @classmethod
    def parse_range(cls, value: Any) -> Any:
        """把 YAML 中的 `24000-24999` 字符串转换为结构化范围。"""
        if isinstance(value, str):
            parts = value.split("-", 1)
            if len(parts) != 2:
                raise ValueError("port range must use start-end format")
            return {"start": int(parts[0]), "end": int(parts[1])}
        return value

    @model_validator(mode="after")
    def validate_order(self) -> "PortRange":
        """校验端口池起始端口不大于结束端口。"""
        if self.start > self.end:
            raise ValueError("port range start must be less than or equal to end")
        return self

    def allocate(self, used_ports: set[int], count: int = 1) -> list[int]:
        """从端口池中稳定分配指定数量的未使用端口。"""
        allocated_ports: list[int] = []
        unavailable_ports = set(used_ports)
        for port in range(self.start, self.end + 1):
            if port in unavailable_ports:
                continue
            allocated_ports.append(port)
            unavailable_ports.add(port)
            if len(allocated_ports) == count:
                return allocated_ports
        raise ValueError("not enough available ports in range")


class PortRanges(ProxystackModel):
    """全局自动分配端口池。"""

    xrelay_inbound: PortRange
    clash_socks: PortRange
    clash_controller: PortRange


class DefaultClashConfig(ProxystackModel):
    """clash 默认配置。"""

    mode: Literal["Rule", "Global", "Direct"] = "Rule"
    rule_profile: Literal["default"] = "default"


class XrelayApiConfig(ProxystackModel):
    """Xray API 配置，只允许监听本机回环地址。"""

    enabled: bool = True
    tag: Name = "api"
    listen: str = "127.0.0.1:10085"
    services: list[str] = Field(default_factory=lambda: ["StatsService"], min_length=1)

    @field_validator("tag")
    @classmethod
    def validate_tag(cls, value: str) -> str:
        """校验 API tag 适合作为 Xray 出站标识。"""
        validate_identifier(value, "xray api tag")
        return value

    @field_validator("listen")
    @classmethod
    def validate_listen(cls, value: str) -> str:
        """校验 API 监听地址必须是 loopback host 和合法端口。"""
        host, _ = parse_listen(value)
        if not is_loopback_listen_host(host):
            raise ValueError("xray api listen must use loopback host")
        return value

    @field_validator("services")
    @classmethod
    def validate_services(cls, value: list[str]) -> list[str]:
        """校验 API services 至少包含一个非空服务名。"""
        for service in value:
            if not service:
                raise ValueError("xray api service name is required")
        return value


class XrelayStatsConfig(ProxystackModel):
    """Xray stats 配置开关。"""

    enabled: bool = True


class XrelayPolicySystemConfig(ProxystackModel):
    """Xray system policy 中与全局流量统计相关的配置。"""

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)

    stats_inbound_uplink: Optional[bool] = Field(default=None, alias="statsInboundUplink")
    stats_inbound_downlink: Optional[bool] = Field(default=None, alias="statsInboundDownlink")
    stats_outbound_uplink: Optional[bool] = Field(default=None, alias="statsOutboundUplink")
    stats_outbound_downlink: Optional[bool] = Field(default=None, alias="statsOutboundDownlink")


class XrelayPolicyLevelConfig(ProxystackModel):
    """Xray level policy 中与用户流量统计相关的配置。"""

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)

    stats_user_uplink: Optional[bool] = Field(default=None, alias="statsUserUplink")
    stats_user_downlink: Optional[bool] = Field(default=None, alias="statsUserDownlink")


def default_xrelay_policy_levels() -> dict[str, XrelayPolicyLevelConfig]:
    """返回默认 level 0 用户流量统计配置。"""
    return {
        "0": XrelayPolicyLevelConfig(
            statsUserUplink=True,
            statsUserDownlink=True,
        ),
    }


class XrelayPolicyConfig(ProxystackModel):
    """Xray policy 配置，支持 system 和 levels 统计字段。"""

    enabled: bool = True
    levels: dict[str, XrelayPolicyLevelConfig] = Field(default_factory=default_xrelay_policy_levels)
    system: XrelayPolicySystemConfig = Field(default_factory=XrelayPolicySystemConfig)


class DefaultXrelayConfig(ProxystackModel):
    """xrelay 默认配置。"""

    loglevel: str = "warning"
    api: XrelayApiConfig = Field(default_factory=XrelayApiConfig)
    stats: XrelayStatsConfig = Field(default_factory=XrelayStatsConfig)
    policy: XrelayPolicyConfig = Field(default_factory=XrelayPolicyConfig)


class DefaultsConfig(ProxystackModel):
    """全局默认值配置。"""

    clash: DefaultClashConfig = Field(default_factory=DefaultClashConfig)
    xrelay: DefaultXrelayConfig = Field(default_factory=DefaultXrelayConfig)


class SecurityConfig(ProxystackModel):
    """安全策略配置。"""

    require_auth_for_public_socks_http: bool = True
    allow_noauth_public: bool = False


class InstallToolConfig(ProxystackModel):
    """单个二进制安装策略配置。"""

    version: str = "latest"
    source: Optional[str] = None
    sha256: Optional[str] = None
    archive_member: Optional[str] = None


class InstallConfig(ProxystackModel):
    """代理核心安装配置。"""

    mihomo: InstallToolConfig = Field(default_factory=InstallToolConfig)
    xray: InstallToolConfig = Field(default_factory=InstallToolConfig)
    geo: InstallToolConfig = Field(default_factory=InstallToolConfig)


class GlobalConfig(ProxystackModel):
    """全局配置模型，对应 `/opt/proxystack/config.yaml`。"""

    version: Literal[1] = 1
    base_dir: Path = Path("/opt/proxystack")
    paths: ConfigPaths = Field(default_factory=ConfigPaths)
    external_host: str
    subscription: SubscriptionConfig = Field(default_factory=SubscriptionConfig)
    port_ranges: PortRanges
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    install: InstallConfig = Field(default_factory=InstallConfig)
    config_path: Optional[Path] = Field(default=None, exclude=True)

    def resolve_path(self, path_value: str) -> Path:
        """把全局配置中的路径值解析为实际文件系统路径。"""
        candidate_path = Path(path_value)
        if candidate_path.is_absolute():
            return candidate_path
        return self.base_dir / candidate_path

    @property
    def stacks_dir(self) -> Path:
        """返回 stack 配置目录。"""
        return self.resolve_path(self.paths.stacks)


class InboundAuth(ProxystackModel):
    """xrelay socks/http inbound 鉴权配置。"""

    type: Literal["noauth", "password"]
    username: Optional[str] = None
    password: Optional[str] = None

    @model_validator(mode="after")
    def validate_password_auth(self) -> "InboundAuth":
        """校验 password 鉴权必须同时提供用户名和密码。"""
        if self.type == "password" and (not self.username or not self.password):
            raise ValueError("username and password are required for password auth")
        return self


class InboundUser(ProxystackModel):
    """xrelay vmess/shadowsocks inbound 的单个客户端用户配置。"""

    user: Name
    uuid: Optional[str] = None
    password: Optional[str] = None
    method: Optional[str] = None
    cipher: Optional[str] = None
    email: Optional[str] = None
    remark: Optional[str] = None
    region: Optional[Region] = None
    tag: Optional[Name] = None

    @field_validator("uuid")
    @classmethod
    def validate_user_uuid(cls, value: Optional[str]) -> Optional[str]:
        """校验 vmess 客户端 UUID 格式，未配置时交给协议级校验处理。"""
        if value is not None:
            validate_uuid(value, "uuid is required for vmess user")
        return value


class Inbound(ProxystackModel):
    """xrelay inbound 配置。"""

    name: Name
    protocol: Literal["vmess", "shadowsocks", "socks5", "http"]
    listen: str = "0.0.0.0"
    port: Port
    udp: bool = False
    auth: Optional[InboundAuth] = None
    user: Optional[str] = None
    server: Optional[str] = None
    remark: Optional[str] = None
    region: Optional[Region] = None
    tag: Optional[str] = None
    sub: bool
    uuid: Optional[str] = None
    users: list[InboundUser] = Field(default_factory=list)
    network: Optional[str] = None
    password: Optional[str] = None
    method: Optional[str] = None
    cipher: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def validate_users_field_protocol(cls, value: Any) -> Any:
        """校验 users 字段只能显式用于 vmess 或 shadowsocks inbound。"""
        if (
            isinstance(value, dict)
            and value.get("protocol") is not None
            and value.get("protocol") not in {"vmess", "shadowsocks"}
            and "users" in value
        ):
            raise ValueError("users is only supported for vmess or shadowsocks inbound")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """校验 inbound 名称适合作为 ref 片段。"""
        validate_identifier(value, "inbound name")
        return value

    @model_validator(mode="after")
    def validate_protocol_credentials(self) -> "Inbound":
        """校验不同协议所需的明文凭据字段。"""
        if self.protocol == "vmess":
            if self.uuid:
                raise ValueError("uuid is not supported for vmess inbound; use users instead")
            if self.user or self.remark:
                raise ValueError("user and remark must be configured under vmess users")
            if not self.users:
                raise ValueError("users is required for vmess inbound")
            self.validate_vmess_users()
            if not self.network:
                raise ValueError("network is required for vmess inbound")
        if self.protocol == "shadowsocks":
            if not self.password:
                raise ValueError("password is required for shadowsocks inbound")
            if not (self.method or self.cipher):
                raise ValueError("method or cipher is required for shadowsocks inbound")
            self.validate_shadowsocks_2022_passwords()
            if self.users:
                if self.user or self.remark:
                    raise ValueError("user and remark must be configured under shadowsocks users")
                self.validate_shadowsocks_users()
        if self.protocol in {"socks5", "http"} and self.sub:
            if not self.auth or self.auth.type != "password":
                raise ValueError("password auth is required when socks/http inbound is published")
        return self

    def validate_vmess_users(self) -> None:
        """校验 vmess 多用户配置中的用户、UUID、email 和最终订阅 tag 不重复。"""
        ensure_unique([vmess_user.user for vmess_user in self.users], "duplicate vmess user")
        for vmess_user in self.users:
            if not vmess_user.uuid:
                raise ValueError("uuid is required for vmess user")
        ensure_unique([vmess_user.uuid.lower() for vmess_user in self.users if vmess_user.uuid], "duplicate vmess uuid")
        ensure_unique([inbound_user_email(vmess_user) for vmess_user in self.users], "duplicate vmess user email")
        base_tag = self.tag or f"{self.protocol}:{self.port}:{self.name}"
        ensure_unique(
            [vmess_user.tag or f"{base_tag}:{vmess_user.user}" for vmess_user in self.users],
            "duplicate vmess user tag",
        )

    def validate_shadowsocks_users(self) -> None:
        """校验 shadowsocks 多用户配置中的用户、email、密码、method 和最终订阅 tag。"""
        ensure_unique([shadowsocks_user.user for shadowsocks_user in self.users], "duplicate shadowsocks user")
        ensure_unique(
            [inbound_user_email(shadowsocks_user) for shadowsocks_user in self.users],
            "duplicate shadowsocks user email",
        )
        base_tag = self.tag or f"{self.protocol}:{self.port}:{self.name}"
        ensure_unique(
            [shadowsocks_user.tag or f"{base_tag}:{shadowsocks_user.user}" for shadowsocks_user in self.users],
            "duplicate shadowsocks user tag",
        )
        inbound_method = self.method or self.cipher or ""
        for shadowsocks_user in self.users:
            if not shadowsocks_user.password:
                raise ValueError("password is required for shadowsocks user")
            if is_shadowsocks_2022_method(inbound_method) and (shadowsocks_user.method or shadowsocks_user.cipher):
                raise ValueError("shadowsocks 2022 users must not set method or cipher")

    def validate_shadowsocks_2022_passwords(self) -> None:
        """校验 SS2022 的 ServerPassword 和 UserPassword 都是合法 base64 PSK。"""
        inbound_method = self.method or self.cipher or ""
        if not is_shadowsocks_2022_method(inbound_method):
            return
        validate_shadowsocks_2022_psk(
            self.password or "",
            inbound_method,
            "shadowsocks 2022 inbound password",
        )
        for shadowsocks_user in self.users:
            if not shadowsocks_user.password:
                continue
            validate_shadowsocks_2022_psk(
                shadowsocks_user.password,
                inbound_method,
                f"shadowsocks 2022 user password for {shadowsocks_user.user}",
            )


def inbound_user_email(inbound_user: InboundUser) -> str:
    """返回 Xray 用户统计 email，未显式配置时使用业务 user 标识。"""
    return inbound_user.email or inbound_user.user


def is_shadowsocks_2022_method(method: str) -> bool:
    """判断 shadowsocks method 是否属于 SS2022 方法。"""
    return method in SHADOWSOCKS_2022_METHODS


def validate_shadowsocks_2022_psk(value: str, method: str, label: str) -> None:
    """校验 SS2022 PSK 是 base64 字符串，且解码长度符合 method 要求。"""
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ValueError(f"{label} must be a base64-encoded PSK for {method}") from exc
    expected_length = SHADOWSOCKS_2022_KEY_LENGTHS[method]
    if len(decoded) != expected_length:
        raise ValueError(f"{label} must decode to {expected_length} bytes for {method}")


class XrelayOutbound(ProxystackModel):
    """xrelay outbound 配置。"""

    type: Literal["clash", "socks5", "http", "direct"]
    ref: Optional[str] = None
    server: Optional[str] = None
    port: Optional[Port] = None
    username: Optional[str] = None
    password: Optional[str] = None

    @model_validator(mode="after")
    def validate_outbound_target(self) -> "XrelayOutbound":
        """校验不同 outbound 类型所需目标字段。"""
        if self.type == "clash":
            validate_ref(self.ref, 3, "clash outbound ref is required")
        if self.type in {"socks5", "http"} and (not self.server or not self.port):
            raise ValueError("server and port are required for socks5/http outbound")
        return self


class XrelayConfig(ProxystackModel):
    """单个 stack 的 xrelay 配置。"""

    enabled: bool = True
    outbound: XrelayOutbound
    inbounds: list[Inbound] = Field(min_length=1)
    api: Optional[XrelayApiConfig] = None
    stats: Optional[XrelayStatsConfig] = None
    policy: Optional[XrelayPolicyConfig] = None

    @model_validator(mode="after")
    def validate_unique_inbounds(self) -> "XrelayConfig":
        """校验同一 xrelay 内 inbound 名称唯一。"""
        ensure_unique([inbound.name for inbound in self.inbounds], "duplicate inbound name")
        return self


def resolve_xrelay_api_config(defaults: DefaultXrelayConfig, xrelay: XrelayConfig) -> XrelayApiConfig:
    """合并全局 defaults.xrelay.api 和单个 stack 的 xrelay.api 覆盖。"""
    if xrelay.api is None:
        return defaults.api
    return merge_xrelay_api_config(defaults.api, xrelay.api)


def resolve_xrelay_stats_config(defaults: DefaultXrelayConfig, xrelay: XrelayConfig) -> XrelayStatsConfig:
    """合并全局 defaults.xrelay.stats 和单个 stack 的 xrelay.stats 覆盖。"""
    if xrelay.stats is None:
        return defaults.stats
    return merge_xrelay_stats_config(defaults.stats, xrelay.stats)


def resolve_xrelay_policy_config(defaults: DefaultXrelayConfig, xrelay: XrelayConfig) -> XrelayPolicyConfig:
    """合并全局 defaults.xrelay.policy 和单个 stack 的 xrelay.policy 覆盖。"""
    if xrelay.policy is None:
        return defaults.policy
    return merge_xrelay_policy_config(defaults.policy, xrelay.policy)


def merge_xrelay_api_config(default_config: XrelayApiConfig, override_config: XrelayApiConfig) -> XrelayApiConfig:
    """按显式配置字段合并 Xray API 配置。"""
    values = default_config.model_dump()
    for field_name in override_config.model_fields_set:
        values[field_name] = getattr(override_config, field_name)
    return XrelayApiConfig.model_validate(values)


def merge_xrelay_stats_config(
    default_config: XrelayStatsConfig,
    override_config: XrelayStatsConfig,
) -> XrelayStatsConfig:
    """按显式配置字段合并 Xray stats 配置。"""
    values = default_config.model_dump()
    for field_name in override_config.model_fields_set:
        values[field_name] = getattr(override_config, field_name)
    return XrelayStatsConfig.model_validate(values)


def merge_xrelay_policy_config(
    default_config: XrelayPolicyConfig,
    override_config: XrelayPolicyConfig,
) -> XrelayPolicyConfig:
    """按显式配置字段合并 Xray policy 配置。"""
    values = default_config.model_dump()
    for field_name in override_config.model_fields_set:
        if field_name == "system":
            values[field_name] = merge_xrelay_policy_system_config(
                default_config.system,
                override_config.system,
            )
        elif field_name == "levels":
            values[field_name] = merge_xrelay_policy_levels(default_config.levels, override_config.levels)
        else:
            values[field_name] = getattr(override_config, field_name)
    return XrelayPolicyConfig.model_validate(values)


def merge_xrelay_policy_levels(
    default_levels: dict[str, XrelayPolicyLevelConfig],
    override_levels: dict[str, XrelayPolicyLevelConfig],
) -> dict[str, XrelayPolicyLevelConfig]:
    """按 level 编号合并 Xray policy levels 配置。"""
    merged_levels = {level: config.model_copy(deep=True) for level, config in default_levels.items()}
    for level, override_config in override_levels.items():
        default_config = merged_levels.get(level, XrelayPolicyLevelConfig())
        merged_levels[level] = merge_xrelay_policy_level_config(default_config, override_config)
    return merged_levels


def merge_xrelay_policy_level_config(
    default_config: XrelayPolicyLevelConfig,
    override_config: XrelayPolicyLevelConfig,
) -> XrelayPolicyLevelConfig:
    """按显式配置字段合并单个 Xray policy level。"""
    values = default_config.model_dump()
    for field_name in override_config.model_fields_set:
        values[field_name] = getattr(override_config, field_name)
    return XrelayPolicyLevelConfig.model_validate(values)


def merge_xrelay_policy_system_config(
    default_config: XrelayPolicySystemConfig,
    override_config: XrelayPolicySystemConfig,
) -> XrelayPolicySystemConfig:
    """按显式配置字段合并 Xray system policy 配置。"""
    values = default_config.model_dump()
    for field_name in override_config.model_fields_set:
        values[field_name] = getattr(override_config, field_name)
    return XrelayPolicySystemConfig.model_validate(values)


class ClashController(ProxystackModel):
    """mihomo REST controller 配置。"""

    listen: str
    secret: str

    @field_validator("listen")
    @classmethod
    def validate_listen(cls, value: str) -> str:
        """校验 controller 监听地址包含合法端口。"""
        parse_listen(value)
        return value

    @field_validator("secret")
    @classmethod
    def validate_secret(cls, value: str) -> str:
        """校验 controller secret 不为空。"""
        if not value:
            raise ValueError("controller secret is required")
        return value


class SocksListener(ProxystackModel):
    """mihomo socks listener 配置。"""

    name: Name
    listen: str = "127.0.0.1"
    port: Port

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """校验 listener 名称适合作为 ref 片段。"""
        validate_identifier(value, "listener name")
        return value


class ClashListeners(ProxystackModel):
    """mihomo listener 集合，P0 只支持一个 socks listener。"""

    socks: list[SocksListener] = Field(default_factory=list)
    mixed: Optional[Any] = None

    @model_validator(mode="after")
    def validate_p0_listeners(self) -> "ClashListeners":
        """校验 P0 listener 限制，mixed 字段暂不支持。"""
        if "mixed" in self.model_fields_set:
            raise ValueError("listeners.mixed is not supported in P0")
        if len(self.socks) > 1:
            raise ValueError("only one socks listener is supported in P0")
        ensure_unique([listener.name for listener in self.socks], "duplicate socks listener name")
        return self


class ClashUpstream(ProxystackModel):
    """mihomo upstream/proxy 配置。"""

    name: Name
    type: Literal["raw", "xrelay-socks5"]
    ref: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """校验 upstream 名称可被 proxy group 引用。"""
        validate_identifier(value, "upstream name")
        return value

    @model_validator(mode="after")
    def validate_upstream(self) -> "ClashUpstream":
        """校验 upstream 类型对应的必填字段。"""
        if self.type == "xrelay-socks5":
            validate_ref(self.ref, 2, "xrelay-socks5 ref is required")
        if self.type == "raw":
            validate_raw_proxy_config(self.config)
        return self


class ClashGroup(ProxystackModel):
    """mihomo proxy group 配置。"""

    name: Name
    type: Literal["select", "url-test", "load-balance", "fallback"]
    proxies: list[str] = Field(min_length=1)
    url: Optional[str] = None
    interval: Optional[int] = None
    strategy: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """校验 proxy group 名称可被规则引用。"""
        validate_identifier(value, "group name")
        return value

    @model_validator(mode="after")
    def validate_group_fields(self) -> "ClashGroup":
        """校验测试类分组必须配置健康检查参数。"""
        if self.type in {"url-test", "load-balance"}:
            if not self.url or self.interval is None:
                raise ValueError("url and interval are required for url-test/load-balance group")
        if self.type == "load-balance" and not self.strategy:
            self.strategy = "consistent-hashing"
        return self


class ClashRules(ProxystackModel):
    """mihomo 规则配置。"""

    profile: Literal["default"] = "default"
    final: str = "AllProxy"
    extra: list[str] = Field(default_factory=list)


class ClashConfig(ProxystackModel):
    """单个 stack 的 mihomo/clash 配置。"""

    enabled: bool = True
    mode: Literal["Rule", "Global", "Direct"] = "Rule"
    controller: ClashController
    listeners: ClashListeners
    upstreams: list[ClashUpstream] = Field(default_factory=list)
    groups: list[ClashGroup] = Field(default_factory=list)
    rules: ClashRules = Field(default_factory=ClashRules)

    @model_validator(mode="after")
    def validate_clash_references(self) -> "ClashConfig":
        """校验当前 clash 内部的名称引用关系。"""
        upstream_names = [upstream.name for upstream in self.upstreams]
        group_names = [group.name for group in self.groups]
        ensure_unique(upstream_names, "duplicate upstream name")
        ensure_unique(group_names, "duplicate group name")
        known_targets = set(upstream_names) | set(group_names) | BUILTIN_RULE_TARGETS
        for group in self.groups:
            for target in group.proxies:
                if target not in known_targets:
                    raise ValueError(f"group proxy target does not exist: {target}")
        validate_rule_target(self.rules.final, known_targets, "rules.final target does not exist")
        for rule in self.rules.extra:
            target = extract_rule_target(rule)
            validate_rule_target(target, known_targets, "rules.extra target does not exist")
        return self


class Stack(ProxystackModel):
    """单个 stack 文件模型。"""

    name: Name
    enabled: bool = True
    role: Literal["edge", "auto"] = "edge"
    labels: list[str] = Field(default_factory=list)
    xrelay: XrelayConfig
    clash: ClashConfig
    source_path: Optional[Path] = Field(default=None, exclude=True)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """校验 stack 名称适合用于文件名和 systemd 实例名。"""
        validate_identifier(value, "stack name")
        return value

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, value: list[str]) -> list[str]:
        """校验 labels 中的每个值都可安全展示和筛选。"""
        for label in value:
            validate_identifier(label, "label")
        return value


class StackSet(ProxystackModel):
    """全局配置和所有 stack 文件合并后的编译输入。"""

    config: GlobalConfig
    stacks: list[Stack]

    @property
    def stack_names(self) -> list[str]:
        """返回所有 stack 名称，保持加载顺序。"""
        return [stack.name for stack in self.stacks]

    def by_name(self) -> dict[str, Stack]:
        """按 stack 名称返回映射，供后续引用图和生成器使用。"""
        return {stack.name: stack for stack in self.stacks}


def validate_identifier(value: str, label: str) -> None:
    """校验配置标识符只包含安全的文件名/ref 片段字符。"""
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if not value or value[0] in {".", "-"} or any(char not in allowed_chars for char in value):
        raise ValueError(f"{label} contains invalid characters")


def validate_uuid(value: Optional[str], message: str) -> None:
    """校验 UUID 字符串格式。"""
    if not value:
        raise ValueError(message)
    try:
        UUID(value)
    except ValueError as exc:
        raise ValueError("uuid must be a valid UUID") from exc


def validate_ref(value: Optional[str], segment_count: int, message: str) -> None:
    """校验 ref 存在且段数符合基础格式要求。"""
    if not value:
        raise ValueError(message)
    if len(value.split(".")) != segment_count:
        raise ValueError(f"ref must contain {segment_count} dot-separated segments")


def ensure_unique(values: list[str], message: str) -> None:
    """校验字符串列表中没有重复值。"""
    seen_values: set[str] = set()
    for value in values:
        if value in seen_values:
            raise ValueError(f"{message}: {value}")
        seen_values.add(value)


def parse_listen(value: str) -> tuple[str, int]:
    """解析 `host:port` 形式的监听地址。"""
    if ":" not in value:
        raise ValueError("listen must use host:port format")
    host, raw_port = value.rsplit(":", 1)
    if not host:
        raise ValueError("listen host is required")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("listen port must be an integer") from exc
    if port < 1 or port > 65535:
        raise ValueError("listen port must be between 1 and 65535")
    return host, port


def is_loopback_listen_host(host: str) -> bool:
    """判断监听 host 是否为本机回环地址。"""
    return host in {"127.0.0.1", "::1", "localhost"}


def validate_raw_proxy_config(config: dict[str, Any]) -> None:
    """校验 raw upstream 中常见 mihomo 节点的必填字段。"""
    proxy_type = config.get("type")
    if not proxy_type:
        raise ValueError("raw upstream config.type is required")
    if not config.get("server"):
        raise ValueError("raw upstream config.server is required")
    port = config.get("port")
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError("raw upstream config.port must be between 1 and 65535")
    if proxy_type == "vmess":
        validate_uuid(config.get("uuid"), "raw vmess upstream uuid is required")
        if not config.get("network"):
            raise ValueError("raw vmess upstream network is required")
    if proxy_type == "shadowsocks":
        if not config.get("cipher"):
            raise ValueError("raw shadowsocks upstream cipher is required")
        if not config.get("password"):
            raise ValueError("raw shadowsocks upstream password is required")


def extract_rule_target(rule: str) -> str:
    """从 mihomo 规则文本中提取目标策略或组名。"""
    parts = [part.strip() for part in rule.split(",") if part.strip()]
    if len(parts) < 3:
        raise ValueError(f"rules.extra entry is invalid: {rule}")
    if parts[-1] == "no-resolve" and len(parts) >= 4:
        return parts[-2]
    return parts[-1]


def validate_rule_target(target: str, known_targets: set[str], message: str) -> None:
    """校验规则目标指向已存在的节点、组或内置策略。"""
    if target not in known_targets:
        raise ValueError(f"{message}: {target}")
