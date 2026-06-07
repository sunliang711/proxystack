"""跨配置文件校验逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
import socket

from proxystack.domain.models import GlobalConfig
from proxystack.domain.models import Inbound
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.domain.models import parse_listen
from proxystack.domain.models import resolve_xrelay_api_config
from proxystack.graph import compile_reference_graph


@dataclass(frozen=True)
class ValidationIssue:
    """带字段路径的配置校验问题。"""

    path: str
    message: str

    def __str__(self) -> str:
        """输出面向 CLI 的单行错误。"""
        return f"{self.path}: {self.message}"


class ConfigValidationError(ValueError):
    """跨 stack 配置校验异常。"""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        """保存所有校验问题，便于 CLI 一次性展示。"""
        self.issues = issues
        super().__init__("\n".join(str(issue) for issue in issues))


@dataclass(frozen=True)
class PortBinding:
    """本地监听端口和来源字段路径。"""

    host: str
    port: int
    path: str


def validate_stack_set(stack_set: StackSet, check_system_ports: bool = True) -> None:
    """执行需要跨 stack 才能判断的校验。"""
    issues: list[ValidationIssue] = []
    issues.extend(validate_unique_stack_names(stack_set.stacks))
    issues.extend(validate_public_inbound_auth(stack_set.config, stack_set.stacks))
    port_bindings = collect_port_bindings(stack_set)
    issues.extend(validate_unique_ports(port_bindings))
    issues.extend(validate_reference_graph(stack_set))
    if check_system_ports:
        issues.extend(validate_system_ports_available(port_bindings))
    if issues:
        raise ConfigValidationError(issues)


def validate_unique_stack_names(stacks: list[Stack]) -> list[ValidationIssue]:
    """校验所有 stack 名称唯一。"""
    issues: list[ValidationIssue] = []
    seen_names: dict[str, str] = {}
    for stack in stacks:
        path = stack.source_path.name if stack.source_path else stack.name
        if stack.name in seen_names:
            issues.append(
                ValidationIssue(
                    path=f"stacks.{stack.name}.name",
                    message=f"duplicate stack name, first seen in {seen_names[stack.name]}",
                )
            )
        else:
            seen_names[stack.name] = path
    return issues


def validate_public_inbound_auth(config: GlobalConfig, stacks: list[Stack]) -> list[ValidationIssue]:
    """校验公开监听的 socks/http inbound 必须启用鉴权。"""
    if not config.security.require_auth_for_public_socks_http or config.security.allow_noauth_public:
        return []
    issues: list[ValidationIssue] = []
    for stack in stacks:
        for inbound_index, inbound in enumerate(stack.xrelay.inbounds):
            if inbound.protocol not in {"socks5", "http"}:
                continue
            if is_loopback_host(inbound.listen):
                continue
            if get_auth_type(inbound) == "password":
                continue
            issues.append(
                ValidationIssue(
                    path=f"stacks.{stack.name}.xrelay.inbounds[{inbound_index}].auth",
                    message="public socks/http inbound requires password auth",
                )
            )
    return issues


def collect_port_bindings(stack_set: StackSet) -> list[PortBinding]:
    """收集所有本地监听端口，供唯一性和占用检查使用。"""
    bindings: list[PortBinding] = []
    subscription_host, subscription_port = parse_listen(stack_set.config.subscription.listen)
    bindings.append(
        PortBinding(
            host=subscription_host,
            port=subscription_port,
            path="subscription.listen",
        )
    )
    stacks = stack_set.stacks
    for stack in stacks:
        for inbound_index, inbound in enumerate(stack.xrelay.inbounds):
            bindings.append(
                PortBinding(
                    host=inbound.listen,
                    port=inbound.port,
                    path=f"stacks.{stack.name}.xrelay.inbounds[{inbound_index}].port",
                )
            )
        for listener_index, listener in enumerate(stack.clash.listeners.socks):
            bindings.append(
                PortBinding(
                    host=listener.listen,
                    port=listener.port,
                    path=f"stacks.{stack.name}.clash.listeners.socks[{listener_index}].port",
                )
            )
        controller_host, controller_port = parse_listen(stack.clash.controller.listen)
        bindings.append(
            PortBinding(
                host=controller_host,
                port=controller_port,
                path=f"stacks.{stack.name}.clash.controller.listen",
            )
        )
        api_config = resolve_xrelay_api_config(stack_set.config.defaults.xrelay, stack.xrelay)
        if api_config.enabled:
            api_host, api_port = parse_listen(api_config.listen)
            bindings.append(
                PortBinding(
                    host=api_host,
                    port=api_port,
                    path=f"stacks.{stack.name}.xrelay.api.listen",
                )
            )
    return bindings


def validate_unique_ports(bindings: list[PortBinding]) -> list[ValidationIssue]:
    """校验本地监听端口在所有 stack 中全局唯一。"""
    issues: list[ValidationIssue] = []
    seen_ports: dict[int, PortBinding] = {}
    for binding in bindings:
        if binding.port in seen_ports:
            first_binding = seen_ports[binding.port]
            issues.append(
                ValidationIssue(
                    path=binding.path,
                    message=f"duplicate listen port {binding.port}, first seen at {first_binding.path}",
                )
            )
            continue
        seen_ports[binding.port] = binding
    return issues


def validate_system_ports_available(bindings: list[PortBinding]) -> list[ValidationIssue]:
    """校验配置声明的本地监听端口当前未被系统占用。"""
    issues: list[ValidationIssue] = []
    checked_ports: set[tuple[str, int]] = set()
    for binding in bindings:
        key = (binding.host, binding.port)
        if key in checked_ports:
            continue
        checked_ports.add(key)
        if is_port_available(binding.host, binding.port):
            continue
        issues.append(
            ValidationIssue(
                path=binding.path,
                message=f"listen port {binding.port} is already in use",
            )
        )
    return issues


def validate_reference_graph(stack_set: StackSet) -> list[ValidationIssue]:
    """校验跨 stack ref、服务依赖和循环依赖。"""
    graph_result = compile_reference_graph(stack_set)
    return [
        ValidationIssue(path=issue.path, message=issue.message)
        for issue in graph_result.issues
    ]


def is_port_available(host: str, port: int) -> bool:
    """通过尝试 bind 判断本地端口是否可用。"""
    family = socket.AF_INET6 if ":" in host and host != "0.0.0.0" else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def is_loopback_host(host: str) -> bool:
    """判断监听地址是否为本机回环地址。"""
    return host in {"127.0.0.1", "::1", "localhost"}


def get_auth_type(inbound: Inbound) -> str:
    """返回 inbound 鉴权类型，缺省按 noauth 处理。"""
    if inbound.auth is None:
        return "noauth"
    return inbound.auth.type
