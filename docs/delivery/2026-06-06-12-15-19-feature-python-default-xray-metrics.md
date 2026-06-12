# 默认开启 Xray API、Stats、Policy

## 背景

`ps-agent add` 生成的 stack YAML 中没有显式包含 `xrelay.api`、`xrelay.stats` 和 `xrelay.policy`，并且 `init` 生成的全局默认配置中这些开关为关闭状态。实际使用期望是默认开启这些能力，方便后续查询 Xray stats。

## 变更

- `init` 生成的 `defaults.xrelay.api/stats/policy` 默认开启。
- 模型层 `XrelayApiConfig`、`XrelayStatsConfig`、`XrelayPolicyConfig` 缺省值默认开启。
- 示例 `tests/fixtures/example-project/config.yaml` 默认开启 API、Stats、Policy。
- 示例 stack 增加 stack 级 API 监听端口，避免多个 stack 继承同一个 `127.0.0.1:10085` 后发生端口冲突。
- 内置 `pair`、`auto-url-test`、`load-balance` 模板显式写入 `api/stats/policy` 配置块，`ps-agent add` 生成的新 stack 可直接看到并编辑。
- `add --allocate-ports` 会为启用的 `xrelay.api.listen` 自动分配本地管理端口，并避让 clash controller 端口。
- 更新 Xray golden 和配置生成文档。

## 验证

- `/tmp/proxystack-test-venv/bin/python -m pytest tests/test_xray_generator.py tests/test_cli.py -q`
- `/tmp/proxystack-test-venv/bin/python -m pytest -q`
- `/tmp/proxystack-test-venv/bin/python -m proxystack.cli.agent validate -c tests/fixtures/example-project/config.yaml --skip-system-ports`
- `/tmp/proxystack-test-venv/bin/python -m proxystack.cli.agent check -c tests/fixtures/example-project/config.yaml --skip-system-ports`
- `git diff --check`
