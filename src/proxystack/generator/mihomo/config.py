"""mihomo YAML 配置生成。"""

from __future__ import annotations

from copy import deepcopy
from io import StringIO
from typing import Any

from ruamel.yaml import YAML

from proxystack.domain.models import ClashGroup
from proxystack.domain.models import ClashRules
from proxystack.domain.models import ClashUpstream
from proxystack.domain.models import Inbound
from proxystack.domain.models import SocksListener
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.graph import ReferenceGraph
from proxystack.graph import build_reference_graph
from proxystack.graph import parse_xrelay_inbound_ref
from proxystack.graph.references import RefFormatError

DEFAULT_RULE_PROFILE = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "DOMAIN,localhost,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve",
]
LOOPBACK_LISTEN_HOSTS = {"127.0.0.1", "::1", "localhost"}


class MihomoGeneratorError(ValueError):
    """mihomo 配置生成失败异常。"""


def render_mihomo_config(stack_set: StackSet, stack_name: str) -> dict[str, Any]:
    """生成指定启用 stack 的 mihomo 配置字典，供 CLI render 和后续 apply 复用。"""
    stack = get_enabled_clash_stack(stack_set, stack_name)
    listener = get_single_socks_listener(stack)
    graph = build_reference_graph(stack_set)
    return {
        "mode": stack.clash.mode,
        "log-level": "info",
        "allow-lan": not is_loopback_listen_host(listener.listen),
        "bind-address": listener.listen,
        "external-controller": stack.clash.controller.listen,
        "secret": stack.clash.controller.secret,
        "socks-port": listener.port,
        "proxies": [render_proxy(stack_set, graph, upstream) for upstream in stack.clash.upstreams],
        "proxy-groups": [render_proxy_group(group) for group in stack.clash.groups],
        "rules": render_rules(stack.clash.rules),
    }


def dumps_mihomo_config(stack_set: StackSet, stack_name: str) -> str:
    """把指定 stack 的 mihomo 配置编码为稳定、可读的 YAML 文本。"""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    stream = StringIO()
    yaml.dump(render_mihomo_config(stack_set, stack_name), stream)
    return stream.getvalue()


def get_enabled_clash_stack(stack_set: StackSet, stack_name: str) -> Stack:
    """按名称获取可生成 mihomo 的 stack，并拒绝禁用 stack 或禁用 clash。"""
    stack = stack_set.by_name().get(stack_name)
    if stack is None:
        raise MihomoGeneratorError(f"stack does not exist: {stack_name}")
    if not stack.enabled:
        raise MihomoGeneratorError(f"stack is disabled: {stack_name}")
    if not stack.clash.enabled:
        raise MihomoGeneratorError(f"clash is disabled: {stack_name}")
    return stack


def get_single_socks_listener(stack: Stack) -> SocksListener:
    """读取 P0 唯一 socks listener；缺失时拒绝生成无入口的 mihomo 配置。"""
    if len(stack.clash.listeners.socks) != 1:
        raise MihomoGeneratorError(f"exactly one clash socks listener is required: {stack.name}")
    return stack.clash.listeners.socks[0]


def is_loopback_listen_host(host: str) -> bool:
    """判断 socks listener 是否只监听本机回环地址。"""
    return host in LOOPBACK_LISTEN_HOSTS


def render_proxy(stack_set: StackSet, graph: ReferenceGraph, upstream: ClashUpstream) -> dict[str, Any]:
    """按 upstream 类型分发生成 mihomo proxy 配置。"""
    if upstream.type == "raw":
        return render_raw_proxy(upstream)
    if upstream.type == "xrelay-socks5":
        return render_xrelay_socks5_proxy(stack_set, graph, upstream)
    raise MihomoGeneratorError(f"unsupported mihomo upstream type: {upstream.type}")


def render_raw_proxy(upstream: ClashUpstream) -> dict[str, Any]:
    """复制 raw upstream 配置，并强制使用 upstream.name 作为 mihomo proxy name。"""
    proxy_config = {"name": upstream.name}
    proxy_config.update(deepcopy(upstream.config))
    if proxy_config.get("type") == "vmess":
        # mihomo 新版本要求 raw vmess 显式包含 alterId 和 cipher。
        proxy_config.setdefault("alterId", 0)
        proxy_config.setdefault("cipher", "auto")
    proxy_config["name"] = upstream.name
    return proxy_config


def render_xrelay_socks5_proxy(
    stack_set: StackSet,
    graph: ReferenceGraph,
    upstream: ClashUpstream,
) -> dict[str, Any]:
    """解析两段 xrelay inbound ref，并生成可连接的 mihomo socks5 proxy。"""
    inbound = resolve_xrelay_socks5_inbound(stack_set, graph, upstream)
    proxy_config: dict[str, Any] = {
        "name": upstream.name,
        "type": "socks5",
        "server": normalize_internal_endpoint_address(inbound.listen),
        "port": inbound.port,
        "udp": inbound.udp,
    }
    if inbound.auth is not None and inbound.auth.type == "password":
        # password 鉴权在模型层已校验完整，这里只负责映射 mihomo 字段名。
        proxy_config["username"] = inbound.auth.username
        proxy_config["password"] = inbound.auth.password
    return proxy_config


def resolve_xrelay_socks5_inbound(
    stack_set: StackSet,
    graph: ReferenceGraph,
    upstream: ClashUpstream,
) -> Inbound:
    """根据 xrelay-socks5 ref 返回目标 socks5 inbound 模型。"""
    path = f"clash.upstreams.{upstream.name}.ref"
    try:
        parsed_ref = parse_xrelay_inbound_ref(upstream.ref, path)
    except RefFormatError as exc:
        raise MihomoGeneratorError(str(exc)) from exc
    endpoint = graph.index.resolve_xrelay_inbound(parsed_ref.raw)
    if endpoint is None:
        raise MihomoGeneratorError(f"xrelay inbound ref does not exist: {parsed_ref.raw}")
    if endpoint.kind != "socks5":
        raise MihomoGeneratorError(f"xrelay-socks5 ref must target socks5 inbound: {parsed_ref.raw}")
    target_stack = stack_set.by_name().get(parsed_ref.stack)
    if target_stack is None:
        raise MihomoGeneratorError(f"xrelay inbound stack does not exist: {parsed_ref.stack}")
    for inbound in target_stack.xrelay.inbounds:
        if inbound.name == parsed_ref.name:
            return inbound
    raise MihomoGeneratorError(f"xrelay inbound ref does not exist: {parsed_ref.raw}")


def normalize_internal_endpoint_address(address: str) -> str:
    """把本机 wildcard listener 地址归一为可连接的 loopback 地址。"""
    if address == "0.0.0.0":
        return "127.0.0.1"
    if address == "::":
        return "::1"
    return address


def render_proxy_group(group: ClashGroup) -> dict[str, Any]:
    """生成 mihomo proxy-group 配置，并保留健康检查和负载均衡字段。"""
    group_config: dict[str, Any] = {
        "name": group.name,
        "type": group.type,
        "proxies": group.proxies,
    }
    if group.url is not None:
        group_config["url"] = group.url
    if group.interval is not None:
        group_config["interval"] = group.interval
    if group.type == "load-balance" and group.strategy is not None:
        group_config["strategy"] = group.strategy
    return group_config


def render_rules(rules: ClashRules) -> list[str]:
    """生成 default profile 规则列表，用户 extra 优先，最终 MATCH 始终排在末尾。"""
    if rules.profile != "default":
        raise MihomoGeneratorError(f"unsupported mihomo rules profile: {rules.profile}")
    return [*rules.extra, *DEFAULT_RULE_PROFILE, f"MATCH,{rules.final}"]
