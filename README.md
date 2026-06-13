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

## 安装

### 开发环境安装

项目要求 Python 3.9+。在仓库根目录创建虚拟环境并以可编辑模式安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

安装后可以验证两个命令入口：

```bash
ps-agent version
ps-sub version
make test
```

`ps-agent` 是 `proxystack-agent` 的短命令别名，`ps-sub` 是 `proxystack-sub` 的短命令别名。

### 生产环境首次安装

Linux/systemd 环境建议使用仓库内安装脚本完成 bootstrap，再由 `ps-agent setup` 补齐运行依赖和 systemd unit。安装脚本负责创建 `/opt/proxystack`、系统用户、Python venv 和 CLI 链接；mihomo、xray-core、geo 数据与 systemd unit 由 `ps-agent setup` 显式安装。

```bash
sudo scripts/install-agent.sh
sudo ps-agent setup
sudo ps-agent doctor
```

默认安装后的主要目录如下：

```text
/opt/proxystack/
  .venv/
  bin/
  config.yaml
  stacks/
  runtime/
  publish/
  downloads/
  sub/
```

如需自定义源码目录、安装目录或 CLI 链接目录，可使用：

```bash
sudo scripts/install-agent.sh \
  --source /path/to/proxystack \
  --base-dir /opt/proxystack \
  --bin-dir /usr/local/bin
```

更多脚本参数见 [部署脚本说明](scripts/README.md)。

## 部署

### 本地部署 agent

`proxystack-agent` 运行在代理机器上，负责管理 stack 配置、生成 Xray/mihomo 配置、安装代理核心、管理 systemd 服务并导出订阅发布包。

首次部署常用流程：

```bash
sudo ps-agent setup
sudo ps-agent doctor
sudo ps-agent config
sudo ps-agent add usa1
sudo ps-agent config usa1
sudo ps-agent check usa1
sudo ps-agent start usa1
sudo ps-agent status usa1
```

关键配置文件：

- `/opt/proxystack/config.yaml`：全局路径、默认端口池、订阅地址、安装源和安全策略。
- `/opt/proxystack/stacks/<name>.yaml`：单个 `xrelay -> clash/mihomo` stack 的监听端口、上游节点、订阅暴露和规则。

修改配置后建议先执行 `ps-agent check [name]` 预览生成变化，再执行 `ps-agent start [name]` 或 `ps-agent restart [name]` 应用。

### 本地部署订阅服务

订阅服务可以和 agent 部署在同一台机器上，共用 `/opt/proxystack`，但只读写 `/opt/proxystack/sub`。

```bash
sudo ps-agent sub export
sudo scripts/install-sub-local.sh \
  --import-bundle /opt/proxystack/publish/sub-bundle.zip \
  --install-systemd \
  --start
```

后续更新订阅内容：

```bash
sudo ps-agent sub export
sudo ps-sub import /opt/proxystack/publish/sub-bundle.zip --data-dir /opt/proxystack/sub
sudo ps-agent restart sub
```

### Docker 部署订阅服务

远端订阅服务器可以只部署 `proxystack-sub`，不需要 mihomo、xray-core 或完整 stack 配置。先准备订阅服务配置和数据目录：

```bash
sudo install -d -m 0750 /opt/proxystack/sub
sudo cp src/proxystack/templates/sub-config.yaml /opt/proxystack/sub/config.yaml
sudo vi /opt/proxystack/sub/config.yaml
```

Docker 场景下，`/opt/proxystack/sub` 会挂载为容器内 `/data`，因此配置中至少需要确认 `listen: 0.0.0.0:3003`，并将 `data_dir` 改为 `/data` 或删除该字段使用默认值。

然后构建并启动容器：

```bash
docker compose -f docker-compose.sub.yml up -d --build
```

导入发布包：

```bash
docker cp /opt/proxystack/publish/sub-bundle.zip proxystack-sub:/tmp/sub-bundle.zip
docker exec proxystack-sub ps-sub import /tmp/sub-bundle.zip --data-dir /data
```

如果公网暴露订阅服务，建议在反向代理层配置 HTTPS、访问控制、限流和日志。完整部署细节见 [部署方案](docs/deployment.md)。

### 卸载

本地部署使用 `scripts/uninstall-local.sh` 卸载服务。默认会停止并禁用服务、删除 systemd unit 和 CLI 链接，保留 `/opt/proxystack` 下的配置、stack、运行数据以及对应系统用户/组：

```bash
sudo scripts/uninstall-local.sh
```

如需彻底清理托管目录、系统用户和用户组，使用：

```bash
sudo scripts/uninstall-local.sh --purge
```

## 使用

### 常用命令

```bash
ps-agent list
ps-agent validate
ps-agent check
ps-agent start
ps-agent stop usa1
ps-agent restart usa1
ps-agent status
ps-agent logs usa1 --follow
ps-agent ipinfo usa1
ps-agent doctor
```

目标作用域可以是全部 enabled stack、单个 stack、单个组件或订阅服务：

```bash
ps-agent start
ps-agent start usa1
ps-agent start xrelay/usa1
ps-agent start clash/usa1
ps-agent start sub
```

### 新增和管理 stack

```bash
ps-agent add usa1
ps-agent add auto --template auto-url-test --members usa1,usa2
ps-agent clone usa1 usa2 --allocate-ports
ps-agent remove usa2
```

`add` 默认使用 `config.yaml` 中的 `port_ranges` 自动分配端口，并会打开编辑器让用户确认 stack 配置。自动化场景可加 `--no-edit`。

### 渲染与订阅

```bash
ps-agent render model
ps-agent render xrelay usa1
ps-agent render clash usa1
ps-agent render sub
ps-agent sub export
ps-agent sub export usa1
ps-sub config --data-dir /opt/proxystack/sub
ps-sub import /opt/proxystack/publish/sub-bundle.zip --data-dir /opt/proxystack/sub
ps-sub clear --data-dir /opt/proxystack/sub
ps-sub serve --config /opt/proxystack/sub/config.yaml
```

订阅只读取 `xrelay.inbounds[]` 中 `sub: true` 的条目，不会把 clash 的代理组、规则或 controller 配置暴露给订阅服务。

### 更新与备份

```bash
ps-agent install all
ps-agent update mihomo
ps-agent update xray
ps-agent update geo
ps-agent update self --wheel proxystack-<version>-py3-none-any.whl
ps-agent export
ps-agent import /opt/proxystack/publish/proxystack-backup.zip
```

`install/update all` 只处理 mihomo、xray-core 和 geo 数据，不安装 systemd unit，也不会自动重启服务。systemd unit 使用 `ps-agent service install [target]`、`ps-agent service uninstall [target]` 管理。

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
