# SS2022 订阅节点无法连接修复记录

## 问题

测试机 `10.2.86.151` 上，从订阅获取的 SS2022 节点导入 mihomo 后无法连接。

## 根因

`proxystack` 生成 Xray Shadowsocks 多用户 inbound 时使用了 `settings.users`。远端 Xray 26.3.27 在 SS2022 场景下没有按该字段进入多用户模式，导致服务端实际只接受顶层 ServerPassword；而订阅侧按 SS2022 多用户规则输出 `ServerPassword:UserPassword`，客户端连接时认证失败。

实测将 Xray 服务端字段改为 `settings.clients` 后，`ServerPassword:UserPassword` 可以连通，Xray 日志能识别到用户 email。

## 修复

- 将 `src/proxystack/generator/xray/config.py` 中 Shadowsocks 多用户输出字段从 `users` 改为 `clients`。
- 更新 `tests/test_xray_generator.py` 中传统 Shadowsocks 和 SS2022 多用户的期望字段。

## 验证

- 本地执行：`.venv/bin/pytest tests/test_xray_generator.py tests/test_sub_generator.py -q`
- 结果：`51 passed`
- 远端执行：重新安装 `/root/proxystack` 到 `/opt/proxystack/.venv`，并执行 `proxystack-agent restart usa1 --config /opt/proxystack/config.yaml`
- 远端生成结果：`/opt/proxystack/runtime/generated/xray/usa1.json` 的 SS2022 inbound 使用 `settings.clients`，不再包含 `settings.users`
- 远端订阅验证：`/sub/eagle` 返回 1 个 SS2022 节点，密码形态保留 `ServerPassword:UserPassword`
- 远端连通验证：使用真实订阅节点启动临时 mihomo，经 SOCKS 请求 `https://ifconfig.io/ip` 返回 OK；Xray 日志显示 `email: eagle`

## 影响范围

只影响 Xray Shadowsocks 多用户运行配置生成。Proxystack 输入配置仍使用 `users` 字段，订阅输出仍按 SS2022 多用户规则输出 `ServerPassword:UserPassword`。
