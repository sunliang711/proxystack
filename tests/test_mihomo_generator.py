"""mihomo 配置生成器测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Optional

import pytest
from ruamel.yaml import YAML

from proxystack.config import load_config
from proxystack.config import load_stacks
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.generator.mihomo import MihomoGeneratorError
from proxystack.generator.mihomo import dumps_mihomo_config
from proxystack.generator.mihomo import normalize_internal_endpoint_address
from proxystack.generator.mihomo import render_mihomo_config

GOLDEN_DIR = Path("tests/golden/mihomo")


@pytest.mark.parametrize(
    ("stack_name", "golden_name"),
    [
        ("usa1", "usa1.yaml"),
        ("usa2", "usa2.yaml"),
        ("auto", "auto.yaml"),
    ],
)
def test_render_mihomo_examples_match_golden(stack_name: str, golden_name: str) -> None:
    """验证示例 stack 生成稳定 mihomo YAML。"""
    config = load_config(Path("tests/fixtures/example-project/config.yaml"))
    stack_set = load_stacks(config, check_system_ports=False)

    assert dumps_mihomo_config(stack_set, stack_name) == (GOLDEN_DIR / golden_name).read_text(encoding="utf-8")


def test_render_mihomo_output_is_yaml() -> None:
    """验证 dumps 输出可以被 YAML parser 读取。"""
    config = load_config(Path("tests/fixtures/example-project/config.yaml"))
    stack_set = load_stacks(config, check_system_ports=False)

    parsed_config = YAML(typ="safe").load(dumps_mihomo_config(stack_set, "auto"))

    assert parsed_config["ipv6"] is True
    assert parsed_config["socks-port"] == 17093
    assert [proxy["name"] for proxy in parsed_config["proxies"]] == ["usa1-local", "usa2-local"]


def test_render_mihomo_raw_proxy_overrides_name() -> None:
    """验证 raw upstream 原样复制配置，但 name 始终使用 upstream.name。"""
    stack_set = make_stack_set(
        make_stack(
            "raw",
            upstreams=[
                {
                    "name": "server-a",
                    "type": "raw",
                    "config": {
                        "name": "ignored",
                        "type": "shadowsocks",
                        "server": "server-a.example.com",
                        "port": 8388,
                        "cipher": "aes-256-gcm",
                        "password": "raw-pass",
                    },
                }
            ],
            groups=[
                {
                    "name": "AllProxy",
                    "type": "select",
                    "proxies": ["server-a", "DIRECT"],
                }
            ],
        )
    )

    rendered_config = render_mihomo_config(stack_set, "raw")

    assert rendered_config["proxies"][0] == {
        "name": "server-a",
        "type": "shadowsocks",
        "server": "server-a.example.com",
        "port": 8388,
        "cipher": "aes-256-gcm",
        "password": "raw-pass",
    }


def test_render_mihomo_xrelay_socks5_proxy_uses_inbound_fields() -> None:
    """验证 xrelay-socks5 upstream 会解析 inbound 并映射 socks5、UDP 和账号字段。"""
    target_stack = make_stack(
        "target",
        xrelay_inbounds=[
            {
                "name": "relay",
                "protocol": "socks5",
                "listen": "0.0.0.0",
                "port": 24001,
                "udp": True,
                "auth": {
                    "type": "password",
                    "username": "relay-user",
                    "password": "relay-pass",
                },
                "sub": True,
            }
        ],
    )
    source_stack = make_stack(
        "source",
        upstreams=[
            {
                "name": "target-local",
                "type": "xrelay-socks5",
                "ref": "target.relay",
            }
        ],
        groups=[
            {
                "name": "AllProxy",
                "type": "select",
                "proxies": ["target-local", "DIRECT"],
            }
        ],
    )
    stack_set = make_stack_set(target_stack, source_stack)

    rendered_config = render_mihomo_config(stack_set, "source")

    assert rendered_config["proxies"][0] == {
        "name": "target-local",
        "type": "socks5",
        "server": "127.0.0.1",
        "port": 24001,
        "udp": True,
        "username": "relay-user",
        "password": "relay-pass",
    }


def test_render_mihomo_groups_and_rules_fields() -> None:
    """验证 groups 保留健康检查字段，rules.extra 排在默认规则前面。"""
    stack_set = make_stack_set(
        make_stack(
            "groups",
            upstreams=[raw_upstream("server-a")],
            groups=[
                {
                    "name": "AutoProxy",
                    "type": "url-test",
                    "proxies": ["server-a"],
                    "url": "http://www.gstatic.com/generate_204",
                    "interval": 120,
                },
                {
                    "name": "BalanceProxy",
                    "type": "load-balance",
                    "proxies": ["server-a"],
                    "url": "http://www.gstatic.com/generate_204",
                    "interval": 120,
                    "strategy": "round-robin",
                },
                {
                    "name": "FallbackProxy",
                    "type": "fallback",
                    "proxies": ["server-a"],
                    "url": "http://www.gstatic.com/generate_204",
                    "interval": 120,
                },
                {
                    "name": "AllProxy",
                    "type": "select",
                    "proxies": ["AutoProxy", "BalanceProxy", "FallbackProxy", "server-a", "DIRECT"],
                },
            ],
            rules={
                "profile": "default",
                "final": "AllProxy",
                "extra": ["DOMAIN-SUFFIX,example.com,AllProxy"],
            },
        )
    )

    rendered_config = render_mihomo_config(stack_set, "groups")

    assert rendered_config["proxy-groups"][0]["url"] == "http://www.gstatic.com/generate_204"
    assert rendered_config["proxy-groups"][1]["strategy"] == "round-robin"
    assert rendered_config["proxy-groups"][2]["type"] == "fallback"
    assert rendered_config["rules"][0] == "DOMAIN-SUFFIX,example.com,AllProxy"
    assert rendered_config["rules"][-1] == "MATCH,AllProxy"


@pytest.mark.parametrize(
    ("enabled", "clash_enabled", "message"),
    [
        (False, True, "stack is disabled"),
        (True, False, "clash is disabled"),
    ],
)
def test_render_mihomo_skips_disabled_sources(enabled: bool, clash_enabled: bool, message: str) -> None:
    """验证禁用 stack 或禁用 clash 时不生成 mihomo YAML。"""
    stack_set = make_stack_set(make_stack("disabled", enabled=enabled, clash_enabled=clash_enabled))

    with pytest.raises(MihomoGeneratorError, match=message):
        dumps_mihomo_config(stack_set, "disabled")


def test_render_mihomo_requires_one_socks_listener() -> None:
    """验证生成器拒绝缺失 socks listener 的 clash 配置。"""
    stack_set = make_stack_set(make_stack("nolisten", listener_socks=[]))

    with pytest.raises(MihomoGeneratorError, match="exactly one clash socks listener"):
        dumps_mihomo_config(stack_set, "nolisten")


def test_clash_mixed_listener_rejected_by_model() -> None:
    """验证 listeners.mixed 会在模型校验阶段失败，生成器不会静默忽略。"""
    with pytest.raises(ValueError, match="listeners.mixed is not supported in P0"):
        make_stack("mixed", listeners={"socks": [socks_listener()], "mixed": {"port": 7890}})


@pytest.mark.parametrize(
    ("address", "expected_address"),
    [
        ("0.0.0.0", "127.0.0.1"),
        ("::", "::1"),
        ("127.0.0.1", "127.0.0.1"),
    ],
)
def test_normalize_internal_endpoint_address(address: str, expected_address: str) -> None:
    """验证内部连接目标地址归一规则。"""
    assert normalize_internal_endpoint_address(address) == expected_address


def make_stack_set(*stacks: Stack) -> StackSet:
    """生成测试用 StackSet。"""
    return StackSet(config=load_config(Path("tests/fixtures/example-project/config.yaml")), stacks=list(stacks))


def make_stack(
    name: str,
    *,
    enabled: bool = True,
    clash_enabled: bool = True,
    listener_socks: Optional[list[dict[str, Any]]] = None,
    listeners: Optional[dict[str, Any]] = None,
    xrelay_inbounds: Optional[list[dict[str, Any]]] = None,
    upstreams: Optional[list[dict[str, Any]]] = None,
    groups: Optional[list[dict[str, Any]]] = None,
    rules: Optional[dict[str, Any]] = None,
) -> Stack:
    """生成测试用 stack 模型，聚焦 mihomo 生成所需字段。"""
    if listeners is None:
        listeners = {
            "socks": [socks_listener()] if listener_socks is None else listener_socks,
        }
    return Stack.model_validate(
        {
            "name": name,
            "enabled": enabled,
            "role": "edge",
            "labels": ["test"],
            "xrelay": {
                "enabled": True,
                "outbound": {
                    "type": "direct",
                },
                "inbounds": xrelay_inbounds or [socks_inbound()],
            },
            "clash": {
                "enabled": clash_enabled,
                "mode": "Rule",
                "controller": {
                    "listen": "127.0.0.1:19001",
                    "secret": "demo-secret",
                },
                "listeners": listeners,
                "upstreams": upstreams or [],
                "groups": groups
                or [
                    {
                        "name": "AllProxy",
                        "type": "select",
                        "proxies": ["DIRECT"],
                    }
                ],
                "rules": rules
                or {
                    "profile": "default",
                },
            },
        }
    )


def socks_listener() -> dict[str, Any]:
    """生成默认 clash socks listener。"""
    return {
        "name": "local",
        "listen": "127.0.0.1",
        "port": 17001,
    }


def socks_inbound() -> dict[str, Any]:
    """生成默认 xrelay socks5 inbound。"""
    return {
        "name": "relay",
        "protocol": "socks5",
        "listen": "127.0.0.1",
        "port": 24001,
        "auth": {
            "type": "noauth",
        },
        "udp": False,
        "sub": False,
    }


def raw_upstream(name: str) -> dict[str, Any]:
    """生成默认 raw shadowsocks upstream。"""
    return {
        "name": name,
        "type": "raw",
        "config": {
            "type": "shadowsocks",
            "server": f"{name}.example.com",
            "port": 8388,
            "cipher": "aes-256-gcm",
            "password": "raw-pass",
        },
    }
