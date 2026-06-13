"""Xray JSON 配置生成。"""

from __future__ import annotations

import json
from typing import Any
from typing import Optional

from proxystack.domain.models import Inbound
from proxystack.domain.models import InboundUser
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.domain.models import XrelayApiConfig
from proxystack.domain.models import XrelayOutbound
from proxystack.domain.models import XrelayPolicyConfig
from proxystack.domain.models import XrelayPolicyLevelConfig
from proxystack.domain.models import XrelayPolicySystemConfig
from proxystack.domain.models import XrelayStatsConfig
from proxystack.domain.models import inbound_user_email
from proxystack.domain.models import is_shadowsocks_2022_method
from proxystack.domain.models import resolve_xrelay_api_config
from proxystack.domain.models import resolve_xrelay_policy_config
from proxystack.domain.models import resolve_xrelay_stats_config
from proxystack.graph import ReferenceGraph
from proxystack.graph import build_reference_graph

XRAY_OUTBOUND_TAG_PREFIX = "egress"
XRAY_POLICY_STATS_FIELDS = {
    "statsInboundUplink": "stats_inbound_uplink",
    "statsInboundDownlink": "stats_inbound_downlink",
    "statsOutboundUplink": "stats_outbound_uplink",
    "statsOutboundDownlink": "stats_outbound_downlink",
}
XRAY_POLICY_LEVEL_STATS_FIELDS = {
    "statsUserUplink": "stats_user_uplink",
    "statsUserDownlink": "stats_user_downlink",
}


class XrayGeneratorError(ValueError):
    """Xray 配置生成失败异常。"""


def render_xray_config(stack_set: StackSet, stack_name: str) -> dict[str, Any]:
    """生成指定启用 stack 的 Xray 配置字典，供 CLI render 和运行配置写入复用。"""
    stack = get_enabled_xrelay_stack(stack_set, stack_name)
    defaults = stack_set.config.defaults.xrelay
    api_config = resolve_xrelay_api_config(defaults, stack.xrelay)
    stats_config = resolve_xrelay_stats_config(defaults, stack.xrelay)
    policy_config = resolve_xrelay_policy_config(defaults, stack.xrelay)
    graph = build_reference_graph(stack_set)
    config: dict[str, Any] = {
        "log": {
            "loglevel": defaults.loglevel,
        },
    }
    if api_config.enabled:
        config["api"] = render_xray_api(api_config)
    if stats_config.enabled:
        config["stats"] = render_xray_stats(stats_config)
    if policy_config.enabled or stats_config.enabled:
        config["policy"] = render_xray_policy(policy_config, stats_config.enabled)
    config["inbounds"] = [render_inbound(inbound) for inbound in stack.xrelay.inbounds]
    config["outbounds"] = [render_outbound(stack.xrelay.outbound, graph, stack.name)]
    return config


def dumps_xray_config(stack_set: StackSet, stack_name: str) -> str:
    """把指定 stack 的 Xray 配置编码为稳定、可读的 JSON 文本。"""
    return json.dumps(render_xray_config(stack_set, stack_name), ensure_ascii=False, indent=2) + "\n"


def render_xray_api(api_config: XrelayApiConfig) -> dict[str, Any]:
    """生成 Xray API 配置，使用简化 listen 模式避免额外 routing 配置。"""
    return {
        "tag": api_config.tag,
        "listen": api_config.listen,
        "services": api_config.services,
    }


def render_xray_stats(stats_config: XrelayStatsConfig) -> dict[str, Any]:
    """生成 Xray stats 配置；官方 StatsObject 当前不需要参数。"""
    return {}


def render_xray_policy(policy_config: XrelayPolicyConfig, stats_enabled: bool) -> dict[str, Any]:
    """生成 Xray policy 配置，stats 开启时默认启用流量统计项。"""
    policy: dict[str, Any] = {}
    levels = render_xray_policy_levels(policy_config.levels)
    if levels:
        policy["levels"] = levels
    policy["system"] = render_xray_policy_system(policy_config.system, stats_enabled)
    return policy


def render_xray_policy_levels(levels_config: dict[str, XrelayPolicyLevelConfig]) -> dict[str, dict[str, bool]]:
    """生成 Xray policy levels 的用户流量统计开关。"""
    levels: dict[str, dict[str, bool]] = {}
    for level in sorted(levels_config):
        level_config = render_xray_policy_level(levels_config[level])
        if level_config:
            levels[level] = level_config
    return levels


def render_xray_policy_level(level_config: XrelayPolicyLevelConfig) -> dict[str, bool]:
    """生成单个 Xray policy level 的用户流量统计开关。"""
    rendered_level: dict[str, bool] = {}
    for xray_field, model_field in XRAY_POLICY_LEVEL_STATS_FIELDS.items():
        value = getattr(level_config, model_field)
        if value is not None:
            rendered_level[xray_field] = value
    return rendered_level


def render_xray_policy_system(
    system_config: XrelayPolicySystemConfig,
    stats_enabled: bool,
) -> dict[str, bool]:
    """生成 Xray system policy 的四个全局流量统计开关。"""
    default_value = stats_enabled
    return {
        xray_field: policy_system_value(system_config, model_field, default_value)
        for xray_field, model_field in XRAY_POLICY_STATS_FIELDS.items()
    }


def policy_system_value(
    system_config: XrelayPolicySystemConfig,
    model_field: str,
    default_value: bool,
) -> bool:
    """读取显式 policy system 覆盖值，未配置时使用调用方默认值。"""
    value = getattr(system_config, model_field)
    if value is None:
        return default_value
    return value


def get_enabled_xrelay_stack(stack_set: StackSet, stack_name: str) -> Stack:
    """按名称获取可生成 Xray 的 stack，并拒绝禁用 stack 或禁用 xrelay。"""
    stack = stack_set.by_name().get(stack_name)
    if stack is None:
        raise XrayGeneratorError(f"stack does not exist: {stack_name}")
    if not stack.enabled:
        raise XrayGeneratorError(f"stack is disabled: {stack_name}")
    if not stack.xrelay.enabled:
        raise XrayGeneratorError(f"xrelay is disabled: {stack_name}")
    return stack


def render_inbound(inbound: Inbound) -> dict[str, Any]:
    """按 inbound 协议分发生成 Xray inbound 配置。"""
    if inbound.protocol == "vmess":
        return render_vmess_inbound(inbound)
    if inbound.protocol == "shadowsocks":
        return render_shadowsocks_inbound(inbound)
    if inbound.protocol == "socks5":
        return render_socks_inbound(inbound)
    if inbound.protocol == "http":
        return render_http_inbound(inbound)
    raise XrayGeneratorError(f"unsupported xray inbound protocol: {inbound.protocol}")


def base_inbound_config(inbound: Inbound, protocol: str) -> dict[str, Any]:
    """生成所有 Xray inbound 共享的基础字段。"""
    return {
        "tag": inbound_tag(inbound),
        "listen": inbound.listen,
        "port": inbound.port,
        "protocol": protocol,
    }


def inbound_tag(inbound: Inbound) -> str:
    """返回显式 tag 或按 `<protocol>:<port>:<name>` 生成默认 tag。"""
    if inbound.tag:
        return inbound.tag
    return f"{inbound.protocol}:{inbound.port}:{inbound.name}"


def render_vmess_inbound(inbound: Inbound) -> dict[str, Any]:
    """生成 vmess inbound 配置，按 users 输出一个或多个客户端。"""
    config = base_inbound_config(inbound, "vmess")
    config["settings"] = {
        "clients": render_vmess_clients(inbound),
    }
    config["streamSettings"] = {
        "network": inbound.network,
    }
    return config


def render_vmess_clients(inbound: Inbound) -> list[dict[str, Any]]:
    """把 vmess inbound 的 users 列表转换为 Xray clients。"""
    return [render_vmess_user_client(vmess_user) for vmess_user in inbound.users]


def render_vmess_user_client(vmess_user: InboundUser) -> dict[str, Any]:
    """生成 vmess 多用户 client，并写入 email 供 Xray 用户统计使用。"""
    return {
        "id": vmess_user.uuid,
        "alterId": 0,
        "email": inbound_user_email(vmess_user),
    }


def render_shadowsocks_inbound(inbound: Inbound) -> dict[str, Any]:
    """生成 shadowsocks inbound 配置，支持传统 SS 和 SS2022 多用户。"""
    config = base_inbound_config(inbound, "shadowsocks")
    settings: dict[str, Any] = {
        "method": inbound.method or inbound.cipher,
        "password": inbound.password,
        "network": "tcp,udp" if inbound.udp else "tcp",
    }
    if inbound.users:
        settings["clients"] = [render_shadowsocks_user(inbound, shadowsocks_user) for shadowsocks_user in inbound.users]
    config["settings"] = settings
    return config


def render_shadowsocks_user(inbound: Inbound, shadowsocks_user: InboundUser) -> dict[str, Any]:
    """生成 shadowsocks 多用户 UserObject，SS2022 统一使用 inbound 级 method。"""
    inbound_method = inbound.method or inbound.cipher or ""
    user_config = {
        "password": shadowsocks_user.password,
        "email": inbound_user_email(shadowsocks_user),
    }
    if not is_shadowsocks_2022_method(inbound_method):
        user_config["method"] = shadowsocks_user.method or shadowsocks_user.cipher or inbound_method
    return user_config


def render_socks_inbound(inbound: Inbound) -> dict[str, Any]:
    """生成 socks inbound 配置，支持 noauth 和 password 鉴权。"""
    config = base_inbound_config(inbound, "socks")
    auth_type = inbound_auth_type(inbound)
    settings: dict[str, Any] = {
        "auth": auth_type,
        "udp": inbound.udp,
    }
    if auth_type == "password":
        settings["accounts"] = [inbound_account(inbound)]
    config["settings"] = settings
    return config


def render_http_inbound(inbound: Inbound) -> dict[str, Any]:
    """生成 http inbound 配置，支持 noauth 和 password 鉴权。"""
    config = base_inbound_config(inbound, "http")
    settings: dict[str, Any] = {}
    if inbound_auth_type(inbound) == "password":
        settings["accounts"] = [inbound_account(inbound)]
    config["settings"] = settings
    return config


def inbound_auth_type(inbound: Inbound) -> str:
    """返回 socks/http inbound 的鉴权类型，未配置时按 noauth 处理。"""
    if inbound.auth is None:
        return "noauth"
    return inbound.auth.type


def inbound_account(inbound: Inbound) -> dict[str, str]:
    """把 password 鉴权配置转换为 Xray account 字段。"""
    if inbound.auth is None or not inbound.auth.username or not inbound.auth.password:
        raise XrayGeneratorError(f"password auth account is incomplete: {inbound.name}")
    return {
        "user": inbound.auth.username,
        "pass": inbound.auth.password,
    }


def render_outbound(outbound: XrelayOutbound, graph: ReferenceGraph, stack_name: str) -> dict[str, Any]:
    """按 xrelay outbound 类型生成 Xray outbound 配置。"""
    outbound_tag = xray_outbound_tag(stack_name)
    if outbound.type == "clash":
        return render_clash_outbound(outbound, graph, outbound_tag)
    if outbound.type == "socks5":
        return render_proxy_outbound("socks", outbound.server, outbound.port, outbound.username, outbound.password, outbound_tag)
    if outbound.type == "http":
        return render_proxy_outbound("http", outbound.server, outbound.port, outbound.username, outbound.password, outbound_tag)
    if outbound.type == "direct":
        return {
            "tag": outbound_tag,
            "protocol": "freedom",
            "settings": {},
        }
    raise XrayGeneratorError(f"unsupported xray outbound type: {outbound.type}")


def xray_outbound_tag(stack_name: str) -> str:
    """生成包含 stack 名的 Xray 出口 tag，便于日志和 stats 排查。"""
    return f"{XRAY_OUTBOUND_TAG_PREFIX}-{stack_name}"


def render_clash_outbound(outbound: XrelayOutbound, graph: ReferenceGraph, outbound_tag: str) -> dict[str, Any]:
    """解析 clash socks listener ref 并生成指向 mihomo 的 socks outbound。"""
    endpoint = graph.index.resolve_clash_listener(outbound.ref or "")
    if endpoint is None:
        raise XrayGeneratorError(f"clash listener ref does not exist: {outbound.ref}")
    return render_proxy_outbound(
        "socks",
        normalize_internal_endpoint_address(endpoint.listen),
        endpoint.port,
        None,
        None,
        outbound_tag,
    )


def render_proxy_outbound(
    protocol: str,
    address: Optional[str],
    port: Optional[int],
    username: Optional[str],
    password: Optional[str],
    outbound_tag: str,
) -> dict[str, Any]:
    """生成 socks/http outbound 通用配置。"""
    if address is None or port is None:
        raise XrayGeneratorError(f"{protocol} outbound requires address and port")
    server: dict[str, Any] = {
        "address": address,
        "port": port,
    }
    if username or password:
        if not username or not password:
            raise XrayGeneratorError(f"{protocol} outbound username and password must be provided together")
        server["users"] = [
            {
                "user": username,
                "pass": password,
            }
        ]
    return {
        "tag": outbound_tag,
        "protocol": protocol,
        "settings": {
            "servers": [server],
        },
    }


def normalize_internal_endpoint_address(address: str) -> str:
    """把本机 wildcard listener 地址归一为可连接的 loopback 地址。"""
    if address == "0.0.0.0":
        return "127.0.0.1"
    if address == "::":
        return "::1"
    return address
