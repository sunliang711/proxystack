"""Xray 配置生成器测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typing import Optional

import pytest

from proxystack.config import load_config
from proxystack.config import load_stacks
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.generator.xray import XrayGeneratorError
from proxystack.generator.xray import dumps_xray_config
from proxystack.generator.xray import normalize_internal_endpoint_address

GOLDEN_DIR = Path("tests/golden/xray")
SS2022_SERVER_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
SS2022_ALICE_KEY = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="
SS2022_BOB_KEY = "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI="


@pytest.mark.parametrize(
    ("stack_name", "golden_name"),
    [
        ("usa1", "usa1.json"),
        ("usa2", "usa2.json"),
        ("auto", "auto.json"),
    ],
)
def test_render_xray_examples_match_golden(stack_name: str, golden_name: str) -> None:
    """验证示例 stack 生成稳定 Xray JSON。"""
    config = load_config(Path("tests/fixtures/example-project/config.yaml"))
    stack_set = load_stacks(config, check_system_ports=False)

    assert dumps_xray_config(stack_set, stack_name) == (GOLDEN_DIR / golden_name).read_text(encoding="utf-8")


def test_render_xray_inbound_matrix_matches_golden() -> None:
    """验证所有 inbound 类型和 direct outbound 的生成结果。"""
    stack_set = make_stack_set(
        make_stack(
            "matrix",
            {"type": "direct"},
            inbound_matrix(),
        )
    )

    assert dumps_xray_config(stack_set, "matrix") == (GOLDEN_DIR / "matrix.json").read_text(encoding="utf-8")


def test_render_xray_vmess_inbound_supports_multiple_users() -> None:
    """验证 vmess users 会生成同一个 inbound 下的多个 clients。"""
    stack_set = make_stack_set(
        make_stack(
            "multi",
            {"type": "direct"},
            [
                {
                    "name": "vmess",
                    "protocol": "vmess",
                    "listen": "0.0.0.0",
                    "port": 26001,
                    "network": "raw",
                    "sub": True,
                    "users": [
                        {
                            "user": "alice",
                            "uuid": "11111111-1111-4111-8111-111111111111",
                            "email": "alice@example.com",
                            "remark": "alice vmess",
                        },
                        {
                            "user": "bob",
                            "uuid": "22222222-2222-4222-8222-222222222222",
                            "remark": "bob vmess",
                        },
                    ],
                }
            ],
        )
    )

    rendered_config = json.loads(dumps_xray_config(stack_set, "multi"))

    assert rendered_config["inbounds"][0]["settings"]["clients"] == [
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "alterId": 0,
            "email": "alice@example.com",
        },
        {
            "id": "22222222-2222-4222-8222-222222222222",
            "alterId": 0,
            "email": "bob",
        },
    ]
    assert rendered_config["inbounds"][0]["streamSettings"]["network"] == "raw"


def test_render_xray_shadowsocks_inbound_supports_multiple_users() -> None:
    """验证传统 shadowsocks users 会生成同一个 inbound 下的多个 clients。"""
    stack_set = make_stack_set(
        make_stack(
            "ssmulti",
            {"type": "direct"},
            [
                {
                    "name": "ss",
                    "protocol": "shadowsocks",
                    "listen": "0.0.0.0",
                    "port": 26001,
                    "method": "aes-256-gcm",
                    "password": "server-pass",
                    "sub": True,
                    "users": [
                        {
                            "user": "alice",
                            "password": "alice-pass",
                            "method": "aes-128-gcm",
                            "email": "alice@example.com",
                        },
                        {
                            "user": "bob",
                            "password": "bob-pass",
                        },
                    ],
                }
            ],
        )
    )

    rendered_config = json.loads(dumps_xray_config(stack_set, "ssmulti"))

    assert rendered_config["inbounds"][0]["settings"] == {
        "method": "aes-256-gcm",
        "password": "server-pass",
        "network": "tcp",
        "clients": [
            {
                "password": "alice-pass",
                "email": "alice@example.com",
                "method": "aes-128-gcm",
            },
            {
                "password": "bob-pass",
                "email": "bob",
                "method": "aes-256-gcm",
            },
        ],
    }


def test_render_xray_shadowsocks_2022_inbound_supports_multiple_users() -> None:
    """验证 SS2022 users 会生成共享 method 的多用户 clients。"""
    stack_set = make_stack_set(
        make_stack(
            "ss2022",
            {"type": "direct"},
            [
                {
                    "name": "ss2022",
                    "protocol": "shadowsocks",
                    "listen": "0.0.0.0",
                    "port": 26001,
                    "method": "2022-blake3-aes-256-gcm",
                    "password": SS2022_SERVER_KEY,
                    "sub": True,
                    "users": [
                        {
                            "user": "alice",
                            "password": SS2022_ALICE_KEY,
                        },
                        {
                            "user": "bob",
                            "password": SS2022_BOB_KEY,
                        },
                    ],
                }
            ],
        )
    )

    rendered_config = json.loads(dumps_xray_config(stack_set, "ss2022"))

    assert rendered_config["inbounds"][0]["settings"] == {
        "method": "2022-blake3-aes-256-gcm",
        "password": SS2022_SERVER_KEY,
        "network": "tcp",
        "clients": [
            {
                "password": SS2022_ALICE_KEY,
                "email": "alice",
            },
            {
                "password": SS2022_BOB_KEY,
                "email": "bob",
            },
        ],
    }


def test_shadowsocks_2022_rejects_non_base64_psk() -> None:
    """验证 SS2022 password 不是 base64 PSK 时在配置校验阶段失败。"""
    with pytest.raises(ValueError, match="shadowsocks 2022 inbound password must be a base64-encoded PSK"):
        make_stack(
            "ss2022",
            {"type": "direct"},
            [
                {
                    "name": "ss2022",
                    "protocol": "shadowsocks",
                    "listen": "0.0.0.0",
                    "port": 26001,
                    "method": "2022-blake3-aes-256-gcm",
                    "password": "server-key",
                    "sub": True,
                    "users": [
                        {
                            "user": "alice",
                            "password": SS2022_ALICE_KEY,
                        },
                    ],
                }
            ],
        )


def test_shadowsocks_2022_rejects_wrong_psk_length() -> None:
    """验证 SS2022 password base64 解码长度和 method 不匹配时失败。"""
    with pytest.raises(ValueError, match="shadowsocks 2022 user password for alice must decode to 32 bytes"):
        make_stack(
            "ss2022",
            {"type": "direct"},
            [
                {
                    "name": "ss2022",
                    "protocol": "shadowsocks",
                    "listen": "0.0.0.0",
                    "port": 26001,
                    "method": "2022-blake3-aes-256-gcm",
                    "password": SS2022_SERVER_KEY,
                    "sub": True,
                    "users": [
                        {
                            "user": "alice",
                            "password": "AAAAAAAAAAAAAAAAAAAAAA==",
                        },
                    ],
                }
            ],
        )


def test_render_xray_socks5_outbound_matches_golden() -> None:
    """验证外部 socks5 outbound 的生成结果。"""
    stack_set = make_stack_set(
        make_stack(
            "socksout",
            {
                "type": "socks5",
                "server": "socks.example.com",
                "port": 1080,
                "username": "up-user",
                "password": "up-pass",
            },
            [socks_noauth_inbound()],
        )
    )

    assert dumps_xray_config(stack_set, "socksout") == (GOLDEN_DIR / "socks-outbound.json").read_text(
        encoding="utf-8"
    )


def test_render_xray_http_outbound_matches_golden() -> None:
    """验证外部 http outbound 的生成结果。"""
    stack_set = make_stack_set(
        make_stack(
            "httpout",
            {
                "type": "http",
                "server": "http.example.com",
                "port": 8080,
                "username": "http-up-user",
                "password": "http-up-pass",
            },
            [socks_noauth_inbound()],
        )
    )

    assert dumps_xray_config(stack_set, "httpout") == (GOLDEN_DIR / "http-outbound.json").read_text(
        encoding="utf-8"
    )


def test_render_xray_clash_wildcard_listener_matches_golden() -> None:
    """验证 clash listener 为 wildcard 时会生成 loopback socks outbound。"""
    stack_set = make_stack_set(
        make_stack(
            "wildcard",
            {"type": "clash", "ref": "wildcard.clash.socks"},
            [socks_noauth_inbound()],
            clash_enabled=True,
            listener_listen="0.0.0.0",
        )
    )

    assert dumps_xray_config(stack_set, "wildcard") == (GOLDEN_DIR / "wildcard-clash.json").read_text(
        encoding="utf-8"
    )


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


@pytest.mark.parametrize(
    ("enabled", "xrelay_enabled", "message"),
    [
        (False, True, "stack is disabled"),
        (True, False, "xrelay is disabled"),
    ],
)
def test_render_xray_skips_disabled_sources(enabled: bool, xrelay_enabled: bool, message: str) -> None:
    """验证禁用 stack 或禁用 xrelay 时不生成 Xray JSON。"""
    stack_set = make_stack_set(
        make_stack(
            "disabled",
            {"type": "direct"},
            [socks_noauth_inbound()],
            enabled=enabled,
            xrelay_enabled=xrelay_enabled,
        )
    )

    with pytest.raises(XrayGeneratorError, match=message):
        dumps_xray_config(stack_set, "disabled")


def test_render_xray_output_is_json() -> None:
    """验证 dumps 输出可以被 JSON parser 读取。"""
    stack_set = make_stack_set(make_stack("jsoncheck", {"type": "direct"}, [socks_noauth_inbound()]))

    parsed_config = json.loads(dumps_xray_config(stack_set, "jsoncheck"))

    assert parsed_config["outbounds"][0]["tag"] == "egress-jsoncheck"
    assert parsed_config["outbounds"][0]["protocol"] == "freedom"
    assert "api" not in parsed_config
    assert "stats" not in parsed_config
    assert "policy" not in parsed_config


def test_render_xray_api_stats_policy_defaults_match_golden() -> None:
    """验证启用 API 和 stats 时生成默认 API、stats 和 policy 配置。"""
    stack_set = make_stack_set(
        make_stack(
            "metrics",
            {"type": "direct"},
            [socks_noauth_inbound()],
            xrelay_overrides={
                "api": {
                    "enabled": True,
                },
                "stats": {
                    "enabled": True,
                },
            },
        )
    )

    assert dumps_xray_config(stack_set, "metrics") == (GOLDEN_DIR / "api-stats-policy.json").read_text(
        encoding="utf-8"
    )


def test_render_xray_api_and_policy_overrides() -> None:
    """验证 stack 级 API 和 policy 配置可以覆盖默认值。"""
    stack_set = make_stack_set(
        make_stack(
            "metrics-custom",
            {"type": "direct"},
            [socks_noauth_inbound()],
            xrelay_overrides={
                "api": {
                    "enabled": True,
                    "tag": "metrics-api",
                    "listen": "127.0.0.1:11085",
                    "services": ["StatsService", "LoggerService"],
                },
                "stats": {
                    "enabled": True,
                },
                "policy": {
                    "levels": {
                        "0": {
                            "statsUserDownlink": False,
                        },
                    },
                    "system": {
                        "statsOutboundDownlink": False,
                    },
                },
            },
        )
    )

    parsed_config = json.loads(dumps_xray_config(stack_set, "metrics-custom"))

    assert parsed_config["api"] == {
        "tag": "metrics-api",
        "listen": "127.0.0.1:11085",
        "services": ["StatsService", "LoggerService"],
    }
    assert parsed_config["policy"]["levels"] == {
        "0": {
            "statsUserUplink": True,
            "statsUserDownlink": False,
        },
    }
    assert parsed_config["policy"]["system"] == {
        "statsInboundUplink": True,
        "statsInboundDownlink": True,
        "statsOutboundUplink": True,
        "statsOutboundDownlink": False,
    }


def test_xray_api_listen_rejects_public_host() -> None:
    """验证 API listen 显式配置为公网地址时会在模型校验阶段失败。"""
    with pytest.raises(ValueError, match="xray api listen must use loopback host"):
        make_stack(
            "public-api",
            {"type": "direct"},
            [socks_noauth_inbound()],
            xrelay_overrides={
                "api": {
                    "enabled": True,
                    "listen": "0.0.0.0:10085",
                },
            },
        )


def make_stack_set(stack: Stack) -> StackSet:
    """生成包含单个测试 stack 的 StackSet。"""
    return StackSet(config=load_config(Path("tests/fixtures/example-project/config.yaml")), stacks=[stack])


def make_stack(
    name: str,
    outbound: dict[str, Any],
    inbounds: list[dict[str, Any]],
    *,
    enabled: bool = True,
    xrelay_enabled: bool = True,
    clash_enabled: bool = False,
    listener_listen: str = "127.0.0.1",
    xrelay_overrides: Optional[dict[str, Any]] = None,
) -> Stack:
    """生成测试用 stack 模型，避免 golden 测试依赖额外 YAML 文件。"""
    xrelay_config: dict[str, Any] = {
        "enabled": xrelay_enabled,
        "outbound": outbound,
        "inbounds": inbounds,
        "api": {
            "enabled": False,
        },
        "stats": {
            "enabled": False,
        },
        "policy": {
            "enabled": False,
        },
    }
    if xrelay_overrides:
        xrelay_config.update(xrelay_overrides)
    return Stack.model_validate(
        {
            "name": name,
            "enabled": enabled,
            "role": "edge",
            "labels": ["test"],
            "xrelay": xrelay_config,
            "clash": {
                "enabled": clash_enabled,
                "mode": "Rule",
                "controller": {
                    "listen": "127.0.0.1:19001",
                    "secret": "demo-secret",
                },
                "listeners": {
                    "socks": [
                        {
                            "name": "local",
                            "listen": listener_listen,
                            "port": 17001,
                        }
                    ],
                },
                "upstreams": [],
                "groups": [
                    {
                        "name": "AllProxy",
                        "type": "select",
                        "proxies": ["DIRECT"],
                    }
                ],
                "rules": {
                    "profile": "default",
                },
            },
        }
    )


def inbound_matrix() -> list[dict[str, Any]]:
    """生成覆盖所有 inbound 类型和鉴权模式的测试数据。"""
    return [
        {
            "name": "vmess-in",
            "protocol": "vmess",
            "listen": "127.0.0.1",
            "port": 26001,
            "network": "raw",
            "tag": "custom-vmess",
            "sub": True,
            "users": [
                {
                    "user": "alice",
                    "uuid": "22222222-2222-4222-8222-222222222222",
                }
            ],
        },
        {
            "name": "ss-in",
            "protocol": "shadowsocks",
            "listen": "127.0.0.1",
            "port": 26002,
            "password": "ss-password",
            "method": "chacha20-ietf-poly1305",
            "udp": True,
            "sub": True,
        },
        socks_noauth_inbound(),
        {
            "name": "socks-password",
            "protocol": "socks5",
            "listen": "127.0.0.1",
            "port": 26004,
            "auth": {
                "type": "password",
                "username": "sock-user",
                "password": "sock-pass",
            },
            "udp": True,
            "sub": True,
        },
        {
            "name": "http-noauth",
            "protocol": "http",
            "listen": "127.0.0.1",
            "port": 26005,
            "auth": {
                "type": "noauth",
            },
            "sub": False,
        },
        {
            "name": "http-password",
            "protocol": "http",
            "listen": "127.0.0.1",
            "port": 26006,
            "auth": {
                "type": "password",
                "username": "http-user",
                "password": "http-pass",
            },
            "sub": True,
        },
    ]


def socks_noauth_inbound() -> dict[str, Any]:
    """生成 noauth socks5 inbound 测试数据。"""
    return {
        "name": "socks-noauth",
        "protocol": "socks5",
        "listen": "127.0.0.1",
        "port": 26003,
        "auth": {
            "type": "noauth",
        },
        "udp": False,
        "sub": False,
    }
