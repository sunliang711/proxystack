# ipinfo IPv6 默认来源调整

## 问题

`ps-agent ipinfo <stack>` 查询 IPv6 时，默认来源中的 `https://ipinfo.io/json` 和 `https://myip.ipip.net` 可能返回 IPv4，导致输出 `wrong-family`。

## 根因

这两个来源不适合作为当前 IPv6 默认优先来源：`ipinfo.io/json` 是 legacy 入口，IPv6 探测应优先使用新版或 IPv6 专用入口；`myip.ipip.net` 免费服务不提供稳定质量承诺，且当前不适合作为 IPv6 默认来源。

## 修复方式

- 从 `DEFAULT_IPV6_SOURCES` 移除 `https://ipinfo.io/json`。
- 从 `DEFAULT_IPV6_SOURCES` 移除 `https://myip.ipip.net`。
- IPv4 默认来源保持不变。
- 单测断言 IPv6 默认来源不再包含上述两个地址。

## 验证

- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_ipinfo.py -q`
- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_cli.py::test_agent_ipinfo_outputs_report -q`
