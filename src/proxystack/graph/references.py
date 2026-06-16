"""配置 ref 解析和 endpoint 索引。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from proxystack.domain.models import ClashListenerUser
from proxystack.domain.models import Stack


@dataclass(frozen=True)
class RefFormatError(ValueError):
    """ref 基础格式错误，保留字段路径便于汇总展示。"""

    path: str
    message: str

    def __str__(self) -> str:
        """输出包含字段路径的错误文本。"""
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class ParsedRef:
    """结构化 ref，避免业务逻辑反复 split 字符串。"""

    raw: str
    stack: str
    component: Optional[str]
    kind: Optional[str]
    name: str

    @classmethod
    def parse_xrelay_inbound(cls, value: Optional[str], path: str) -> "ParsedRef":
        """解析 `<stack>.<inbound_name>` 形式的 xrelay inbound ref。"""
        parts = split_ref(value, 2, path)
        return cls(raw=value or "", stack=parts[0], component="xrelay", kind=None, name=parts[1])

    @classmethod
    def parse_component(cls, value: Optional[str], path: str) -> "ParsedRef":
        """解析 `<stack>.<component>.<kind>` 形式的组件 ref。"""
        parts = split_ref(value, 3, path)
        return cls(raw=value or "", stack=parts[0], component=parts[1], kind=parts[2], name="")


@dataclass(frozen=True)
class Endpoint:
    """可被 ref 指向的本地 endpoint。"""

    ref: str
    stack: str
    component: str
    kind: str
    name: str
    listen: str
    port: int
    path: str
    users: Optional[tuple["EndpointUser", ...]] = None


@dataclass(frozen=True)
class EndpointUser:
    """可被内部 ref 连接复用的 listener 认证用户。"""

    username: str
    password: str


@dataclass(frozen=True)
class ReferenceIndex:
    """跨 stack endpoint 索引，供校验、生成器和 check 复用。"""

    xrelay_inbounds: dict[str, Endpoint]
    clash_listeners: dict[str, Endpoint]

    @classmethod
    def from_stacks(cls, stacks: list[Stack]) -> "ReferenceIndex":
        """从所有启用的 stack 组件中建立 endpoint 索引。"""
        xrelay_inbounds: dict[str, Endpoint] = {}
        clash_listeners: dict[str, Endpoint] = {}
        for stack in stacks:
            if not stack.enabled:
                continue
            if stack.xrelay.enabled:
                xrelay_inbounds.update(index_xrelay_inbounds(stack))
            if stack.clash.enabled:
                clash_listeners.update(index_clash_listeners(stack))
        return cls(xrelay_inbounds=xrelay_inbounds, clash_listeners=clash_listeners)

    def resolve_xrelay_inbound(self, ref: str) -> Optional[Endpoint]:
        """按两段 ref 查询 xrelay inbound endpoint。"""
        return self.xrelay_inbounds.get(ref)

    def resolve_clash_listener(self, ref: str) -> Optional[Endpoint]:
        """按三段 ref 查询 clash listener endpoint。"""
        return self.clash_listeners.get(ref)


def split_ref(value: Optional[str], segment_count: int, path: str) -> list[str]:
    """按期望段数拆分 ref，并校验没有空片段。"""
    if not value:
        raise RefFormatError(path=path, message="ref is required")
    parts = value.split(".")
    if len(parts) != segment_count:
        raise RefFormatError(path=path, message=f"ref must contain {segment_count} dot-separated segments")
    if any(not part for part in parts):
        raise RefFormatError(path=path, message="ref must not contain empty segments")
    return parts


def parse_xrelay_inbound_ref(value: Optional[str], path: str) -> ParsedRef:
    """解析 xrelay-socks5 upstream 使用的两段 inbound ref。"""
    return ParsedRef.parse_xrelay_inbound(value, path)


def parse_component_ref(value: Optional[str], path: str) -> ParsedRef:
    """解析 xrelay outbound 使用的三段组件 ref。"""
    return ParsedRef.parse_component(value, path)


def index_xrelay_inbounds(stack: Stack) -> dict[str, Endpoint]:
    """建立单个 stack 的 xrelay inbound 两段 ref 索引。"""
    endpoints: dict[str, Endpoint] = {}
    for inbound_index, inbound in enumerate(stack.xrelay.inbounds):
        ref = f"{stack.name}.{inbound.name}"
        endpoints[ref] = Endpoint(
            ref=ref,
            stack=stack.name,
            component="xrelay",
            kind=inbound.protocol,
            name=inbound.name,
            listen=inbound.listen,
            port=inbound.port,
            path=f"stacks.{stack.name}.xrelay.inbounds[{inbound_index}]",
        )
    return endpoints


def index_clash_listeners(stack: Stack) -> dict[str, Endpoint]:
    """建立单个 stack 的 clash listener 三段 ref 索引。"""
    endpoints: dict[str, Endpoint] = {}
    for listener_index, listener in enumerate(stack.clash.listeners.socks):
        ref = f"{stack.name}.clash.socks"
        endpoints[ref] = Endpoint(
            ref=ref,
            stack=stack.name,
            component="clash",
            kind="socks",
            name=listener.name,
            listen=listener.listen,
            port=listener.port,
            path=f"stacks.{stack.name}.clash.listeners.socks[{listener_index}]",
            users=endpoint_users(listener.users),
        )
    for listener_index, listener in enumerate(stack.clash.listeners.http):
        ref = f"{stack.name}.clash.http"
        endpoints[ref] = Endpoint(
            ref=ref,
            stack=stack.name,
            component="clash",
            kind="http",
            name=listener.name,
            listen=listener.listen,
            port=listener.port,
            path=f"stacks.{stack.name}.clash.listeners.http[{listener_index}]",
            users=endpoint_users(listener.users),
        )
    return endpoints


def endpoint_users(users: Optional[list[ClashListenerUser]]) -> Optional[tuple[EndpointUser, ...]]:
    """把 listener users 转为 ref endpoint 可携带的不可变认证信息。"""
    if users is None:
        return None
    return tuple(EndpointUser(username=user.username, password=user.password) for user in users)
