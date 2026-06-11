# xrelay vmess 多用户支持

## 背景

xrelay vmess inbound 原先只支持顶层单用户 `uuid/user/remark` 字段，Xray 生成器只能输出一个 `settings.clients` 项，订阅生成也只能导出一个节点。

## 变更

- `Inbound` 新增 vmess `users` 结构，单用户也通过一条 `users` 记录表达。
- vmess 校验要求非空 `users`，不再支持顶层 `uuid`；顶层 `user` 和 `remark` 也不用于 vmess。每个用户 UUID 必须合法；`users` 只能用于 vmess，同一 inbound 内 `user`、`uuid`、最终订阅 tag 不允许重复。
- Xray vmess 多用户仍生成一个 inbound，并把 `users` 展开为多个 `settings.clients`；多用户 client 写入 `email` 便于 Xray 用户统计。
- 订阅生成将 vmess `users` 展开为多个节点，节点 id 使用 `<stack>:<inbound>:<user>`。
- 更新 `docs/config-spec.md` 和 `docs/generation.md` 中的配置与生成规则。

## 测试

- `.venv/bin/python -m pytest tests/test_config_loader.py tests/test_xray_generator.py tests/test_sub_generator.py tests/test_cli.py::test_agent_add_allocates_ports_by_default_for_multiple_stacks tests/e2e/test_task11_main_flow.py -q`：85 passed
- `.venv/bin/python -m pytest -q`：262 passed
