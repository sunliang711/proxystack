# proxystack

`proxystack` 是一个从零开始的新项目，用 `/opt/proxystack/config.yaml` 管理全局配置，用 `/opt/proxystack/stacks/<name>.yaml` 为每组 `xrelay -> clash/mihomo` stack 单独建配置文件，并生成 Xray 配置、mihomo 配置和订阅输出。

项目目标是解决旧方案里需要重复配置端口和上下游关系的问题：新增一组 stack 时，用户只在 `stacks/<name>.yaml` 中声明一次监听端口、入站协议、订阅暴露和上下游引用，工具负责把它编译成各组件真正需要的配置文件。

## 核心设计

- xrelay 负责启动 Xray，向客户端暴露 `vmess`、`shadowsocks`、`socks5`、`http` 等 inbound。
- clash 负责启动 mihomo，连接真实上游节点或本机其他 xrelay inbound，并提供给 xrelay 的 outbound 使用。
- subscription 只读取 xrelay 的 `inbounds` 中 `sub: true` 的条目生成订阅，不读取 clash 的代理组、规则或节点信息。
- auto 场景通过 mihomo 的 `url-test` 或 `load-balance` 组实现，P0 下游节点引用其他 xrelay 暴露的本地 socks5 inbound。
- `inbounds[].sub` 是唯一的订阅暴露开关。

## 文档入口

- [整体架构](docs/architecture.md)
- [统一配置规范](docs/config-spec.md)
- [配置生成规则](docs/generation.md)
- [CLI 与服务管理](docs/cli.md)
- [部署方案](docs/deployment.md)
- [编码规范](docs/conventions.md)
- [参考项目](docs/reference-projects.md)
- [开发进度](docs/PROGRESS.md)
- [全局配置初始化模板](src/proxystack/templates/agent-config.yaml)
- [测试 stack fixture](tests/fixtures/example-project/stacks/usa1.yaml)
- [add 默认模板](src/proxystack/templates/stack.pair.yaml)

## 建议技术栈

首期建议使用 Python 实现同一项目内的两个运行组件：

- `proxystack-agent`：本地运行，负责 stack 配置、Xray/mihomo 配置生成、systemd 管理、安装更新和订阅发布包导出。
- `proxystack-sub`：订阅服务，只消费订阅输入/发布包，支持像 `clashsub` 的 `inputs` 目录一样合并多个输入文件生成订阅；同一批输入文件也可以直接给 `proxystack-agent` 校验、合并和重新导出；支持本地部署和 Docker 部署。

建议技术栈：

- CLI: Typer
- 配置模型与校验: Pydantic v2
- YAML: ruamel.yaml
- 模板: Jinja2
- HTTP 订阅服务: FastAPI + Uvicorn
- HTTP 客户端/下载: httpx
- 日志: logging 结构化封装
- 测试: pytest

不重写代理核心。项目只编排、下载、配置和管理 `mihomo` 与 `xray-core`，不会自行实现 socks/http/vmess/shadowsocks 协议栈。
