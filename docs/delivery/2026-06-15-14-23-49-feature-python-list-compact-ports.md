# list 紧凑端口展示

## 背景

`ps-agent list` 的 `Endpoints` 列同时展示业务入口和管理端点，节点较多时输出过密，不利于快速查看 stack 状态。

## 变更

- 默认 `ps-agent list` 将 `Endpoints` 列改为 `Ports`，只展示 xrelay inbound 和 clash socks/http 端口。
- 新增 `ps-agent list --verbose` / `-v`，用于展示 xrelay API 和 clash controller 等完整端点。
- 每个 stack 的组件行之间保持紧凑，不同 stack 之间增加空行分隔。

## 影响范围

- `src/proxystack/cli/agent.py`
- `tests/test_cli.py`

## 验证

- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_cli.py::test_agent_list_outputs_aligned_table tests/test_cli.py::test_format_stack_table_keeps_disabled_component_rows tests/test_cli.py::test_agent_list_skips_system_port_check_by_default -q`
- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/unit/test_task11_cli_matrix.py -q`
