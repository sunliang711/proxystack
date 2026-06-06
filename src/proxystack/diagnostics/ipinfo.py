"""通过 mihomo socks listener 查询 stack 出口 IP。"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import re
import subprocess
from typing import Callable
from typing import Optional

from proxystack.config import load_config
from proxystack.config import load_stacks
from proxystack.domain.models import SocksListener

DEFAULT_SOURCES = (
    "https://ipinfo.io/json",
    "https://myip.ipip.net",
    "https://ifconfig.me/all.json",
    "https://ifconfig.co/json",
    "https://api64.ipify.org?format=json",
)
FAMILY_LABELS = {
    "ipv4": "IPv4",
    "ipv6": "IPv6",
}
SUPPORTED_FAMILIES = {"all", "ipv4", "ipv6"}
WILDCARD_LISTEN_HOSTS = {"0.0.0.0", "::", ""}


class IpInfoError(ValueError):
    """ipinfo 查询失败异常。"""


@dataclass(frozen=True)
class CurlResult:
    """记录单次 curl 查询结果，便于测试替换外部命令。"""

    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class SourceResult:
    """记录单个 IP 信息来源的解析结果。"""

    url: str
    status: str
    ip: Optional[str]
    region: Optional[str]
    body: str
    error: str


@dataclass(frozen=True)
class FamilyResult:
    """记录 IPv4 或 IPv6 一组来源的查询结果。"""

    family: str
    label: str
    sources: tuple[SourceResult, ...]
    ip: Optional[str]
    region: Optional[str]


@dataclass(frozen=True)
class IpInfoReport:
    """记录一次 stack 出口 IP 查询报告。"""

    stack_name: str
    proxy_url: str
    families: tuple[FamilyResult, ...]


CurlRunner = Callable[[str, str, str, float], CurlResult]


def query_ipinfo(
    config_path: Path,
    stack_name: str,
    family: str = "all",
    timeout: float = 8.0,
    sources: tuple[str, ...] = DEFAULT_SOURCES,
    curl_runner: Optional[CurlRunner] = None,
) -> IpInfoReport:
    """查询指定 stack 的 mihomo 出口 IP，默认同时检查 IPv4 和 IPv6。"""
    normalized_family = family.lower()
    if normalized_family not in SUPPORTED_FAMILIES:
        raise IpInfoError("family must be one of: all, ipv4, ipv6")
    if timeout <= 0:
        raise IpInfoError("timeout must be greater than 0")
    if not sources:
        raise IpInfoError("at least one ipinfo source is required")

    runner = curl_runner or run_curl
    proxy_url = resolve_proxy_url(config_path, stack_name)
    families = ("ipv4", "ipv6") if normalized_family == "all" else (normalized_family,)
    family_results = tuple(
        query_family(proxy_url, query_family_name, sources, timeout, runner)
        for query_family_name in families
    )
    return IpInfoReport(stack_name=stack_name, proxy_url=proxy_url, families=family_results)


def resolve_proxy_url(config_path: Path, stack_name: str) -> str:
    """从 stack 的 mihomo socks listener 生成 curl 可用的代理 URL。"""
    config = load_config(config_path)
    stack_set = load_stacks(config, check_system_ports=False)
    stack = stack_set.by_name().get(stack_name)
    if stack is None:
        raise IpInfoError(f"stack does not exist: {stack_name}")
    if not stack.enabled:
        raise IpInfoError(f"stack is disabled: {stack_name}")
    if not stack.clash.enabled:
        raise IpInfoError(f"clash is disabled: {stack_name}")
    if len(stack.clash.listeners.socks) != 1:
        raise IpInfoError(f"exactly one clash socks listener is required: {stack_name}")
    return listener_proxy_url(stack.clash.listeners.socks[0])


def listener_proxy_url(listener: SocksListener) -> str:
    """把 mihomo socks listener 转换为本机可连接的 socks5 URL。"""
    host = normalize_connect_host(listener.listen)
    return f"socks5://{format_proxy_host(host)}:{listener.port}"


def normalize_connect_host(host: str) -> str:
    """把监听地址转换为本机连接地址，wildcard listener 使用 127.0.0.1。"""
    normalized_host = host.strip().strip("[]")
    if normalized_host in WILDCARD_LISTEN_HOSTS:
        return "127.0.0.1"
    return normalized_host


def format_proxy_host(host: str) -> str:
    """为 curl proxy URL 格式化 host，IPv6 地址需要方括号。"""
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def query_family(
    proxy_url: str,
    family: str,
    sources: tuple[str, ...],
    timeout: float,
    curl_runner: CurlRunner,
) -> FamilyResult:
    """按 IP family 逐个查询来源，并保留首个可解析 IP 和地域。"""
    best_ip: Optional[str] = None
    best_region: Optional[str] = None
    source_results: list[SourceResult] = []

    for url in sources:
        result = curl_runner(proxy_url, url, family, timeout)
        body = result.stdout.strip()
        if result.returncode != 0:
            source_results.append(
                SourceResult(
                    url=url,
                    status="failed",
                    ip=None,
                    region=None,
                    body=body,
                    error=result.stderr.strip() or f"curl exited with code {result.returncode}",
                )
            )
            continue

        ip_value, region_value, wrong_family = parse_source_response(body, family)
        if ip_value and best_ip is None:
            best_ip = ip_value
        if region_value and best_region is None:
            best_region = region_value

        parsed = bool(ip_value or region_value)
        status = "wrong-family" if wrong_family else "ok" if parsed else "raw"
        source_results.append(
            SourceResult(
                url=url,
                status=status,
                ip=ip_value,
                region=region_value,
                body=body,
                error="",
            )
        )

    return FamilyResult(
        family=family,
        label=FAMILY_LABELS[family],
        sources=tuple(source_results),
        ip=best_ip,
        region=best_region,
    )


def run_curl(proxy_url: str, url: str, family: str, timeout: float) -> CurlResult:
    """调用 curl 通过指定代理查询一个 IP 信息来源。"""
    command = ["curl", "-sS", "-L", "-m", format_timeout(timeout), "-x", proxy_url]
    if family == "ipv4":
        command.append("-4")
    elif family == "ipv6":
        command.append("-6")
    command.append(url)

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise IpInfoError("curl command not found; please install curl") from exc
    return CurlResult(returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)


def format_timeout(timeout: float) -> str:
    """格式化 curl 超时参数，整数秒避免输出无意义的小数。"""
    timeout_value = float(timeout)
    if timeout_value.is_integer():
        return str(int(timeout_value))
    return str(timeout_value)


def parse_source_response(body: str, family: str) -> tuple[Optional[str], Optional[str], bool]:
    """解析 JSON 或文本来源响应，并识别 IP family 是否匹配。"""
    stripped_body = body.strip()
    if not stripped_body:
        return None, None, False

    try:
        loaded_json = json.loads(stripped_body)
    except json.JSONDecodeError:
        loaded_json = None

    if loaded_json is not None:
        ip_value = extract_ip_from_json(loaded_json)
        region_value = extract_region_from_json(loaded_json)
        if ip_value and not ip_matches_family(ip_value, family):
            return None, None, True
        return ip_value, region_value, False

    ip_candidates = extract_ip_candidates(stripped_body)
    ip_value = ip_candidates[0] if ip_candidates else None
    if ip_value and not ip_matches_family(ip_value, family):
        return None, None, True
    region_value = extract_region_from_text(stripped_body)
    return ip_value, region_value, False


def ip_matches_family(ip_value: str, family: str) -> bool:
    """判断 IP 字符串是否属于指定 family。"""
    try:
        ip_address = ipaddress.ip_address(ip_value)
    except ValueError:
        return False
    if family == "ipv4":
        return ip_address.version == 4
    if family == "ipv6":
        return ip_address.version == 6
    return False


def extract_ip_candidates(text: str) -> list[str]:
    """从文本中提取可被 ipaddress 识别的 IP 候选值。"""
    candidates: list[str] = []
    for token in re.findall(r"[0-9A-Fa-f:.]+", text):
        try:
            ip_value = str(ipaddress.ip_address(token))
        except ValueError:
            continue
        if ip_value not in candidates:
            candidates.append(ip_value)
    return candidates


def extract_ip_from_json(data: object) -> Optional[str]:
    """从常见 JSON 字段或嵌套结构中提取 IP。"""
    if isinstance(data, dict):
        for key in ("ip", "ip_addr", "query", "address"):
            value = data.get(key)
            if isinstance(value, str):
                try:
                    return str(ipaddress.ip_address(value.strip()))
                except ValueError:
                    pass
        for value in data.values():
            found = extract_ip_from_json(value)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = extract_ip_from_json(item)
            if found:
                return found
    return None


def extract_region_from_json(data: object) -> Optional[str]:
    """从常见 JSON 字段中提取城市、地区、国家和运营商信息。"""
    if not isinstance(data, dict):
        return None

    city_keys = ("city",)
    region_keys = ("region", "region_name", "province", "state")
    country_keys = ("country", "country_name", "countryCode", "country_code", "country_iso")
    org_keys = ("org", "asn_org", "isp")

    parts: list[str] = []
    for keys in (city_keys, region_keys, country_keys, org_keys):
        for key in keys:
            value = data.get(key)
            if isinstance(value, str):
                region_part = value.strip()
                if region_part and region_part not in parts:
                    parts.append(region_part)
                break
    return " / ".join(parts) if parts else None


def extract_region_from_text(text: str) -> Optional[str]:
    """从 myip.ipip.net 这类文本响应中提取地域信息。"""
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not line:
        return None
    match = re.search(r"来自于：(.+)$", line)
    if match:
        return match.group(1).strip()
    return None


def format_ipinfo_report(report: IpInfoReport) -> list[str]:
    """把查询报告格式化为 CLI 友好的多行文本。"""
    lines = [
        f"Stack: {report.stack_name}",
        f"Proxy: {report.proxy_url}",
        "",
    ]
    for family in report.families:
        lines.append(f"{family.label}:")
        for source in family.sources:
            lines.append(f"  - {source.url} [{source.status}]")
            if source.ip:
                lines.append(f"    IP: {source.ip}")
            if source.region:
                lines.append(f"    Region: {source.region}")
            if source.status == "failed" and source.error:
                lines.append(f"    Error: {source.error}")
            if source.status == "raw" and source.body:
                lines.append(f"    Body: {source.body}")
        if family.ip is None:
            lines.append("  IP: 未解析到")
        if family.region is None:
            lines.append("  Region: 未解析到")
        lines.append("")

    lines.append("Summary:")
    for family in report.families:
        lines.append(f"  {family.label}:")
        lines.append(f"    IP: {family.ip or '未解析到'}")
        lines.append(f"    Region: {family.region or '未解析到'}")
    return lines
