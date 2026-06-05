# Task 04 交付记录：Xray 配置生成器

## 变更摘要

- 新增 `src/proxystack/generator/xray/`，通过 dict/list 结构和 JSON encoder 生成 Xray 配置。
- 支持 Xray `vmess`、`shadowsocks`、`socks5`、`http` inbound，其中 socks/http 支持 noauth/password。
- 支持 xrelay outbound `clash`、`socks5`、`http`、`direct`，其中 `clash` 通过引用图解析 mihomo socks listener。
- 支持生成 Xray API、Stats 和 Policy；API/Stats 默认关闭，开启 Stats 时默认生成四个 `policy.system` 统计开关。
- 新增 `proxystack-agent render xrelay <name>`，只读输出指定 stack 的 Xray JSON。
- 新增 Xray golden tests，覆盖示例 stack、每种 inbound/outbound 类型和 wildcard listener loopback 归一。

## 边界

- 仅生成只读 Xray JSON，不生成 manifest、systemd、apply、mihomo 或订阅配置。
- API listen 仅允许 loopback 地址，避免生成公网 API。
- 禁用 stack 或 `xrelay.enabled: false` 时，render 会失败并提示不生成 Xray JSON。

## 验证命令

```bash
make test PYTHON=.venv/bin/python
make lint PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
.venv/bin/proxystack-agent render xrelay usa1 -c examples/config.yaml
.venv/bin/proxystack-agent render xrelay usa1 -c examples/config.yaml | python -m json.tool
```

## 风险与后续

- vmess 仍按首期设计一条 inbound 一组配置，暂不合并同端口多用户。
- API 使用 Xray 简化 listen 模式，暂不额外生成 API inbound/routing。
- Xray 协议字段以当前 P0 文档和示例为准，后续接入真实 xray-core 启动校验时可继续收紧。
