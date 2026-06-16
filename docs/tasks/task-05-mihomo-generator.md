# Task 05: mihomo 配置生成器

## 目标

根据已校验的 clash 模型生成 mihomo YAML。

状态：已完成。

## 技术方案

- 新建 `src/proxystack/generator/mihomo`。
- 生成 map/struct 后通过 YAML encoder 输出。
- P0 支持一个 socks listener 和一个可选 HTTP listener；使用 mihomo 高级 listeners，支持独立 listen 和 listener users；mixed listener 预留到 P1。

## 实现步骤

1. 已生成基础字段：`mode`、`allow-lan`、`listeners`、`external-controller` 和 `secret`。
2. 已通过结构化 dict/list 和 YAML encoder 输出 mihomo YAML。
3. 已生成 raw upstream 到 `proxies`，并强制使用 upstream 名称作为 proxy `name`。
4. 已生成 `xrelay-socks5` upstream 到本机 socks5 proxy，支持 wildcard listen 归一和 password auth。
5. 已支持 clash socks/http listener 的独立 listen 和 users；xrelay clash outbound 引用带 users 的 socks listener 时使用第一个用户。
6. 已生成 `proxy-groups`，支持 select/url-test/load-balance/fallback。
7. 已生成 default rules profile、`rules.extra` 和最终 `MATCH,<final>`。
8. 已新增 `proxystack-agent render clash <stack>`，只读输出配置，不写 runtime/systemd。

## 验收标准

- auto 示例生成的 proxies 包含 `usa1-local` 和 `usa2-local`。
- `url-test` 和 `load-balance` 组输出正确。
- `render clash auto` 能展示最终 YAML。
- golden tests 覆盖 raw、xrelay-socks5、rules 和 groups。
- P0 遇到 `listeners.mixed` 时校验失败，不能静默忽略或生成 `mixed-port`。

## 交付内容

- 新增 `src/proxystack/generator/mihomo/`。
- 新增 `tests/test_mihomo_generator.py` 和 `tests/golden/mihomo/*.yaml`。
- 更新 `proxystack-agent render clash <stack>`。

## 依赖

Task 03。

## 风险

mihomo 配置项很多，首期要收敛范围，避免把完整 mihomo schema 复制进项目。
