# Inbound 共享地区与固定订阅节点名

## 背景

原先 `users[].region` 和 `inbound.region` 都可以参与订阅分组，容易出现同一个 inbound 下用户地区不一致的问题；订阅节点名也支持策略配置，命名规则不够统一。

## 变更

- 移除 `users[].region` 配置支持，地区统一从 `inbound.region` 读取。
- 多用户节点生成时统一使用 inbound 级别的 `region`。
- 订阅节点名固定生成为 `{user}@{stack_name}-{protocol}:{port}-{remark}`。
- `remark` 缺失时使用 inbound 的 `name` 作为节点名备注片段。
- 移除 `subscription.remark_policy` 和 `subscription.remark_template` 配置说明与模板。
- 更新配置文档、生成文档、stack 模板和测试断言。

## 验证

- `PYTHONPATH=src:. .venv/bin/pytest tests/test_config_loader.py tests/test_sub_generator.py -q`
- `PYTHONPATH=src:. .venv/bin/pytest tests/test_cli.py -q`
- `PYTHONPATH=src:. .venv/bin/pytest -q`

## 风险

旧配置中如果仍保留 `users[].region`、`subscription.remark_policy` 或 `subscription.remark_template` 会加载失败；这是本次需求确认后的预期行为。
