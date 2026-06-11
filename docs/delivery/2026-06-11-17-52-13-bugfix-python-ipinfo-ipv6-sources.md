# ipinfo IPv6 查询修复说明

## Bug 定位分析

- 问题现象：`ipinfo` 子命令查询 IPv6 时多个来源返回 `curl: (7) Could not connect to server`，最终显示 `IP: 未解析到`。
- 根因位置：`src/proxystack/diagnostics/ipinfo.py` 中 `DEFAULT_IPV6_SOURCES` 缺少 `../clash` 已使用的通用回退来源；同时 `run_curl` 对 IPv6 查询追加 `-6`，会让 curl 连接本地 socks 代理时也强制使用 IPv6。
- 触发条件：mihomo socks listener 只监听 `127.0.0.1`，但 IPv6 查询使用 `curl -6 -x socks5://127.0.0.1:<port>`，curl 会在连接代理阶段失败，尚未访问外部 IP 信息来源。
- 修复思路：为 IPv6 默认来源补齐 `ipinfo.io/json` 和 `myip.ipip.net`；IPv6 查询不再追加 `-6`，由可返回 IPv6 的来源和代理出口完成 IPv6 结果判断。
- 影响评估：仅影响 `ipinfo` 默认 IPv6 查询来源和 curl 参数；IPv4 仍保留 `-4`，代理解析和响应解析逻辑不变。

## Bug 修复摘要

- 问题：当前 `ipinfo` IPv6 默认来源比 `../clash` 少，且 `curl -6` 会导致 IPv4-only 本机 socks listener 无法连接。
- 根因：默认来源过滤过窄；IPv6 查询参数同时影响了代理连接地址族。
- 修复方式：在 `DEFAULT_IPV6_SOURCES` 中加入 `https://ipinfo.io/json` 和 `https://myip.ipip.net`；IPv6 查询不再追加 `-6`，并同步更新单测期望。
- 影响范围：`src/proxystack/diagnostics/ipinfo.py`、`tests/test_ipinfo.py`。
- 验证方式：本地执行 `.venv/bin/python -m pytest tests/test_ipinfo.py -q` 和 `.venv/bin/python -m pytest tests/test_cli.py -q`，均通过；远端 `10.2.183.123` 执行 `ps-agent ipinfo usa --family all --timeout 8 -c /opt/proxystack/config.yaml` 和 `ps-agent ipinfo usa1 --family all --timeout 8 -c /opt/proxystack/config.yaml`，均能解析 IPv4 和 IPv6。
- 回归风险：低；新增来源仍经过既有 family 校验，不匹配 IPv6 的响应会被标记为 `wrong-family`，不会覆盖最终 IPv6 结果。
