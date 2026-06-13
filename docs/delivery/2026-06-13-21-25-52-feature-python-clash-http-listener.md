# Clash HTTP Listener

## 背景

stack 运行用的 mihomo/clash 配置原先只生成 `socks-port`，本机 HTTP 代理客户端没有独立入口；不希望用 `mixed-port` 替换现有 socks 入口，以免影响 xray 到 clash 的内部 socks 链路。

## 变更

- 在 `port_ranges` 中新增必填配置 `clash_http`，默认范围为 `7201-7301`。
- 在 `clash.listeners` 中新增可选 `http` listener，P0 最多允许一个。
- `listeners.socks` 继续生成 `socks-port`，`listeners.http` 生成 mihomo HTTP 代理 `port`。
- 同时配置 socks 和 HTTP listener 时，两者必须使用相同 `listen`，因为 mihomo 基础端口共享 `bind-address`。
- `listeners.mixed` 仍然不支持，不使用 `mixed-port` 替换 `socks-port`。
- `add` 和 `clone --allocate-ports` 会从 `clash_http` 端口池分配 HTTP listener 端口。
- `proxystack-agent list` 新增 `Clash HTTP` 列。
- 更新默认配置模板、stack 模板、示例 fixture、mihomo golden、配置文档和生成文档。

## 验证

- `PYTHONPATH=src:. .venv/bin/pytest tests/test_config_loader.py tests/test_mihomo_generator.py tests/test_xray_generator.py tests/test_cli.py -q`
- `PYTHONPATH=src:. .venv/bin/pytest tests/test_install.py tests/test_systemd.py tests/test_ipinfo.py -q`
- `PYTHONPATH=src:. .venv/bin/pytest -q`

## 风险

旧配置缺少 `port_ranges.clash_http` 时会加载失败，需要显式补充该字段；这是本次新增独立 HTTP listener 后的预期行为。
