# ps-sub 配置来源收敛

## 变更摘要

- 从 agent 全局 `subscription` 模型和模板中移除 `listen`、`access` 字段。
- `ps-agent init/setup` 生成 `sub/config.yaml` 时只使用 `src/proxystack/templates/sub-config.yaml`，不再由 agent 配置覆盖监听地址和访问控制。
- agent 生成本地订阅 index 时默认 `access.type: none`；真实 HTTP 鉴权只由 `sub/config.yaml` 控制。
- agent 端口校验不再检查订阅服务端口，避免依赖独立的 ps-sub 运行配置。

## 验证

- `.venv/bin/python -m pytest tests/test_config_loader.py tests/test_cli.py tests/test_systemd.py tests/test_sub_generator.py tests/e2e/test_task11_main_flow.py tests/unit/test_task11_config_matrix.py -q`
- `.venv/bin/python -m pytest -q`
