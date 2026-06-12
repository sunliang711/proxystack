# Task 05 交付记录：mihomo 配置生成器

## 变更摘要

- 新增 `src/proxystack/generator/mihomo/`，通过 dict/list 结构和 `ruamel.yaml` encoder 生成 mihomo YAML。
- 导出 `render_mihomo_config(stack_set, stack_name)`、`dumps_mihomo_config(...)` 和 `MihomoGeneratorError`。
- 支持仅对启用 stack 且 `clash.enabled: true` 的配置生成 YAML；禁用 stack 或 clash 时直接报错。
- 支持基础字段、唯一 socks listener、raw upstream、`xrelay-socks5` upstream、proxy groups 和 default rules profile。
- 新增 `proxystack-agent render clash <stack>`，只读输出 mihomo YAML，不写 runtime、manifest 或 systemd。
- 新增 mihomo golden tests，覆盖 examples 中的 `usa1`、`usa2`、`auto`，并覆盖 raw、xrelay-socks5、groups、rules、禁用错误和 `listeners.mixed` 校验。

## 边界

- P0 只支持一个 socks listener，不生成 `mixed-port` 或高级 mihomo listeners。
- `xrelay-socks5` 只解析两段 `<stack>.<inbound>` ref，并要求目标 inbound 协议为 socks5。
- default rules profile 按 `rules.extra`、内置默认规则、`MATCH,<rules.final>` 的顺序生成。
- 当前命令仅 render，不负责 apply、manifest、runtime 写入、systemd 管理或 mihomo 进程启动校验。

## 验证命令

```bash
make test PYTHON=.venv/bin/python
make lint PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
.venv/bin/proxystack-agent render clash auto -c tests/fixtures/example-project/config.yaml --skip-system-ports
```

## 风险与后续

- mihomo schema 很大，当前仅覆盖 P0 文档内字段；真实 mihomo 启动校验可在 apply/systemd 阶段补充。
- fallback 组会保留用户配置的 `url`、`interval`，但模型层当前未强制 fallback 必填健康检查字段。
- raw upstream 凭据按已校验模型原样输出，后续如需要脱敏展示，应在展示层单独处理。
