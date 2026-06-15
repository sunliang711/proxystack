# xrelay-socks5 成员管理命令

## 背景

auto/load-balance stack 支持多个 `xrelay-socks5` upstream，但此前只能在创建时通过 `add --members` 一次性生成，后续增删成员需要手动编辑 YAML，并同步维护 `clash.upstreams` 和各代理组 `proxies`。

## 变更

- 新增 `ps-agent member list <stack>`，列出 stack 中的 `xrelay-socks5` 成员。
- 新增 `ps-agent member add <stack> <member>`，默认写入 `<member>-local -> <member>.relay`。
- 新增 `ps-agent member remove <stack> <member>`，删除对应 `xrelay-socks5` upstream。
- `add/remove` 会自动同步 `url-test`、`load-balance` 组和引用这些自动组的 `select` 总组。
- 写入前校验成员 stack 存在 `relay` socks5 inbound，写入后复用现有 stack set 校验避免悬空引用。

## 影响范围

- `src/proxystack/cli/agent.py`
- `src/proxystack/cli/lifecycle.py`
- `tests/test_cli.py`
- `tests/unit/test_task11_cli_matrix.py`
- `docs/cli.md`

## 验证

- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_cli.py::test_agent_member_commands_update_auto_stack tests/test_cli.py::test_agent_member_add_rejects_duplicate_and_missing_member -q`
- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/unit/test_task11_cli_matrix.py -q`
- `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_cli.py::test_agent_add_auto_template_without_members_creates_disabled_draft tests/test_cli.py::test_agent_add_members_requires_existing_refs tests/test_cli.py::test_agent_list_outputs_aligned_table tests/test_cli.py::test_format_stack_table_keeps_disabled_component_rows tests/test_cli.py::test_agent_list_skips_system_port_check_by_default -q`
