# mihomo 高级 listener 认证支持

## 变更摘要

- `clash.listeners.socks/http` 支持 mihomo 原生 `users` 数组配置，保留未配置、空数组和多用户三种语义。
- mihomo 生成器改为输出高级 `listeners`，不再为 stack 运行配置输出基础 `socks-port` / `port` / `bind-address`。
- socks 和 HTTP listener 支持独立 `listen`。
- xrelay 的 `outbound.type: clash` 引用带认证的 socks listener 时，会使用第一个 `users` 账号生成 Xray socks outbound。
- 同步更新配置模板、配置规范、生成文档、任务说明和相关 golden。

## 验证

- `PYTHONPATH=src:. .venv/bin/pytest tests/test_config_loader.py::test_reference_graph_indexes_clash_listener_users tests/test_mihomo_generator.py tests/test_xray_generator.py -q`
- `PYTHONPATH=src:. .venv/bin/pytest tests/test_cli.py tests/test_config_loader.py tests/test_mihomo_generator.py tests/test_xray_generator.py tests/e2e tests/unit -q`
- `PYTHONPATH=src:. .venv/bin/pytest -q`

## 风险

- 运行用 mihomo 配置的 listener 输出形态从基础端口切换为高级 `listeners`，部署环境需要使用支持高级 listeners 的 mihomo 版本。
- 未配置 `users` 时会跟随 mihomo 全局 `authentication`；当前 proxystack 未新增全局 `authentication` 配置，默认仍等价于不认证。
