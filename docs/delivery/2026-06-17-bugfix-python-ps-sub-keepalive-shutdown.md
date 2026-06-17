# Bug 修复：ps-sub serve Ctrl+C 关闭等待

## Bug 定位分析

- 问题现象：`ps-sub serve` 运行后使用 `Ctrl+C` 停止服务时，部分环境退出等待时间仍偏长。
- 根因位置：`src/proxystack/cli/sub.py` 中 `uvicorn.run` 已限制 graceful shutdown，但未显式覆盖 Uvicorn 默认 `timeout_keep_alive=5`。
- 触发条件：服务存在订阅客户端访问后的 keep-alive 连接，或运行环境对 Uvicorn 默认关闭等待更敏感时触发。
- 修复思路：在 `ps-sub serve` 启动 Uvicorn 时同步传入短 keep-alive 超时，使 Ctrl+C 后连接等待上限与 graceful shutdown 保持一致。
- 影响评估：只影响 `ps-sub serve` 的 HTTP 连接关闭等待，不改变订阅路由、配置格式、watcher reload 和鉴权行为。

## Bug 修复摘要

- 问题：`Ctrl+C` 停止 `ps-sub serve` 仍可能等待较久。
- 根因：Uvicorn keep-alive 超时仍使用默认 5 秒。
- 修复方式：新增 `UVICORN_KEEP_ALIVE_TIMEOUT = 1`，并传给 `uvicorn.run(timeout_keep_alive=...)`。
- 影响范围：`src/proxystack/cli/sub.py`、`tests/test_cli.py`、`tests/e2e/test_task11_main_flow.py`。
- 验证方式：`PYTHONPATH=src:. .venv/bin/python -m pytest -q tests/test_subserver.py tests/test_cli.py::test_sub_serve_uses_config_access_and_memory_index tests/test_cli.py::test_sub_serve_rejects_duplicate_proxy_name_before_startup tests/test_cli.py::test_sub_serve_defaults_data_dir_to_config_parent tests/test_cli.py::test_sub_serve_uses_config_templates_dir tests/e2e/test_task11_main_flow.py`，结果 `22 passed, 1 skipped`。
- 手工验证：本地真实启动 `ps-sub serve`，保持 `/health` keep-alive 连接后发送 `SIGINT`，退出耗时约 `0.28s`。
- 回归风险：低；变更仅收紧服务关闭阶段的空闲连接等待时间。
