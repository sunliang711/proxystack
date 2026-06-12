# Task 04 扩展交付记录：Xray API、Stats、Policy

## 变更摘要

- 在 `defaults.xrelay` 和单个 stack 的 `xrelay` 下支持 `api`、`stats`、`policy` 配置。
- API 默认关闭；开启时默认生成 `tag: api`、`listen: 127.0.0.1:10085`、`services: [StatsService]`。
- Stats 默认关闭；开启时生成 `stats: {}`。
- Policy 支持 `system.statsInboundUplink`、`statsInboundDownlink`、`statsOutboundUplink`、`statsOutboundDownlink`。
- 开启 Stats 时默认将四个 `policy.system` 统计开关渲染为 `true`，显式配置值可覆盖。
- API listen 在模型校验阶段限制为 loopback host，避免生成公网 API。

## 参考

- Project X API：`https://xtls.github.io/en/config/api.html`
- Project X Stats：`https://xtls.github.io/en/config/stats.html`
- Project X Policy：`https://xtls.github.io/en/config/policy.html`

## 验证命令

```bash
make test PYTHON=.venv/bin/python
make lint PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
.venv/bin/proxystack-agent render xrelay usa1 -c tests/fixtures/example-project/config.yaml --skip-system-ports | .venv/bin/python -m json.tool
```

## 风险与后续

- API 采用 Xray 简化 listen 配置，不额外生成 API inbound/routing。
- 当前仅支持系统级全局流量统计开关，用户级统计字段后续可按需求扩展。
