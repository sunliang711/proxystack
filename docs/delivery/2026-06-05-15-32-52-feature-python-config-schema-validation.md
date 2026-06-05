# Task 02 配置模型与校验交付记录

## 变更摘要

- 新增 `src/proxystack/domain` 领域模型，覆盖全局配置、stack、xrelay、clash、inbound、outbound、upstream、group、rules 和端口池。
- 新增跨 stack 校验，覆盖文件名与 stack name 一致、stack name 唯一、公开 socks/http 鉴权、全局监听端口唯一和系统端口占用。
- 扩展配置加载入口，新增 `load_config`、`load_stack`、`load_stacks`。
- 扩展 `proxystack-agent validate`，支持 `-c/--config` 和 `--skip-system-ports`。
- 补充配置模型、非法配置和 CLI validate 测试。

## 验证结果

- `make test PYTHON=.venv/bin/python`：17 passed
- `make lint PYTHON=.venv/bin/python`：通过
- `make build PYTHON=.venv/bin/python`：通过
- `.venv/bin/proxystack-agent validate -c examples/config.yaml --skip-system-ports`：通过
