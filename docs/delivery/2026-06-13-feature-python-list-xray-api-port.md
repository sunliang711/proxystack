# ps-agent list 显示 Xray API 端口

## 变更摘要

- `ps-agent list` 新增 `Xray API` 列。
- 端口来自合并后的 `defaults.xrelay.api` 与 stack `xrelay.api` 配置；xrelay 或 API 禁用时显示 `-`。
- 保持现有表格对齐输出格式。

## 验证

- `.venv/bin/python -m pytest tests/test_cli.py::test_agent_list_outputs_aligned_table tests/test_cli.py::test_agent_list_skips_system_port_check_by_default -q`
- `.venv/bin/python -m pytest -q`
