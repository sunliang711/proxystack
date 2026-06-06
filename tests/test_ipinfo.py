"""ipinfo 诊断能力测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from proxystack.diagnostics import ipinfo as ipinfo_module
from proxystack.diagnostics.ipinfo import CurlResult
from proxystack.diagnostics.ipinfo import format_ipinfo_report
from proxystack.diagnostics.ipinfo import listener_proxy_url
from proxystack.diagnostics.ipinfo import parse_source_response
from proxystack.diagnostics.ipinfo import query_ipinfo
from proxystack.diagnostics.ipinfo import run_curl
from proxystack.domain.models import SocksListener


def test_query_ipinfo_uses_stack_clash_socks_listener() -> None:
    """验证 ipinfo 使用 stack 的 mihomo socks listener 作为查询代理。"""
    calls: list[tuple[str, str, str, float]] = []

    def fake_curl(proxy_url: str, url: str, family: str, timeout: float) -> CurlResult:
        """记录 curl 参数并返回可解析的 JSON 响应。"""
        calls.append((proxy_url, url, family, timeout))
        return CurlResult(
            returncode=0,
            stdout='{"ip": "198.51.100.10", "city": "Tokyo", "country": "JP", "org": "AS64500"}',
            stderr="",
        )

    report = query_ipinfo(
        Path("examples/config.yaml"),
        "usa1",
        family="ipv4",
        timeout=3.0,
        sources=("https://ipinfo.io/json",),
        curl_runner=fake_curl,
    )

    assert report.proxy_url == "socks5://127.0.0.1:17091"
    assert report.families[0].ip == "198.51.100.10"
    assert report.families[0].region == "Tokyo / JP / AS64500"
    assert calls == [("socks5://127.0.0.1:17091", "https://ipinfo.io/json", "ipv4", 3.0)]
    assert "IP: 198.51.100.10" in "\n".join(format_ipinfo_report(report))


def test_listener_proxy_url_normalizes_wildcard_and_ipv6_hosts() -> None:
    """验证 wildcard 监听地址会转成本机地址，IPv6 地址会补方括号。"""
    wildcard_listener = SocksListener(name="local", listen="0.0.0.0", port=17090)
    ipv6_listener = SocksListener(name="local", listen="::1", port=17091)

    assert listener_proxy_url(wildcard_listener) == "socks5://127.0.0.1:17090"
    assert listener_proxy_url(ipv6_listener) == "socks5://[::1]:17091"


def test_parse_source_response_handles_text_and_wrong_family() -> None:
    """验证 ipinfo 能解析文本响应，并识别 family 不匹配的响应。"""
    ip_value, region_value, wrong_family = parse_source_response(
        "当前 IP：203.0.113.8 来自于：中国 北京 电信",
        "ipv4",
    )
    wrong_ip, wrong_region, wrong_family_ipv6 = parse_source_response(
        '{"ip": "203.0.113.8", "city": "Beijing"}',
        "ipv6",
    )

    assert ip_value == "203.0.113.8"
    assert region_value == "中国 北京 电信"
    assert wrong_family is False
    assert wrong_ip is None
    assert wrong_region is None
    assert wrong_family_ipv6 is True


def test_run_curl_adds_proxy_family_and_timeout(monkeypatch) -> None:
    """验证 run_curl 使用代理、family 和 timeout 参数调用 curl。"""
    calls: list[list[str]] = []

    def fake_run(args, check, capture_output, text):
        """记录 subprocess.run 参数，避免测试执行真实 curl。"""
        calls.append(args)
        assert check is False
        assert capture_output is True
        assert text is True
        return SimpleNamespace(returncode=0, stdout='{"ip": "2001:db8::1"}', stderr="")

    monkeypatch.setattr(ipinfo_module.subprocess, "run", fake_run)

    result = run_curl("socks5://127.0.0.1:17091", "https://ipinfo.io/json", "ipv6", 2.5)

    assert result.returncode == 0
    assert calls == [
        [
            "curl",
            "-sS",
            "-L",
            "-m",
            "2.5",
            "-x",
            "socks5://127.0.0.1:17091",
            "-6",
            "https://ipinfo.io/json",
        ]
    ]
