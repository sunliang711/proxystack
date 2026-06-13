# ps-sub 订阅地区分组

## 变更摘要

- 订阅节点 schema 新增可选 `region` 字段，格式为两位大写国家/地区简称，不限制固定枚举。
- stack inbound 和 vmess/shadowsocks `users[]` 支持配置 `region`，多用户订阅节点优先使用 `users[].region`，未配置时继承 inbound 的 `region`。
- Surge 模板上下文新增 `surge_region_groups`，默认模板在 `[Proxy Group]` 输出带 emoji 和 `icon-url` 的常用地区组、`OtherRegion`、`ProxyList` 和 `FinalList`，同时保持服务端直接列出全部节点，不再依赖 `MySub`。
- 默认 stack 模板和文档补充 `region` 字段来源、订阅 input 示例和 Surge 地区分组规则。
- Surge 默认业务组同步为链接中的 `OpenAI`、`Claude`、`Cursor`、`Google`、`Meta`、`Apple`、`Microsoft` 等分组名称，并补齐对应 `icon-url`。
- `/surge_sub/:user` HTTP 响应第一行新增 `#!MANAGED-CONFIG` 托管配置头；默认 `interval=86400`、`strict=true`，反向代理部署可通过 `managed_config.public_base_url` 指定公网前缀。
- Premium Clash 默认 `proxy-groups` 与 Surge `[Proxy Group]` 的组名和数量保持一致，图标字段使用 `icon`；业务组、图标、`rule-providers` 和 `rules` 显式写在模板中，`rule-providers` URL 改为 R2 的 `/clash/*.yaml` 规则源。

## 验证

- `.venv/bin/python -m pytest tests/test_subserver.py tests/test_cli.py::test_sub_config_creates_default_config tests/test_cli.py::test_sub_default_config_falls_back_when_builtin_template_missing tests/test_cli.py::test_sub_config_rejects_invalid_managed_config_public_base_url tests/golden/test_subscription_golden.py tests/test_sub_generator.py -q`，结果：54 passed。
- `.venv/bin/python -m pytest tests/test_sub_generator.py tests/golden/test_subscription_golden.py -q`，结果：35 passed。
- R2 `/clash/*.yaml` rule provider URL 抽检 31 个，结果：failed=0。
- `git diff --check`，结果：通过。
- `.venv/bin/python -m pytest -q`，结果：311 passed。
