"""订阅 input、索引、渲染和发布包生成。"""

from __future__ import annotations

from datetime import datetime
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

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic import field_validator
from pydantic import model_validator
from ruamel.yaml import YAML

from proxystack.domain.models import Inbound
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet

SUPPORTED_INPUT_EXTENSIONS = {".yaml", ".yml", ".json"}
BUNDLE_VERSION = 1
INDEX_VERSION = 1
INPUT_VERSION = 1
DEFAULT_ACCESS = {"type": "none"}


class SubscriptionGeneratorError(ValueError):
    """订阅生成、合并或渲染失败异常。"""


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

    input_version: Literal[1]
    source: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    nodes: list[SubscriptionNode] = Field(default_factory=list)

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

    bundle_version: Literal[1]
    source: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    inputs_sha256: dict[str, str]
    template_version: str = "builtin-v1"
    access: SubscriptionAccess = Field(default_factory=SubscriptionAccess)


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
            nodes.append(render_inbound_node(stack_set, stack, inbound))
    return SubscriptionInput(
        input_version=INPUT_VERSION,
        source=source,
        generated_at=now_iso(),
        nodes=nodes,
    )


def render_inbound_node(stack_set: StackSet, stack: Stack, inbound: Inbound) -> SubscriptionNode:
    """把单个 xrelay inbound 映射为订阅节点。"""
    node_data: dict[str, Any] = {
        "id": f"{stack.name}:{inbound.name}",
        "user": inbound.user or "default",
        "protocol": inbound.protocol,
        "server": inbound.server or stack_set.config.external_host,
        "port": inbound.port,
        "tag": inbound_tag(inbound),
        "remark": inbound.remark or inbound.tag or f"{stack.name}-{inbound.name}",
    }
    if inbound.udp:
        node_data["udp"] = inbound.udp
    if inbound.protocol == "vmess":
        node_data["uuid"] = inbound.uuid
        node_data["network"] = inbound.network
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


def merge_input_files(input_dir: Path, access: Optional[SubscriptionAccess] = None) -> SubscriptionIndex:
    """扫描并合并 inputs 目录，供 agent 和 sub 共享。"""
    return merge_inputs(load_inputs(input_dir), access=access)


def merge_inputs(
    inputs: list[tuple[Path, SubscriptionInput]],
    access: Optional[SubscriptionAccess] = None,
) -> SubscriptionIndex:
    """按给定顺序合并多个 input，并在重复 node.id 时失败。"""
    nodes: list[SubscriptionNode] = []
    sources: list[str] = []
    node_sources: dict[str, str] = {}
    for input_path, subscription_input in inputs:
        sources.append(subscription_input.source)
        for node in subscription_input.nodes:
            if node.id in node_sources:
                raise SubscriptionGeneratorError(
                    f"duplicate node id: {node.id}, first seen in {node_sources[node.id]}, repeated in {input_path.name}"
                )
            node_sources[node.id] = input_path.name
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


def render_clash_subscription(index: SubscriptionIndex, user: str) -> str:
    """渲染普通 Clash 订阅 YAML。"""
    return dump_yaml(render_clash_subscription_dict(index, user))


def render_premium_clash_subscription(index: SubscriptionIndex, user: str) -> str:
    """渲染 Premium Clash 订阅 YAML；P0 与普通 Clash 使用同一结构。"""
    return dump_yaml(render_clash_subscription_dict(index, user))


def render_clash_subscription_dict(index: SubscriptionIndex, user: str) -> dict[str, Any]:
    """生成 Clash 订阅字典，只包含客户端节点列表。"""
    nodes = nodes_for_user(index, user)
    return {
        "proxies": [render_clash_proxy(node) for node in nodes],
    }


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


def render_surge_subscription(index: SubscriptionIndex, user: str) -> str:
    """渲染 Surge 订阅文本。"""
    nodes = nodes_for_user(index, user)
    lines = ["[Proxy]"]
    lines.extend(render_surge_proxy(node) for node in nodes)
    lines.append("")
    return "\n".join(lines)


def render_surge_proxy(node: SubscriptionNode) -> str:
    """把订阅节点转换为 Surge proxy 行。"""
    if node.protocol == "vmess":
        return (
            f"{node.remark} = vmess, {node.server}, {node.port}, "
            f"username={node.uuid}, network={node.network}"
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
    return f", username={node.auth.username}, password={node.auth.password}"


def nodes_for_user(index: SubscriptionIndex, user: str) -> list[SubscriptionNode]:
    """从订阅索引中读取指定用户节点，用户不存在或空节点时失败。"""
    nodes = index.users.get(user, [])
    if not nodes:
        raise SubscriptionGeneratorError(f"subscription user has no nodes: {user}")
    return nodes


def dump_yaml(value: dict[str, Any]) -> str:
    """把字典编码为稳定、可读的 YAML 文本。"""
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
    """写入订阅发布包 zip，并返回 manifest。"""
    ensure_unique_bundle_input_names(input_files)
    for name, _content in input_files:
        validate_bundle_input_name(name)
    manifest = BundleManifest(
        bundle_version=BUNDLE_VERSION,
        source=source,
        generated_at=now_iso(),
        inputs_sha256={name: sha256_bytes(content) for name, content in input_files},
        access=access or SubscriptionAccess(),
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
    """读取并校验 current/index.json。"""
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
    if member.is_dir() and name in {"inputs/", "templates/"}:
        return
    if name.startswith("inputs/") and len(path.parts) == 2 and path.parts[1]:
        return
    if name.startswith("templates/") and len(path.parts) == 2 and path.parts[1]:
        return
    raise SubscriptionGeneratorError(f"unexpected bundle path: {name}")


def extract_bundle_inputs(bundle_path: Path, data_dir: Path) -> BundleManifest:
    """校验发布包并把 inputs 解包到 data_dir/inputs。"""
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
            validate_bundle_input_name(name)
        input_dir = data_dir / "inputs"
        input_dir.mkdir(parents=True, exist_ok=True)
        clear_managed_input_files(input_dir)
        for name, content in input_members.items():
            (input_dir / name).write_bytes(content)
    return manifest


def clear_managed_input_files(input_dir: Path) -> None:
    """清理旧订阅 input，确保导入发布包后 current 只来自本次 bundle。"""
    for path in scan_input_files(input_dir):
        path.unlink()
