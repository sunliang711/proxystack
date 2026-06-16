# Bug 修复：ps-sub serve Ctrl+C 停止过慢

## Bug 定位分析

- 问题现象：`ps-sub serve` 运行后使用 `Ctrl+C` 停止服务，进程退出等待时间偏长。
- 根因位置：`src/proxystack/subserver/watcher.py` 中 inotify watcher 停止时只设置 stop event，后台线程仍可能阻塞在 `select()`，需要等到 `watch_interval` 超时；`src/proxystack/cli/sub.py` 未显式限制 Uvicorn graceful shutdown 等待时间。
- 触发条件：Linux 环境优先使用 inotify watcher，服务空闲时按 `Ctrl+C` 停止。
- 修复思路：为 inotify watcher 增加非阻塞唤醒管道，`stop()` 时主动唤醒 `select()`；统一 watcher join 的短超时；给 `uvicorn.run` 设置短 graceful shutdown timeout。
- 影响评估：只影响 `ps-sub serve` 关闭流程，不改变订阅路由、配置格式、reload 行为和启动参数。

## Bug 修复摘要

- 问题：`Ctrl+C` 停止 `ps-sub serve` 太慢。
- 根因：inotify watcher 退出依赖 `select()` 超时，Uvicorn 关闭超时也未显式收紧。
- 修复方式：新增 watcher 停止唤醒管道，收紧 watcher join timeout，并传入 `timeout_graceful_shutdown=1`。
- 影响范围：`proxystack.subserver.watcher` 和 `proxystack.cli.sub.serve`。
- 验证方式：`.venv/bin/python -m pytest -q tests/test_subserver.py tests/test_cli.py::test_sub_serve_uses_config_access_and_memory_index tests/test_cli.py::test_sub_serve_rejects_duplicate_proxy_name_before_startup tests/test_cli.py::test_sub_serve_defaults_data_dir_to_config_parent tests/test_cli.py::test_sub_serve_uses_config_templates_dir tests/e2e/test_task11_main_flow.py`，结果 `21 passed, 1 skipped`。
- 回归风险：低；Linux inotify 停止速度用例在非 Linux 环境会跳过，macOS 当前验证覆盖 polling watcher 与 CLI 参数传递。
