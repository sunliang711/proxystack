# member 不支持 stack 的明确错误

## 问题

`ps-agent member list/add/remove` 面向 auto/load-balance stack 设计。普通 edge stack 不支持成员管理，但此前 `list` 可能只显示空列表，`remove` 可能显示成员不存在，提示不够直接。

## 修复

- 在 `member list/add/remove` 入口统一校验目标 stack。
- 只有 `role: auto` 且包含 `url-test` 或 `load-balance` 组的 stack 支持 member 命令。
- 不支持时统一报错：`stack does not support member commands: <stack>`。
- CLI 文档补充 member 命令的目标 stack 要求。

## 验证

- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_cli.py::test_agent_member_commands_update_auto_stack tests/test_cli.py::test_agent_member_add_rejects_duplicate_and_missing_member tests/test_cli.py::test_agent_member_commands_reject_unsupported_stack -q`
- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/unit/test_task11_cli_matrix.py -q`
- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_cli.py -q`
