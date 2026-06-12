# prefix-source 使用横杠连接

## 变更摘要

- 将 `subscription.remark_policy: prefix-source` 的默认输出从 `{source} {remark}` 改为 `{source}-{remark}`。
- 更新订阅生成测试、CLI 摘要测试和文档说明。

## 保持不变的行为

- `preserve` 策略仍保留旧命名规则。
- `template` 策略仍可通过 `remark_template` 自定义任意分隔符。

## 验证结果

- `PYTHONPATH=src /tmp/proxystack-test-venv/bin/python -m pytest -q tests/test_sub_generator.py tests/test_cli.py::test_agent_sub_export_summary_does_not_write_bundle tests/test_config_loader.py::test_load_config_accepts_subscription_remark_template tests/test_config_loader.py::test_load_config_rejects_unknown_subscription_remark_template_field`：33 passed
- `PYTHONPATH=src /tmp/proxystack-test-venv/bin/python -m pytest -q`：299 passed
- `git diff --check`：通过
