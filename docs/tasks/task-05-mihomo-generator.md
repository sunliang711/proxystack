# Task 05: mihomo 配置生成器

## 目标

根据已校验的 clash 模型生成 mihomo YAML。

## 技术方案

- 新建 `src/proxystack/generator/mihomo`。
- 生成 map/struct 后通过 YAML encoder 输出。
- P0 只支持一个 socks listener；mixed listener 预留到 P1。

## 实现步骤

1. 生成基础字段：`mode`、`allow-lan`、`bind-address`、`external-controller`。
2. 生成 `socks-port`。
3. 生成 raw upstream 到 `proxies`。
4. 生成 `xrelay-socks5` upstream 到本机 socks5 proxy。
5. 生成 `proxy-groups`，支持 select/url-test/load-balance/fallback。
6. 生成 default rules profile 和 `rules.extra`。

## 验收标准

- auto 示例生成的 proxies 包含 `usa1-local` 和 `usa2-local`。
- `url-test` 和 `load-balance` 组输出正确。
- `render clash auto` 能展示最终 YAML。
- golden tests 覆盖 raw、xrelay-socks5、rules 和 groups。
- P0 遇到 `listeners.mixed` 时校验失败，不能静默忽略或生成 `mixed-port`。

## 依赖

Task 03。

## 风险

mihomo 配置项很多，首期要收敛范围，避免把完整 mihomo schema 复制进项目。
