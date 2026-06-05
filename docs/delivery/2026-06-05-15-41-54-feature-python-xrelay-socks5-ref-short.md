# xrelay-socks5 ref 简写交付记录

## 变更摘要

- 将 `clash.upstreams[].type: xrelay-socks5` 的 `ref` 从四段格式改为两段格式：`<stack>.<inbound_name>`。
- 更新 `examples/stacks/auto.yaml`、根目录模板和包内模板，统一使用 `usa1.relay`、`usa2.relay`。
- 更新配置规范、生成规则、架构说明和 Task 03 验收描述。
- 补充测试覆盖两段 ref 可用，以及旧四段 ref 不再接受。

## 验证结果

- `make test PYTHON=.venv/bin/python`：19 passed
- `make lint PYTHON=.venv/bin/python`：通过
- `make build PYTHON=.venv/bin/python`：通过，构建产物已清理
- `.venv/bin/proxystack-agent validate -c examples/config.yaml`：通过
