# ipinfo IPv6 来源回退修复说明

## Bug 定位分析

- 问题现象：`ipinfo` 子命令查询 IPv6 时只尝试 `ifconfig.me`、`ifconfig.co`、`api64.ipify.org`，当这些来源连接失败时，最终显示 `IP: 未解析到`。
- 根因位置：`src/proxystack/diagnostics/ipinfo.py` 中 `DEFAULT_IPV6_SOURCES` 缺少 `../clash` 已使用的通用回退来源。
- 触发条件：目标代理出口可通过 `ipinfo.io/json` 或 `myip.ipip.net` 获取 IPv6 信息，但当前默认 IPv6 来源列表未尝试这些来源。
- 修复思路：为 IPv6 默认来源补齐 `ipinfo.io/json` 和 `myip.ipip.net`，保持现有 `curl -6`、解析逻辑和 CLI 输出结构不变。
- 影响评估：仅影响 `ipinfo` 默认 IPv6 查询来源；IPv4 默认来源、代理解析和响应解析逻辑不变。

## Bug 修复摘要

- 问题：当前 `ipinfo` IPv6 默认来源比 `../clash` 少，缺少可用回退。
- 根因：默认来源过滤过窄，导致部分环境下所有 IPv6 来源连接失败后没有继续尝试通用来源。
- 修复方式：在 `DEFAULT_IPV6_SOURCES` 中加入 `https://ipinfo.io/json` 和 `https://myip.ipip.net`，并同步更新单测期望。
- 影响范围：`src/proxystack/diagnostics/ipinfo.py`、`tests/test_ipinfo.py`。
- 验证方式：执行 `.venv/bin/python -m pytest tests/test_ipinfo.py -q` 和 `.venv/bin/python -m pytest tests/test_cli.py -q`，均通过。
- 回归风险：低；新增来源仍经过既有 family 校验，不匹配 IPv6 的响应会被标记为 `wrong-family`，不会覆盖最终 IPv6 结果。
