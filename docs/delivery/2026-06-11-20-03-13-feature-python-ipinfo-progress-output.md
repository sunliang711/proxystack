# ipinfo 渐进式输出

## 变更摘要

- `ps-agent ipinfo` 改为在每个 IP 来源查询完成后立即输出该来源结果，不再等待 IPv4/IPv6 全部来源执行完才展示。
- 保留最终 `Summary` 汇总，现有 `query_ipinfo()` 仍返回完整 `IpInfoReport`，方便测试和库式调用复用。
- 新增 `line_callback` 渐进式输出回调，并复用同一套格式化函数，避免流式输出和最终报告格式漂移。

## 影响范围

- `src/proxystack/cli/agent.py`
- `src/proxystack/diagnostics/ipinfo.py`
- `tests/test_cli.py`
- `tests/test_ipinfo.py`

## 验证方式

- `.venv/bin/python -m pytest -q`：250 passed
