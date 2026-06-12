"""订阅 input、索引、渲染和发布包生成。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from typing import Literal
from typing import Optional
from zipfile import ZIP_DEFLATED
from zipfile import BadZipFile
from zipfile import ZipFile
from zipfile import ZipInfo
import hashlib
import json
import os

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic import field_validator
from pydantic import model_validator
from jinja2 import Environment
from jinja2 import StrictUndefined
from jinja2 import TemplateError
from ruamel.yaml import YAML

from proxystack.domain.models import Inbound
from proxystack.domain.models import InboundUser
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.domain.models import SubscriptionConfig
from proxystack.domain.models import is_shadowsocks_2022_method

SUPPORTED_INPUT_EXTENSIONS = {".yaml", ".yml", ".json"}
BUNDLE_SCHEMA = "proxystack.sub-bundle"
BUNDLE_VERSION = 1
INDEX_VERSION = 1
INPUT_SCHEMA = "proxystack.subscription-input"
INPUT_VERSION = 1
DEFAULT_ACCESS = {"type": "none"}
SUB_TEMPLATE_DIR_NAME = "sub"
CLASH_TEMPLATE_NAME = "clash.yaml.j2"
PREMIUM_CLASH_TEMPLATE_NAME = "premium-clash.yaml.j2"
SURGE_TEMPLATE_NAME = "surge.conf.j2"
CLASH_TEST_URL = "http://www.gstatic.com/generate_204"
DEFAULT_CLASH_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "DOMAIN,localhost,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve",
    "GEOIP,CN,DIRECT",
    "MATCH,Final",
]
SURGE_SKIP_PROXY = (
    "127.0.0.1, 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, "
    "100.64.0.0/10, localhost, *.local"
)
DEFAULT_SURGE_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "DOMAIN,localhost,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve",
    "GEOIP,CN,DIRECT",
    "FINAL,FinalGroup",
]


class SubscriptionGeneratorError(ValueError):
    """订阅生成、合并或渲染失败异常。"""


class SubscriptionTemplateError(SubscriptionGeneratorError):
    """订阅模板读取或渲染失败异常。"""


@dataclass(frozen=True)
class SubscriptionInputSummary:
    """描述一个订阅 input 的非敏感摘要，供 CLI 和日志输出。"""

    name: str
    source: str
    nodes: int
    users: int
    remarks: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubscriptionBundleSummary:
    """描述订阅发布包内容的非敏感摘要。"""

    source: str
    inputs: tuple[SubscriptionInputSummary, ...]
    users: int

    @property
    def input_count(self) -> int:
        """返回发布包包含的 input 文件数量。"""
        return len(self.inputs)

    @property
    def node_count(self) -> int:
        """返回发布包包含的订阅节点总数。"""
        return sum(input_summary.nodes for input_summary in self.inputs)

    @property
    def user_count(self) -> int:
        """返回发布包包含的去重用户数量。"""
        return self.users


@dataclass(frozen=True)
class BundleImportResult:
    """描述发布包导入结果，避免 CLI 重新扫描 zip 或泄露凭据。"""

    manifest: "BundleManifest"
    summary: SubscriptionBundleSummary
    written_inputs: tuple[str, ...]
    replaced_inputs: tuple[str, ...]
    removed_inputs: tuple[str, ...]
    replace_all: bool


class SubscriptionAuth(BaseModel):
    """订阅节点中的 socks/http 鉴权参数。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["noauth", "password"]
    username: Optional[str] = None
    password: Optional[str] = None

    @model_validator(mode="after")
    def validate_password_auth(self) -> "SubscriptionAuth":
        """校验 password 鉴权必须同时包含用户名和密码。"""
        if self.type == "password" and (not self.username or not self.password):
            raise ValueError("username and password are required for password auth")
        return self


class SubscriptionNode(BaseModel):
    """单个可发布订阅节点，禁止携带 clash upstream/rules 等额外字段。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1)
    user: str = Field(min_length=1)
    protocol: Literal["vmess", "shadowsocks", "socks5", "http"]
    server: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    tag: str = Field(min_length=1)
    remark: str = Field(min_length=1)
    uuid: Optional[str] = None
    network: Optional[str] = None
    method: Optional[str] = None
    cipher: Optional[str] = None
    password: Optional[str] = None
    udp: Optional[bool] = None
    auth: Optional[SubscriptionAuth] = None

    @model_validator(mode="after")
    def validate_protocol_fields(self) -> "SubscriptionNode":
        """校验不同协议的客户端连接参数齐备。"""
        if self.protocol == "vmess":
            if not self.uuid:
                raise ValueError("uuid is required for vmess node")
            if not self.network:
                raise ValueError("network is required for vmess node")
        if self.protocol == "shadowsocks":
            if not self.password:
                raise ValueError("password is required for shadowsocks node")
            if not (self.method or self.cipher):
                raise ValueError("method or cipher is required for shadowsocks node")
        if self.protocol in {"socks5", "http"} and self.auth is not None and self.auth.type == "password":
            if not self.auth.username or not self.auth.password:
                raise ValueError("username and password are required for password auth")
        return self


class SubscriptionInput(BaseModel):
    """agent 和 sub 共享的订阅输入文件格式。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    input_schema: Literal["proxystack.subscription-input"] = INPUT_SCHEMA
    input_version: Literal[1]
    source: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    nodes: list[SubscriptionNode] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def validate_schema_metadata(cls, value: Any) -> Any:
        """校验 input schema 和版本，兼容缺少 schema 的 v1 输入。"""
        if not isinstance(value, dict):
            return value
        input_schema = value.get("input_schema", INPUT_SCHEMA)
        if input_schema != INPUT_SCHEMA:
            raise ValueError(f"unsupported subscription input schema: {input_schema}")
        input_version = value.get("input_version")
        if input_version is not None and (type(input_version) is not int or input_version != INPUT_VERSION):
            raise ValueError(f"unsupported subscription input version: {input_version}")
        return value

    @field_validator("nodes")
    @classmethod
    def validate_unique_node_ids(cls, nodes: list[SubscriptionNode]) -> list[SubscriptionNode]:
        """校验单个 input 内部的 node.id 不重复。"""
        seen_node_ids: set[str] = set()
        for node in nodes:
            if node.id in seen_node_ids:
                raise ValueError(f"duplicate node id in input: {node.id}")
            seen_node_ids.add(node.id)
        return nodes


class SubscriptionAccess(BaseModel):
    """订阅服务访问控制信息，会写入 index 供 HTTP 服务读取。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["none", "token"] = "none"
    token: Optional[str] = None

    @model_validator(mode="after")
    def validate_token_access(self) -> "SubscriptionAccess":
        """校验 token 模式必须包含 token 明文。"""
        if self.type == "token" and not self.token:
            raise ValueError("token is required when access type is token")
        return self


class SubscriptionIndex(BaseModel):
    """合并后的订阅索引，供 CLI render 和订阅 HTTP 服务读取。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    index_version: Literal[1]
    generated_at: str = Field(min_length=1)
    sources: list[str] = Field(default_factory=list)
    nodes: list[SubscriptionNode] = Field(default_factory=list)
    users: dict[str, list[SubscriptionNode]] = Field(default_factory=dict)
    access: SubscriptionAccess = Field(default_factory=SubscriptionAccess)


class BundleManifest(BaseModel):
    """订阅发布包 manifest 结构，用于 import 时校验版本和 hash。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    bundle_schema: Literal["proxystack.sub-bundle"] = BUNDLE_SCHEMA
    bundle_version: Literal[1]
    source: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    inputs_sha256: dict[str, str]
    template_version: str = "builtin-v1"
    access: SubscriptionAccess = Field(default_factory=SubscriptionAccess)

    @model_validator(mode="before")
    @classmethod
    def validate_schema_metadata(cls, value: Any) -> Any:
        """校验 bundle schema 和版本，避免和后续原生备份包混用。"""
        if not isinstance(value, dict):
            return value
        bundle_schema = value.get("bundle_schema", BUNDLE_SCHEMA)
        if bundle_schema != BUNDLE_SCHEMA:
            raise ValueError(f"unsupported subscription bundle schema: {bundle_schema}")
        bundle_version = value.get("bundle_version")
        if bundle_version is not None and (type(bundle_version) is not int or bundle_version != BUNDLE_VERSION):
            raise ValueError(f"unsupported subscription bundle version: {bundle_version}")
        return value

    @field_validator("inputs_sha256")
    @classmethod
    def validate_inputs_sha256(cls, inputs_sha256: dict[str, str]) -> dict[str, str]:
        """校验 manifest 中的 input hash 是标准 sha256 十六进制值。"""
        for name, digest in inputs_sha256.items():
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError(f"invalid input sha256 for {name}")
        return inputs_sha256


def now_iso() -> str:
    """返回带本地时区的秒级 ISO 时间戳。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def render_stack_input(stack_set: StackSet, source: str) -> SubscriptionInput:
    """从启用 stack 的启用 xrelay inbound 生成订阅 input。"""
    nodes: list[SubscriptionNode] = []
    for stack in stack_set.stacks:
        if not stack.enabled or not stack.xrelay.enabled:
            continue
        for inbound in stack.xrelay.inbounds:
            if not inbound.sub:
                continue
            nodes.extend(render_inbound_nodes(stack_set, stack, inbound))
    return SubscriptionInput(
        input_version=INPUT_VERSION,
        source=source,
        generated_at=now_iso(),
        nodes=nodes,
    )


def render_inbound_nodes(stack_set: StackSet, stack: Stack, inbound: Inbound) -> list[SubscriptionNode]:
    """把一个 xrelay inbound 映射为一个或多个订阅节点。"""
    if inbound.protocol == "vmess":
        return [render_vmess_user_node(stack_set, stack, inbound, vmess_user) for vmess_user in inbound.users]
    if inbound.protocol == "shadowsocks" and inbound.users:
        return [
            render_shadowsocks_user_node(stack_set, stack, inbound, shadowsocks_user)
            for shadowsocks_user in inbound.users
        ]
    return [render_inbound_node(stack_set, stack, inbound)]


def render_inbound_node(stack_set: StackSet, stack: Stack, inbound: Inbound) -> SubscriptionNode:
    """把单个 xrelay inbound 映射为订阅节点。"""
    user = inbound.user or "default"
    node_data: dict[str, Any] = {
        "id": f"{stack.name}:{inbound.name}",
        "user": user,
        "protocol": inbound.protocol,
        "server": inbound.server or stack_set.config.external_host,
        "port": inbound.port,
        "tag": inbound_tag(inbound),
        "remark": render_subscription_remark(
            stack_set.config.subscription,
            stack.name,
            inbound,
            user,
            inbound.remark,
            inbound.remark or inbound.tag or f"{stack.name}-{inbound.name}",
        ),
    }
    if inbound.udp:
        node_data["udp"] = inbound.udp
    if inbound.protocol == "shadowsocks":
        node_data["method"] = inbound.method or inbound.cipher
        node_data["cipher"] = inbound.cipher or inbound.method
        node_data["password"] = inbound.password
    if inbound.protocol in {"socks5", "http"} and inbound.auth is not None:
        node_data["auth"] = {
            "type": inbound.auth.type,
            "username": inbound.auth.username,
            "password": inbound.auth.password,
        }
    return SubscriptionNode.model_validate(node_data)


def render_vmess_user_node(
    stack_set: StackSet,
    stack: Stack,
    inbound: Inbound,
    vmess_user: InboundUser,
) -> SubscriptionNode:
    """把 vmess users 中的单个用户映射为独立订阅节点。"""
    node_data: dict[str, Any] = {
        "id": f"{stack.name}:{inbound.name}:{vmess_user.user}",
        "user": vmess_user.user,
        "protocol": inbound.protocol,
        "server": inbound.server or stack_set.config.external_host,
        "port": inbound.port,
        "tag": vmess_user.tag or f"{inbound_tag(inbound)}:{vmess_user.user}",
        "remark": render_subscription_remark(
            stack_set.config.subscription,
            stack.name,
            inbound,
            vmess_user.user,
            vmess_user.remark,
            vmess_user.remark or vmess_user.tag or f"{stack.name}-{inbound.name}-{vmess_user.user}",
        ),
        "uuid": vmess_user.uuid,
        "network": inbound.network,
    }
    if inbound.udp:
        node_data["udp"] = inbound.udp
    return SubscriptionNode.model_validate(node_data)


def render_shadowsocks_user_node(
    stack_set: StackSet,
    stack: Stack,
    inbound: Inbound,
    shadowsocks_user: InboundUser,
) -> SubscriptionNode:
    """把 shadowsocks users 中的单个用户映射为独立订阅节点。"""
    method = shadowsocks_user.method or shadowsocks_user.cipher or inbound.method or inbound.cipher
    node_data: dict[str, Any] = {
        "id": f"{stack.name}:{inbound.name}:{shadowsocks_user.user}",
        "user": shadowsocks_user.user,
        "protocol": inbound.protocol,
        "server": inbound.server or stack_set.config.external_host,
        "port": inbound.port,
        "tag": shadowsocks_user.tag or f"{inbound_tag(inbound)}:{shadowsocks_user.user}",
        "remark": render_subscription_remark(
            stack_set.config.subscription,
            stack.name,
            inbound,
            shadowsocks_user.user,
            shadowsocks_user.remark,
            shadowsocks_user.remark or shadowsocks_user.tag or f"{stack.name}-{inbound.name}-{shadowsocks_user.user}",
        ),
        "method": method,
        "cipher": method,
        "password": shadowsocks_node_password(inbound, shadowsocks_user),
    }
    if inbound.udp:
        node_data["udp"] = inbound.udp
    return SubscriptionNode.model_validate(node_data)


def shadowsocks_node_password(inbound: Inbound, shadowsocks_user: InboundUser) -> str:
    """返回订阅侧 shadowsocks 密码；SS2022 需要组合服务端密码和用户密码。"""
    inbound_method = inbound.method or inbound.cipher or ""
    if is_shadowsocks_2022_method(inbound_method):
        return f"{inbound.password}:{shadowsocks_user.password}"
    return shadowsocks_user.password or ""


def render_subscription_remark(
    config: SubscriptionConfig,
    source: str,
    inbound: Inbound,
    user: str,
    configured_remark: Optional[str],
    preserve_remark: str,
) -> str:
    """按订阅 remark 策略生成客户端最终看到的节点名。"""
    fallback_remark = f"{inbound.protocol}:{inbound.port}:{user}"
    remark = configured_remark or fallback_remark
    if config.remark_policy == "preserve":
        return preserve_remark
    values = {
        "source": source,
        "inbound": inbound.name,
        "protocol": inbound.protocol,
        "port": inbound.port,
        "user": user,
        "remark": remark,
    }
    if config.remark_policy == "template":
        return (config.remark_template or "").format(**values)
    return "{source}-{remark}".format(**values)


def inbound_tag(inbound: Inbound) -> str:
    """返回显式 tag 或按 xray inbound 默认规则生成 tag。"""
    if inbound.tag:
        return inbound.tag
    return f"{inbound.protocol}:{inbound.port}:{inbound.name}"


def access_from_stack_set(stack_set: StackSet) -> SubscriptionAccess:
    """从全局配置提取订阅访问控制信息。"""
    access = stack_set.config.subscription.access
    return SubscriptionAccess.model_validate(access.model_dump())


def input_to_yaml(subscription_input: SubscriptionInput) -> str:
    """把订阅 input 编码为稳定 YAML 文本。"""
    return dump_yaml(subscription_input.model_dump(mode="json", exclude_none=True))


def index_to_json(index: SubscriptionIndex) -> str:
    """把订阅 index 编码为稳定 JSON 文本。"""
    return json.dumps(index.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2) + "\n"


def load_input_file(path: Path) -> SubscriptionInput:
    """读取并校验单个 YAML 或 JSON 订阅 input 文件。"""
    if path.suffix not in SUPPORTED_INPUT_EXTENSIONS:
        raise SubscriptionGeneratorError(f"unsupported input extension: {path.name}")
    try:
        if path.suffix == ".json":
            loaded = json.loads(path.read_text(encoding="utf-8"))
        else:
            loaded = load_yaml_mapping(path)
        return SubscriptionInput.model_validate(loaded)
    except (OSError, ValueError, ValidationError) as exc:
        raise SubscriptionGeneratorError(f"invalid subscription input {path}: {exc}") from exc


def load_input_content(name: str, content: bytes) -> SubscriptionInput:
    """从发布包成员内容读取并校验订阅 input。"""
    validate_bundle_input_name(name)
    try:
        text = content.decode("utf-8")
        if Path(name).suffix == ".json":
            loaded = json.loads(text)
        else:
            loaded = load_yaml_mapping_text(text, name)
        return SubscriptionInput.model_validate(loaded)
    except (UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise SubscriptionGeneratorError(f"invalid bundled subscription input {name}: {exc}") from exc


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """读取 YAML 文件并要求顶层是 mapping。"""
    yaml = YAML(typ="safe")
    with path.open("r", encoding="utf-8") as input_file:
        loaded = yaml.load(input_file)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"subscription input must be a mapping: {path}")
    return loaded


def load_yaml_mapping_text(text: str, label: str) -> dict[str, Any]:
    """读取 YAML 文本并要求顶层是 mapping。"""
    yaml = YAML(typ="safe")
    loaded = yaml.load(text)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"subscription input must be a mapping: {label}")
    return loaded


def scan_input_files(input_dir: Path) -> list[Path]:
    """扫描 inputs 目录中的订阅 input 文件，并按文件名稳定排序。"""
    if not input_dir.exists():
        raise SubscriptionGeneratorError(f"input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise SubscriptionGeneratorError(f"input path is not a directory: {input_dir}")
    return sorted(
        [path for path in input_dir.iterdir() if path.is_file() and path.suffix in SUPPORTED_INPUT_EXTENSIONS],
        key=lambda path: path.name,
    )


def load_inputs(input_dir: Path) -> list[tuple[Path, SubscriptionInput]]:
    """读取 inputs 目录中的所有 input 文件。"""
    return [(path, load_input_file(path)) for path in scan_input_files(input_dir)]


def summarize_subscription_inputs(
    source: str,
    inputs: list[tuple[Path, SubscriptionInput]],
) -> SubscriptionBundleSummary:
    """生成多个订阅 input 的非敏感摘要，供导入、导出和日志复用。"""
    input_summaries = tuple(input_summary(input_path.name, subscription_input) for input_path, subscription_input in inputs)
    users = {node.user for _input_path, subscription_input in inputs for node in subscription_input.nodes}
    return SubscriptionBundleSummary(source=source, inputs=input_summaries, users=len(users))


def summarize_input_files(source: str, input_files: list[tuple[str, bytes]]) -> SubscriptionBundleSummary:
    """从发布包候选 input 内容生成非敏感摘要。"""
    loaded_inputs = [(Path(name), load_input_content(name, content)) for name, content in input_files]
    return summarize_subscription_inputs(source, loaded_inputs)


def input_summary(name: str, subscription_input: SubscriptionInput) -> SubscriptionInputSummary:
    """生成单个订阅 input 的非敏感摘要。"""
    return SubscriptionInputSummary(
        name=name,
        source=subscription_input.source,
        nodes=len(subscription_input.nodes),
        users=len({node.user for node in subscription_input.nodes}),
        remarks=tuple(node.remark for node in subscription_input.nodes),
    )


def merge_input_files(input_dir: Path, access: Optional[SubscriptionAccess] = None) -> SubscriptionIndex:
    """扫描并合并 inputs 目录，供 agent 和 sub 共享。"""
    return merge_inputs(load_inputs(input_dir), access=access)


def merge_inputs(
    inputs: list[tuple[Path, SubscriptionInput]],
    access: Optional[SubscriptionAccess] = None,
) -> SubscriptionIndex:
    """按给定顺序合并多个 input，并在重复 node.id 或订阅代理名时失败。"""
    nodes: list[SubscriptionNode] = []
    sources: list[str] = []
    node_sources: dict[str, str] = {}
    proxy_name_sources: dict[tuple[str, str], tuple[str, str]] = {}
    for input_path, subscription_input in inputs:
        sources.append(subscription_input.source)
        for node in subscription_input.nodes:
            if node.id in node_sources:
                raise SubscriptionGeneratorError(
                    f"duplicate node id: {node.id}, first seen in {node_sources[node.id]}, repeated in {input_path.name}"
                )
            node_sources[node.id] = input_path.name
            proxy_name_key = (node.user, node.remark)
            if proxy_name_key in proxy_name_sources:
                first_input_name, first_node_id = proxy_name_sources[proxy_name_key]
                raise SubscriptionGeneratorError(
                    "duplicate proxy name for user: "
                    f"user={node.user} name={node.remark}, "
                    f"first seen in {first_input_name} node={first_node_id}, "
                    f"repeated in {input_path.name} node={node.id}"
                )
            proxy_name_sources[proxy_name_key] = (input_path.name, node.id)
            nodes.append(node)
    return build_index(nodes, sources, access=access)


def build_index(
    nodes: list[SubscriptionNode],
    sources: list[str],
    access: Optional[SubscriptionAccess] = None,
) -> SubscriptionIndex:
    """根据节点列表生成按 user 分组的订阅索引。"""
    users: dict[str, list[SubscriptionNode]] = {}
    for node in nodes:
        users.setdefault(node.user, []).append(node)
    return SubscriptionIndex(
        index_version=INDEX_VERSION,
        generated_at=now_iso(),
        sources=sources,
        nodes=nodes,
        users={user: users[user] for user in sorted(users)},
        access=access or SubscriptionAccess(),
    )


def render_stack_index(stack_set: StackSet, source: str) -> SubscriptionIndex:
    """从当前 stack 直接生成订阅索引。"""
    subscription_input = render_stack_input(stack_set, source)
    return merge_inputs([(Path(f"{source}.yaml"), subscription_input)], access=access_from_stack_set(stack_set))


def render_clash_subscription(
    index: SubscriptionIndex,
    user: str,
    template_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> str:
    """渲染普通 Clash 订阅 YAML。"""
    return render_subscription_template(
        CLASH_TEMPLATE_NAME,
        build_subscription_template_context(index, user),
        template_dir=template_dir,
        data_dir=data_dir,
    )


def render_premium_clash_subscription(
    index: SubscriptionIndex,
    user: str,
    template_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> str:
    """渲染 Premium Clash 订阅 YAML；当前与普通 Clash 使用同一结构。"""
    return render_subscription_template(
        PREMIUM_CLASH_TEMPLATE_NAME,
        build_subscription_template_context(index, user),
        template_dir=template_dir,
        data_dir=data_dir,
    )


def build_subscription_template_context(index: SubscriptionIndex, user: str) -> dict[str, Any]:
    """生成三类订阅模板共享的上下文。"""
    nodes = nodes_for_user(index, user)
    proxies = [render_clash_proxy(node) for node in nodes]
    proxy_names = [proxy["name"] for proxy in proxies]
    return {
        "user": user,
        "generated_at": index.generated_at,
        "sources": [*index.sources],
        "nodes": nodes,
        "proxies": proxies,
        "proxy_names": proxy_names,
        "proxy_groups": render_clash_proxy_groups(proxy_names),
        "clash_rules": [*DEFAULT_CLASH_RULES],
        "surge_proxy_lines": [render_surge_proxy(node) for node in nodes],
        "surge_rules": [*DEFAULT_SURGE_RULES],
        "test_url": CLASH_TEST_URL,
        "surge_skip_proxy": SURGE_SKIP_PROXY,
    }


def render_subscription_template(
    template_name: str,
    context: dict[str, Any],
    template_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> str:
    """读取本地覆盖或包内默认模板，并用订阅上下文渲染。"""
    source = load_subscription_template(template_name, template_dir=template_dir, data_dir=data_dir)
    environment = build_subscription_template_environment()
    try:
        return environment.from_string(source).render(**context)
    except TemplateError as exc:
        raise SubscriptionTemplateError(f"subscription template render failed: {template_name}") from exc


def build_subscription_template_environment() -> Environment:
    """创建订阅模板渲染环境并注册 YAML 片段过滤器。"""
    environment = Environment(autoescape=False, keep_trailing_newline=True, undefined=StrictUndefined)
    environment.filters["yaml_block"] = yaml_block
    return environment


def load_subscription_template(
    template_name: str,
    template_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> str:
    """按本地覆盖目录、data_dir 默认目录、包内默认模板顺序读取模板。"""
    validate_subscription_template_name(template_name)
    for template_path in subscription_template_paths(template_name, template_dir=template_dir, data_dir=data_dir):
        try:
            if template_path.is_file():
                return template_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SubscriptionTemplateError(f"subscription template could not be read: {template_path}") from exc
    try:
        return files("proxystack").joinpath("templates", SUB_TEMPLATE_DIR_NAME, template_name).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SubscriptionTemplateError(f"subscription template is missing: {template_name}") from exc


def find_subscription_template_source(
    template_name: str,
    template_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> str:
    """返回模板将从哪个位置读取，用于启动日志摘要。"""
    validate_subscription_template_name(template_name)
    for template_path in subscription_template_paths(template_name, template_dir=template_dir, data_dir=data_dir):
        try:
            if template_path.is_file():
                return str(template_path)
        except OSError as exc:
            raise SubscriptionTemplateError(f"subscription template could not be read: {template_path}") from exc
    return f"builtin:{SUB_TEMPLATE_DIR_NAME}/{template_name}"


def validate_subscription_template_name(template_name: str) -> None:
    """校验模板名不包含路径片段，避免模板查找越界。"""
    if Path(template_name).name != template_name:
        raise SubscriptionTemplateError(f"unsafe subscription template name: {template_name}")


def subscription_template_paths(
    template_name: str,
    template_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> list[Path]:
    """返回本地模板候选路径，支持模板根目录和 sub 子目录两种写法。"""
    paths: list[Path] = []
    if template_dir is not None:
        paths.append(template_dir / SUB_TEMPLATE_DIR_NAME / template_name)
        paths.append(template_dir / template_name)
    if data_dir is not None:
        paths.append(data_dir / "templates" / SUB_TEMPLATE_DIR_NAME / template_name)
    return unique_paths(paths)


def unique_paths(paths: list[Path]) -> list[Path]:
    """去重模板候选路径，避免同一路径被重复读取。"""
    seen_paths: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path in seen_paths:
            continue
        seen_paths.add(path)
        unique.append(path)
    return unique


def yaml_block(value: Any, indent: int = 0) -> str:
    """把对象渲染成可嵌入模板的 YAML 块。"""
    text = dump_yaml(value).rstrip("\n")
    if not text or indent <= 0:
        return text
    prefix = " " * indent
    return "\n".join(f"{prefix}{line}" if line else line for line in text.splitlines())


def render_clash_subscription_dict(index: SubscriptionIndex, user: str) -> dict[str, Any]:
    """生成可直接导入 Clash/Mihomo 的完整订阅字典。"""
    nodes = nodes_for_user(index, user)
    proxies = [render_clash_proxy(node) for node in nodes]
    proxy_names = [proxy["name"] for proxy in proxies]
    return {
        "port": 7890,
        "socks-port": 7891,
        "redir-port": 7892,
        "tproxy-port": 7893,
        "allow-lan": True,
        "mode": "Rule",
        "log-level": "info",
        "external-controller": "127.0.0.1:9090",
        "dns": {
            "enable": False,
            "listen": "0.0.0.0:53",
            "enhanced-mode": "fake-ip",
            "nameserver": [
                "tls://dns.rubyfish.cn:853",
                "119.29.29.29",
                "223.5.5.5",
            ],
            "fallback": [
                "tls://1.1.1.1:853",
                "tcp://1.1.1.1:53",
                "tcp://208.67.222.222:443",
                "tls://dns.google",
                "tls://dns.rubyfish.cn:853",
                "114.114.114.114",
                "8.8.8.8",
            ],
        },
        "tun": {
            "enable": False,
        },
        "proxies": proxies,
        "proxy-groups": render_clash_proxy_groups(proxy_names),
        "rules": [*DEFAULT_CLASH_RULES],
    }


def render_clash_proxy_groups(proxy_names: list[str]) -> list[dict[str, Any]]:
    """根据节点名生成默认 Clash/Mihomo 代理组。"""
    return [
        {
            "name": "AllProxy",
            "type": "select",
            "proxies": ["auto", "loadbalance", *proxy_names, "DIRECT"],
        },
        {
            "name": "loadbalance",
            "type": "load-balance",
            "url": CLASH_TEST_URL,
            "interval": 300,
            "strategy": "round-robin",
            "proxies": [*proxy_names],
        },
        {
            "name": "auto",
            "type": "url-test",
            "url": CLASH_TEST_URL,
            "interval": 300,
            "proxies": [*proxy_names],
        },
        {
            "name": "Final",
            "type": "select",
            "proxies": ["AllProxy", "DIRECT", *proxy_names],
        },
    ]


def render_clash_proxy(node: SubscriptionNode) -> dict[str, Any]:
    """把订阅节点转换为 Clash/Mihomo proxy 字段。"""
    proxy: dict[str, Any] = {
        "name": node.remark,
        "type": clash_protocol_type(node.protocol),
        "server": node.server,
        "port": node.port,
    }
    if node.protocol == "vmess":
        proxy["uuid"] = node.uuid
        proxy["alterId"] = 0
        proxy["cipher"] = "auto"
        proxy["network"] = node.network
    if node.protocol == "shadowsocks":
        proxy["cipher"] = node.cipher or node.method
        proxy["password"] = node.password
    if node.protocol in {"socks5", "http"} and node.auth is not None and node.auth.type == "password":
        proxy["username"] = node.auth.username
        proxy["password"] = node.auth.password
    if node.udp is not None and node.protocol in {"shadowsocks", "socks5"}:
        proxy["udp"] = node.udp
    return proxy


def clash_protocol_type(protocol: str) -> str:
    """把订阅协议名转换为 Clash proxy type。"""
    if protocol == "shadowsocks":
        return "ss"
    return protocol


def render_surge_subscription(
    index: SubscriptionIndex,
    user: str,
    template_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> str:
    """渲染 Surge 订阅文本。"""
    return render_subscription_template(
        SURGE_TEMPLATE_NAME,
        build_subscription_template_context(index, user),
        template_dir=template_dir,
        data_dir=data_dir,
    )


def render_surge_group_line(name: str, group_type: str, proxies: list[str], suffix: str = "") -> str:
    """生成 Surge 代理组配置行。"""
    proxy_part = ", ".join(proxies)
    if suffix:
        return f"{name} = {group_type}, {proxy_part}, {suffix}"
    return f"{name} = {group_type}, {proxy_part}"


def render_surge_proxy(node: SubscriptionNode) -> str:
    """把订阅节点转换为 Surge proxy 行。"""
    if node.protocol == "vmess":
        return (
            f"{node.remark} = vmess, {node.server}, {node.port}, "
            f"username={node.uuid}, network={node.network}, vmess-aead=true"
        )
    if node.protocol == "shadowsocks":
        return (
            f"{node.remark} = ss, {node.server}, {node.port}, "
            f"encrypt-method={node.cipher or node.method}, password={node.password}"
        )
    if node.protocol == "socks5":
        auth = render_surge_auth(node)
        udp = ", udp-relay=true" if node.udp else ""
        return f"{node.remark} = socks5, {node.server}, {node.port}{auth}{udp}"
    auth = render_surge_auth(node)
    return f"{node.remark} = http, {node.server}, {node.port}{auth}"


def render_surge_auth(node: SubscriptionNode) -> str:
    """生成 Surge socks/http 可选鉴权片段。"""
    if node.auth is None or node.auth.type != "password":
        return ""
    return f", {node.auth.username}, {node.auth.password}"


def nodes_for_user(index: SubscriptionIndex, user: str) -> list[SubscriptionNode]:
    """从订阅索引中读取指定用户节点，用户不存在或空节点时失败。"""
    nodes = index.users.get(user, [])
    if not nodes:
        raise SubscriptionGeneratorError(f"subscription user has no nodes: {user}")
    return nodes


def dump_yaml(value: Any) -> str:
    """把对象编码为稳定、可读的 YAML 文本。"""
    from io import StringIO

    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    stream = StringIO()
    yaml.dump(value, stream)
    return stream.getvalue()


def sha256_bytes(content: bytes) -> str:
    """计算字节内容的 sha256 十六进制摘要。"""
    return hashlib.sha256(content).hexdigest()


def write_bundle(
    output_path: Path,
    source: str,
    input_files: list[tuple[str, bytes]],
    access: Optional[SubscriptionAccess] = None,
) -> BundleManifest:
    """写入订阅发布包 zip，并返回 manifest；access 不再随发布包生效。"""
    ensure_unique_bundle_input_names(input_files)
    for name, _content in input_files:
        validate_bundle_input_name(name)
    manifest = BundleManifest(
        bundle_version=BUNDLE_VERSION,
        source=source,
        generated_at=now_iso(),
        inputs_sha256={name: sha256_bytes(content) for name, content in input_files},
        access=SubscriptionAccess(),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as zip_file:
        zip_file.writestr("manifest.json", json.dumps(manifest.model_dump(mode="json", exclude_none=True), indent=2))
        for name, content in input_files:
            zip_file.writestr(f"inputs/{name}", content)
    return manifest


def ensure_unique_bundle_input_names(input_files: list[tuple[str, bytes]]) -> None:
    """校验发布包内 input 文件名不重复。"""
    seen_names: set[str] = set()
    for name, _content in input_files:
        if name in seen_names:
            raise SubscriptionGeneratorError(f"duplicate bundle input file: {name}")
        seen_names.add(name)


def validate_bundle_input_name(name: str) -> None:
    """校验发布包内 input 文件名不包含路径片段。"""
    if Path(name).name != name or Path(name).suffix not in SUPPORTED_INPUT_EXTENSIONS:
        raise SubscriptionGeneratorError(f"unsafe bundle input file: {name}")


def stack_input_file(source: str, subscription_input: SubscriptionInput) -> tuple[str, bytes]:
    """把 stack 生成的 input 转换为发布包内文件名和内容。"""
    return f"{source}.yaml", input_to_yaml(subscription_input).encode("utf-8")


def input_dir_files(input_dir: Path) -> list[tuple[str, bytes]]:
    """读取 inputs 目录中的原始 input 文件内容用于发布包。"""
    files: list[tuple[str, bytes]] = []
    for path in scan_input_files(input_dir):
        load_input_file(path)
        files.append((path.name, path.read_bytes()))
    return files


def load_index_file(path: Path) -> SubscriptionIndex:
    """读取并校验订阅索引 JSON 文件。"""
    try:
        return SubscriptionIndex.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise SubscriptionGeneratorError(f"invalid subscription index {path}: {exc}") from exc


def load_manifest_from_zip(zip_file: ZipFile) -> BundleManifest:
    """从发布包 zip 中读取并校验 manifest。"""
    try:
        manifest_data = json.loads(zip_file.read("manifest.json").decode("utf-8"))
    except (KeyError, ValueError) as exc:
        raise SubscriptionGeneratorError("bundle manifest is missing or invalid") from exc
    try:
        return BundleManifest.model_validate(manifest_data)
    except ValidationError as exc:
        raise SubscriptionGeneratorError(f"bundle manifest schema is invalid: {exc}") from exc


def validate_bundle_members(zip_file: ZipFile) -> None:
    """校验 zip 成员路径不会穿越目标目录。"""
    for member in zip_file.infolist():
        validate_zip_member(member)


def validate_zip_member(member: ZipInfo) -> None:
    """校验单个 zip 成员路径安全且属于允许目录。"""
    name = member.filename
    path = Path(name)
    if name.startswith("/") or "\\" in name or ".." in path.parts:
        raise SubscriptionGeneratorError(f"unsafe bundle path: {name}")
    if name == "manifest.json":
        return
    if member.is_dir() and name == "inputs/":
        return
    if name.startswith("inputs/") and len(path.parts) == 2 and path.parts[1]:
        return
    raise SubscriptionGeneratorError(f"unexpected bundle path: {name}")


def extract_bundle_inputs(bundle_path: Path, data_dir: Path, replace_all: bool = False) -> BundleManifest:
    """校验发布包并把 inputs 增量解包到 data_dir/inputs。"""
    return extract_bundle_inputs_with_result(bundle_path, data_dir, replace_all=replace_all).manifest


def extract_bundle_inputs_with_result(
    bundle_path: Path,
    data_dir: Path,
    replace_all: bool = False,
) -> BundleImportResult:
    """校验发布包、写入 inputs，并返回本次导入的非敏感摘要。"""
    try:
        zip_file = ZipFile(bundle_path, "r")
    except BadZipFile as exc:
        raise SubscriptionGeneratorError(f"invalid subscription bundle zip: {bundle_path}") from exc
    with zip_file:
        validate_bundle_members(zip_file)
        manifest = load_manifest_from_zip(zip_file)
        actual_input_names = {
            Path(member.filename).name
            for member in zip_file.infolist()
            if not member.is_dir() and member.filename.startswith("inputs/")
        }
        expected_input_names = set(manifest.inputs_sha256)
        if actual_input_names != expected_input_names:
            raise SubscriptionGeneratorError("bundle inputs do not match manifest")
        try:
            input_members = {name: zip_file.read(f"inputs/{name}") for name in manifest.inputs_sha256}
        except KeyError as exc:
            raise SubscriptionGeneratorError("bundle input is missing") from exc
        for name, content in input_members.items():
            actual_hash = sha256_bytes(content)
            if actual_hash != manifest.inputs_sha256[name]:
                raise SubscriptionGeneratorError(f"input hash mismatch: {name}")
        loaded_inputs = [(Path(name), load_input_content(name, content)) for name, content in input_members.items()]
        import_summary = summarize_subscription_inputs(manifest.source, loaded_inputs)
        input_dir = data_dir / "inputs"
        input_dir.mkdir(parents=True, exist_ok=True)
        existing_input_names = {path.name for path in scan_input_files(input_dir)}
        replaced_inputs = tuple(sorted(name for name in input_members if name in existing_input_names))
        removed_inputs: tuple[str, ...] = ()
        if replace_all:
            merge_inputs(loaded_inputs)
            removed_inputs = tuple(sorted(name for name in existing_input_names if name not in input_members))
            clear_managed_input_files(input_dir)
        else:
            existing_inputs = [
                (path, load_input_file(path))
                for path in scan_input_files(input_dir)
                if path.name not in input_members
            ]
            merge_inputs([*existing_inputs, *loaded_inputs])
        for name, content in input_members.items():
            write_input_atomically(input_dir / name, content)
    return BundleImportResult(
        manifest=manifest,
        summary=import_summary,
        written_inputs=tuple(sorted(input_members)),
        replaced_inputs=replaced_inputs,
        removed_inputs=removed_inputs,
        replace_all=replace_all,
    )


def clear_managed_input_files(input_dir: Path) -> tuple[str, ...]:
    """清理旧订阅 input，确保 replace-all 或 clear 后 inputs 只保留非导入文件。"""
    removed_inputs: list[str] = []
    for path in scan_input_files(input_dir):
        removed_inputs.append(path.name)
        path.unlink()
    return tuple(removed_inputs)


def write_input_atomically(path: Path, content: bytes) -> None:
    """通过临时文件和 os.replace 写入 input，便于运行中的 watcher 感知替换。"""
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_bytes(content)
    os.replace(tmp_path, path)
