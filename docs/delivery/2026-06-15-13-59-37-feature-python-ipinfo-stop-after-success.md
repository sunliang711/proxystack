# ipinfo 来源成功后停止查询

## 背景

`ps-agent ipinfo` 默认会按 IP family 查询多个来源：IPv4 2 个，IPv6 5 个。旧逻辑会遍历当前 family 的全部来源，即使已经解析到出口 IP，也会继续请求后续来源，导致诊断耗时偏长。

## 变更

- `query_family()` 在解析到匹配当前 family 的 IP 后立即停止后续来源查询。
- 失败响应、空响应、无法解析 IP 或返回错误 IP family 的来源仍会继续尝试下一个来源。
- 保留流式输出行为：已查询的来源仍会逐条输出，未查询的来源不再展示。

## 影响范围

- `src/proxystack/diagnostics/ipinfo.py`
- `tests/test_ipinfo.py`

## 验证

- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_ipinfo.py -q`
- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_cli.py::test_agent_ipinfo_outputs_report -q`
