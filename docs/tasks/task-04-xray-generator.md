# Task 04: Xray 配置生成器

## 目标

根据已校验的 xrelay 模型生成 Xray JSON。

## 技术方案

- 新建 `src/proxystack/generator/xray`。
- 生成结构体后通过 JSON encoder 输出，避免字符串拼接。
- 使用 golden tests 固化输出。

## 实现步骤

1. 生成日志、API、Stats、Policy 和基础 inbound/outbound 容器字段；API、Stats 默认关闭。
2. 生成 vmess inbound。
3. 生成 shadowsocks inbound。
4. 生成 socks5/http inbound，支持 noauth/password。
5. 生成 clash/socks5/http/direct outbound。
6. 直接读取模型中的 `uuid`、`password` 等明文字段生成运行配置。

## 验收标准

- `examples/stacks/usa1.yaml`、`usa2.yaml`、`auto.yaml` 都能生成 JSON。
- `type: clash` outbound 能解析到目标 mihomo listener。
- 生成 JSON 可格式化且字段稳定。
- golden tests 覆盖每种 inbound 和 outbound。
- API listen 默认使用 `127.0.0.1:10085`，显式配置非 loopback 地址时校验失败。
- 开启 Stats 时生成 `stats: {}`，并默认生成四个 `policy.system` 统计开关为 `true`。

## 依赖

Task 03。

## 风险

vmess 多用户合并可以后置；首期先保证一条 inbound 一组配置正确。
