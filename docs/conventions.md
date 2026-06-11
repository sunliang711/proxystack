# 编码规范

## 1. 规则来源

本项目使用 Python，编码规范基于：

- `/Users/eagle/.codex/ai-rules-skills/rules/00-global.md`
- `/Users/eagle/.codex/ai-rules-skills/rules/10-python-backend.md`
- `/Users/eagle/.codex/ai-rules-skills/rules/11-python-security.md`
- `/Users/eagle/.codex/ai-rules-skills/rules/12-python-api-design.md`

## 2. 项目结构

```text
pyproject.toml
src/proxystack/
  cli/
  config/
  domain/
  graph/
  generator/
    xray/
    mihomo/
    sub/
  install/
  systemd/
  subserver/
  mihomoapi/
  templates/
tests/
  golden/
  fixtures/
examples/
  config.yaml
  stacks/
    usa1.yaml
```

约束：

- console scripts 只负责命令入口和依赖装配，不放业务逻辑。
- CLI 层只做参数接收、校验入口和响应展示。
- Service 层承载业务流程、文件写入、外部调用编排。
- Adapter 层封装 systemd、下载器、文件系统和 mihomo API。
- Pydantic Schema 与运行时生成模型分离，避免把外部输入模型直接传到所有内部模块。
- 配置加载统一在 `src/proxystack/config`，业务代码不散落调用 `os.getenv()` 读取核心配置。
- 本地运行目录默认统一在 `/opt/proxystack`，代码中不得硬编码其他配置或运行目录。
- 内置 stack 模板只维护在 `src/proxystack/templates`，运行时代码通过包内资源读取，避免多处模板分叉。

## 3. 依赖和日志

- CLI 使用 Typer。
- HTTP 订阅服务使用 FastAPI + Uvicorn。
- 配置模型和输入校验使用 Pydantic v2。
- YAML 使用 ruamel.yaml；只读场景也可封装 PyYAML safe_load，但禁止 `yaml.load`。
- 模板使用 Jinja2。
- 下载和 HTTP 调用使用 httpx。
- 日志使用 Python `logging` 的结构化封装，生产代码禁止 `print()`。
- 测试使用 pytest。
- 新增同类替代依赖前必须说明理由。

## 4. 注释要求

本项目后续写代码时：

- 每个函数/方法必须有注释，说明功能和适用场景。
- 复杂分支、异常处理、副作用、并发、权限和外部调用必须补充必要注释。
- 注释保持简洁，不重复描述代码本身。

## 5. 安全约定

- 凭据直接使用明文字段，例如 `uuid`、`password`、`secret`、`token`；P0 不使用外部凭据引用。
- 订阅发布包可以包含客户端连接所需凭据，例如 vmess uuid、shadowsocks password、socks/http auth。
- `sub-bundle.zip` 不包含完整 stack、clash upstream、rules、mode、controller 配置或本地运行路径。
- socks/http 非回环监听必须开启鉴权，除非用户显式传入危险确认。
- 订阅 HTTP 默认需要 token 访问控制；`none` 只允许本地监听或显式风险确认。
- 管理 HTTP API 默认不开启；开启时必须有鉴权和监听地址限制。
- 所有外部输入都必须通过 Pydantic 或白名单规则校验，包括 YAML、CLI 参数、HTTP path/query/body。
- 执行 systemctl、journalctl、curl 等外部命令时，必须使用参数数组调用，禁止把用户输入拼接进 shell 字符串。
- 文件路径必须做路径穿越校验，尤其是 import/export、bundle 解包和模板路径。

## 6. 测试约定

- 单元测试优先使用 pytest fixture、mock 和 fake。
- 配置生成器必须有 golden tests。
- Pydantic 校验必须覆盖端口冲突、ref 缺失、类型不匹配、rules 目标不存在、危险 socks/http 暴露。
- systemd 和下载器通过接口抽象，单元测试使用 fake 实现，不调用真实 systemctl。
- HTTP 订阅服务使用 FastAPI TestClient 覆盖路由和响应。
- 发布包导入测试必须覆盖 hash 校验失败、zip 路径穿越和原子切换失败。

## 7. 日志字段

推荐字段：

- `instance`
- `component`：`xrelay`、`clash`、`sub`
- `service`
- `file`
- `operation`
- `duration_ms`
- `changed`
- `bundle_version`

日志 message 使用英文，面向用户的 CLI 文案使用中文。
