# mihomo 高级 listener 名称去重修复

## 问题

远端 `sudo ps-agent ipinfo de1` 使用 `socks5://127.0.0.1:6005` 查询出口 IP 时连接失败。`proxystack-clash@de1.service` 处于 running 状态，但 `ss -ltnp` 显示 mihomo 未监听 `6005`，只监听了 HTTP 和 controller 端口。

## 根因

de1 使用 mihomo 高级 `listeners` 配置后，socks 和 HTTP listener 都生成了相同的 `name: local`。mihomo 对同名高级 listener 只保留或启动了其中一个，导致 socks listener 未实际监听。

## 修复

- mihomo 生成器在输出高级 `listeners` 时对 listener 名称做去重。
- 同名时保留第一个名称，后续 listener 自动追加协议后缀，例如 `local-http`。
- stack 模板中的 HTTP listener 默认名改为 `local-http`，避免新配置继续生成同名 listener。

## 验证

- 远端临时修复 de1 HTTP listener 名称并重启后，mihomo 已监听 `127.0.0.1:6005`。
- `sudo ps-agent ipinfo de1` IPv4 查询成功。
- 本地执行 `PYTHONPATH=src:. .venv/bin/pytest tests/test_mihomo_generator.py -q` 通过。
- 本地执行 `PYTHONPATH=src:. .venv/bin/pytest -q` 通过。
