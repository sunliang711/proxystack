# sub export 输出 external_host

## 变更摘要

- `ps-agent sub export` 和 `ps-agent sub export --summary` 的摘要行新增 `external_host=<value>`。
- 输出值来自当前 agent `config.yaml` 的 `external_host`，用于提醒发布前确认订阅默认 server。
- 不改变发布包内容和订阅节点生成规则。

## 验证

- `.venv/bin/python -m pytest tests/test_cli.py::test_agent_sub_export_all_stacks_bundle tests/test_cli.py::test_agent_sub_export_summary_does_not_write_bundle -q`
- `.venv/bin/python -m pytest -q`
