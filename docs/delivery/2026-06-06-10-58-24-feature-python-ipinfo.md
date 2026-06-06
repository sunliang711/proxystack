# ipinfo 诊断命令交付说明

## 变更摘要

- 新增 `ps-agent ipinfo <stack>` 命令，通过 stack 的 mihomo socks listener 查询出口 IP。
- 新增 `proxystack.diagnostics.ipinfo` 模块，负责代理 URL 解析、curl 调用、IPv4/IPv6 多源查询和响应解析。
- 补充 CLI 文档，说明 `ipinfo` 依赖系统 `curl`。

## 核心规则

- 默认查询 IPv4 和 IPv6，可通过 `--family ipv4|ipv6` 限定。
- 默认使用来源包括 `ipinfo.io`、`myip.ipip.net`、`ifconfig.me`、`ifconfig.co` 和 `ipify`。
- 查询代理来自 `clash.listeners.socks[0]`，wildcard 监听地址会转换为 `127.0.0.1`。
- P0 只支持 mihomo socks listener，不支持直接通过 xrelay inbound 查询。

## 验证方式

- `.venv/bin/python -m pytest tests/test_ipinfo.py -q`
- `.venv/bin/python -m pytest tests/test_cli.py -q`
- `.venv/bin/python -m pytest -q`
- `git diff --check`
