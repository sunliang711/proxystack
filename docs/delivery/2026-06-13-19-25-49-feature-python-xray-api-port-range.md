# Xray API 独立端口池

## 背景

`add` 和 `clone --allocate-ports` 原先把 Xray API 端口从 `clash_controller` 端口池中分配，导致 Xray API 和 mihomo/clash REST controller 共用同一段端口范围。

## 变更

- 在 `port_ranges` 中新增必填配置 `xray_api_range`。
- Xray API 自动分配改为使用 `xray_api_range`。
- `clash_controller` 仅用于 mihomo/clash REST controller。
- 默认模板和测试配置补充 `xray_api_range: 10001-10999`，并使用 `clash_socks: 7001-7101`。
- 文档说明补充各端口池对应的组件。

## 验证

- `PYTHONPATH=src:. .venv/bin/pytest tests/test_config_loader.py -q`
- `PYTHONPATH=src:. .venv/bin/pytest tests/test_cli.py -k "agent_init or add_allocates_ports or clone_allocates_new_ports or native_backup_import_rejects_stack_path_outside_base_dir" -q`
- `PYTHONPATH=src:. .venv/bin/pytest tests/test_install.py tests/test_systemd.py -q`
- `PYTHONPATH=src:. .venv/bin/pytest tests/test_cli.py -q`
- `PYTHONPATH=src:. .venv/bin/pytest -q`

## 风险

旧配置缺少 `port_ranges.xray_api_range` 时会加载失败，需要显式补充该字段；这是本次需求确认后的预期行为。
