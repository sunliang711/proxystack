# 部署方案

## 1. 组件部署边界

`proxystack` 分为两个运行组件：

- `proxystack-agent`：部署在本地代理机器上，管理 `/opt/proxystack/config.yaml`、`/opt/proxystack/stacks/*.yaml`、Xray/mihomo stack 对、systemd 服务、安装更新和订阅发布包导出。
- `proxystack-sub`：部署在提供订阅链接的机器上，只消费订阅输入文件或 `sub-bundle.zip`，可合并 inputs 目录中的多个输入，不读取完整 stack，也不保存 clash upstream、rules、mode 或 controller 配置。

`proxystack-sub` 支持两种部署方式：

- 本地部署：和 agent 共用 `/opt/proxystack`，使用 Python venv + systemd。
- Docker 部署：容器运行 FastAPI/Uvicorn，订阅数据通过 volume 持久化。

## 2. 本地部署 `proxystack-agent`

默认目录：

```text
/opt/proxystack/
  .venv/
  bin/
    mihomo
    xray
  config.yaml
  geo/
  stacks/
    usa1.yaml
  runtime/
    generated/
    manifest.json
  publish/
  downloads/
```

首次安装建议流程：

```bash
sudo groupadd --system proxystack
sudo useradd --system --home /opt/proxystack --shell /usr/sbin/nologin --gid proxystack proxystack
sudo install -d -o proxystack -g proxystack -m 0750 /opt/proxystack
sudo install -d -o proxystack -g proxystack -m 0750 /opt/proxystack/bin
sudo install -d -o proxystack -g proxystack -m 0750 /opt/proxystack/geo
sudo install -d -o proxystack -g proxystack -m 0750 /opt/proxystack/downloads
sudo install -d -o proxystack -g proxystack -m 0750 /opt/proxystack/runtime
sudo install -d -o proxystack -g proxystack -m 0750 /opt/proxystack/publish
sudo -u proxystack python3 -m venv /opt/proxystack/.venv
sudo -u proxystack /opt/proxystack/.venv/bin/python -m pip install --upgrade pip
sudo -u proxystack /opt/proxystack/.venv/bin/pip install proxystack-<version>-py3-none-any.whl

sudo ln -sf /opt/proxystack/.venv/bin/proxystack-agent /usr/local/bin/proxystack-agent
sudo ln -sf /opt/proxystack/.venv/bin/proxystack-sub /usr/local/bin/proxystack-sub
```

说明：

- 交互式使用时可以执行 `source /opt/proxystack/.venv/bin/activate`，但不是必需步骤；`/usr/local/bin/proxystack-agent` 和 `/usr/local/bin/proxystack-sub` 会直接指向 venv 内的 console scripts。
- systemd unit 不依赖 shell 的 venv activate，而是使用 `/opt/proxystack/.venv/bin/proxystack-agent`、`/opt/proxystack/.venv/bin/proxystack-sub` 或生成后的二进制路径。
- 首次 bootstrap 脚本默认从脚本所在仓库根目录安装源码，也可以用 `--source DIR` 指定源码目录。
- bootstrap 脚本会在 `/opt/proxystack/runtime/source.sha256` 记录源码指纹；重复执行时，源码未变化且 venv 内 console scripts 正常存在就跳过 pip 安装，源码变化会自动重新安装。
- 安装或升级 Python 包不自动下载 mihomo、xray-core 或 geo 数据；代理核心安装仍由 `proxystack-agent install ...` 显式触发。
- `proxystack-agent install mihomo|xray` 默认把代理核心写入 `/opt/proxystack/bin`；`proxystack-agent install geo` 默认下载 `MetaCubeX/meta-rules-dat` 的 `geoip.metadb` 并写入 `/opt/proxystack/geo`；普通远端 URL 必须显式提供 sha256，本地文件也建议提供 sha256。
- `proxystack-agent install all` 和 `proxystack-agent update all` 只展开 `config.install.mihomo/xray/geo`，不会安装 systemd unit，也不会执行 self update。默认配置下三个目标都使用托管 `auto` 源。
- `install` 遇到已存在的目标二进制或 geo 数据会跳过下载；`update` 会强制重新下载并替换目标文件。
- 首次安装由 Shell 脚本 bootstrap；后续 proxystack 代码更新、mihomo/xray-core/geo 下载和更新都由 `proxystack-agent` 子命令管理。
- `update self` 默认以 `proxystack` 用户运行并只写 `/opt/proxystack/.venv`；普通管理员应显式使用 `sudo -u proxystack proxystack-agent update self --wheel <file>`，CLI 不自动提权。

仓库提供首次 bootstrap 脚本，见 [scripts/README.md](../scripts/README.md) 和 [Task 12](tasks/task-12-deployment-scripts.md)。脚本只创建系统用户、目录、Python venv、安装 proxystack Python 包、暴露 CLI，并可选安装 systemd unit；代理核心安装不放在 Shell 脚本中，首次安装后手动执行 `proxystack-agent install all`。`install all` 只覆盖 mihomo、xray-core 和 geo 数据；systemd unit 安装统一使用 `proxystack-agent service install [target]`。

```bash
sudo scripts/install-agent.sh
sudo scripts/install-agent.sh --install-systemd
```

常用流程：

```bash
proxystack-agent setup
proxystack-agent add usa1
proxystack-agent config usa1
proxystack-agent check
proxystack-agent start
proxystack-agent status
proxystack-agent publish
```

说明：

- `init` 创建 `/opt/proxystack` 目录结构和默认 `config.yaml`，默认配置优先来自 `examples/config.yaml`。
- `setup` 会先执行幂等初始化，再安装代理核心和 geo 数据，最后安装 systemd unit。
- `add usa1` 创建 `/opt/proxystack/stacks/usa1.yaml`。
- `check` 校验配置并展示生成变更预览，不写运行目录、不操作 systemd。
- `start` 先检查 `mihomo`/`xray` 是否已安装且可执行，再生成配置并写入 manifest，最后通过 systemd 启动目标服务；配置变化时会重启受影响服务，并启动目标范围内未变化的服务。
- `publish` 默认生成 `/opt/proxystack/publish/sub-bundle.zip`。
- 后续 proxystack 代码更新使用 `proxystack-agent update self --wheel <file>` 或配置的包源；代理核心更新使用 `proxystack-agent update mihomo|xray|geo|all`。
- `install/update mihomo|xray|geo|all` 仍只处理代理核心和 geo 数据，不自动停启 systemd 服务；真实停启和 unit 管理由 `service` 分组和顶层生命周期命令提供。

systemd unit 文件需要安装到 `/etc/systemd/system/`，这是 systemd 的固定约束；unit 内容必须指向 `/opt/proxystack` 内的配置、虚拟环境和生成文件。

## 3. 本地部署 `proxystack-sub`

适用于同一台机器同时提供订阅 HTTP 服务的场景。

默认目录：

```text
/opt/proxystack/sub/
  inputs/
  bundles/
  current/
    index.json
```

导入发布包并启动：

```bash
proxystack-agent publish
proxystack-sub import /opt/proxystack/publish/sub-bundle.zip --data-dir /opt/proxystack/sub
proxystack-sub serve --host 0.0.0.0 --port 3003 --data-dir /opt/proxystack/sub
```

本地订阅服务可使用 `scripts/install-sub-local.sh` 部署，脚本封装 sub 数据目录创建、可选发布包导入、可选 systemd 安装和启动。

```bash
sudo scripts/install-sub-local.sh \
  --import-bundle /opt/proxystack/publish/sub-bundle.zip \
  --install-systemd \
  --start
```

服务启动命令建议：

```bash
proxystack-sub serve --host 0.0.0.0 --port 3003 --data-dir /opt/proxystack/sub
```

本地部署要求：

- `proxystack-sub.service` 只运行订阅 HTTP 服务；unit 安装使用 `proxystack-agent service install sub`，常用启停使用 `proxystack-agent start sub`、`proxystack-agent stop sub` 和 `proxystack-agent restart sub`。
- 发布包更新通过 `proxystack-sub import sub-bundle.zip` 完成；import 默认自动 rebuild。多个输入文件也可以直接放入 `/opt/proxystack/sub/inputs/` 后执行 `proxystack-sub rebuild`。
- import 必须校验 zip 路径穿越、manifest hash 和 bundle version。
- 服务进程只读取 `/opt/proxystack/sub/current`，不读取 `/opt/proxystack/config.yaml` 或 `stacks/*.yaml`。

## 4. 本地卸载

本地非 Docker 部署统一使用 `scripts/uninstall-local.sh` 卸载 systemd unit。默认保留配置、stack、运行数据、用户和 CLI 链接：

```bash
sudo scripts/uninstall-local.sh
```

只卸载订阅服务：

```bash
sudo scripts/uninstall-local.sh --target sub
```

彻底清理托管目录和用户必须显式指定：

```bash
sudo scripts/uninstall-local.sh --target all --purge-data --remove-user --remove-bin
```

## 5. 同机非 Docker 目录边界

agent 和 sub 可以部署在同一台机器、共用 `/opt/proxystack` 根目录，但不能共用同一批运行数据：

```text
/opt/proxystack/
  config.yaml              # agent 读取
  stacks/                  # agent 读取和编辑
  runtime/                 # agent 写入
  publish/                 # agent 写入发布包
  downloads/               # agent 写入下载缓存
  sub/                     # sub 写入
    inputs/
    bundles/
    current/
```

写入边界：

- `proxystack-agent` 可写 `runtime/`、`publish/`、`downloads/` 和 `stacks/*.yaml`。
- `config.yaml` 运行期只读；只有 `init` 和 `edit` 这类配置管理命令可以写。
- `proxystack-sub` 只写 `sub/inputs/`、`sub/bundles/`、`sub/current/`。
- `proxystack-agent publish` 只生成 `/opt/proxystack/publish/sub-bundle.zip`，不直接改 `sub/current/`。
- `proxystack-sub import` 从发布包复制 inputs 到 `sub/inputs/`，再 rebuild 到 `sub/current/`。

运行边界：

- agent 锁文件：`/opt/proxystack/runtime/agent.lock`。
- sub 锁文件：`/opt/proxystack/sub/sub.lock`。
- agent 服务：`proxystack-xray@<name>.service`、`proxystack-clash@<name>.service`。
- sub 服务：`proxystack-sub.service`。
- `validate/doctor` 必须检查订阅服务端口是否和 xrelay/clash/controller 端口冲突。

因此同机部署不会目录冲突；唯一需要用户配置的是订阅服务监听端口，例如 `127.0.0.1:3003` 或由反向代理转发的公网端口。

权限模型：

- 默认创建系统用户和用户组：`proxystack:proxystack`。
- `/opt/proxystack`：`0750`，owner 为 `proxystack:proxystack`。
- `/opt/proxystack/.venv/`、`bin/`、`geo/`：`0750`，owner 为 `proxystack:proxystack`。
- `/opt/proxystack/bin/mihomo` 和 `/opt/proxystack/bin/xray`：`0750`，owner 为 `proxystack:proxystack`。
- `/opt/proxystack/geo/*`：`0640`，owner 为 `proxystack:proxystack`。
- `/opt/proxystack/config.yaml` 和 `stacks/*.yaml`：`0640`。
- `/opt/proxystack/runtime/`、`publish/`、`downloads/`：`0750`。
- `/opt/proxystack/sub/`、`sub/inputs/`、`sub/bundles/`、`sub/current/`：`0750`。
- `/usr/local/bin/proxystack-agent`、`/usr/local/bin/proxystack-sub`、`/usr/local/bin/ps-agent` 和 `/usr/local/bin/ps-sub`：root-owned symlink，指向 `/opt/proxystack/.venv/bin/` 中的 console script。
- `service install|uninstall` 和首次创建 `/etc/systemd/system/*.service` 必须以 root 运行；`update self`、`install/update mihomo|xray|geo` 默认以 `proxystack` 用户运行。需要重启 systemd 服务时，用户必须显式使用 sudo 或系统授权，CLI 不静默提权。

systemd hardening 要求：

- `User=proxystack`、`Group=proxystack`。
- `NoNewPrivileges=true`。
- `ProtectSystem=strict`。
- `ProtectHome=true`。
- `PrivateTmp=true`。
- `ReadWritePaths=/opt/proxystack/runtime` 用于 xray/clash 运行服务；如果 `config.paths.generated` 不在 runtime 下，也会额外加入该生成目录。
- `ReadWritePaths=/opt/proxystack/sub` 用于 `proxystack-sub.service`。

Task09 P0 实现的 unit 约束：

- `proxystack-xray@.service` 和 `proxystack-clash@.service` 只引用 `runtime/generated` 下的生成后配置文件，不把 `config.yaml` 或 `stacks/*.yaml` 作为运行配置传入服务。
- xray/clash unit 的 `ReadWritePaths` 仅包含 agent runtime 相关目录。
- `proxystack-sub.service` 只传入 `proxystack-sub serve --data-dir <sub_dir> --host <host> --port <port>`，不读取或改写 stack 文件。
- `service install|uninstall` 是唯一 unit 文件安装卸载入口；`install/update` 分组不提供 unit 安装命令。
- `systemctl` 和 `journalctl` 通过参数数组调用；返回非零时 CLI 展示 stdout/stderr 摘要并失败，不吞掉权限错误。

## 6. Docker 部署 `proxystack-sub`

适用于远端订阅服务器或希望隔离运行环境的场景。

镜像职责：

- 只包含 `proxystack-sub` 运行所需依赖。
- 暴露订阅 HTTP 端口。
- 通过 volume 保存 inputs、已导入的发布包和 current 索引。
- 不包含 mihomo、xray-core，也不管理 systemd。

推荐运行：

```bash
mkdir -p /opt/proxystack/sub

docker run -d \
  --name proxystack-sub \
  --restart unless-stopped \
  -p 3003:3003 \
  -v /opt/proxystack/sub:/data \
  --user 10001:10001 \
  --read-only \
  --cap-drop ALL \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  proxystack-sub:latest \
  proxystack-sub serve --host 0.0.0.0 --port 3003 --data-dir /data
```

Docker 部署可使用 `scripts/deploy-sub-docker.sh`，脚本封装数据目录创建、owner 设置和安全默认的容器启动参数。同名容器已存在时脚本默认失败，需要显式传入 `--replace`。

```bash
sudo scripts/deploy-sub-docker.sh \
  --image proxystack-sub:latest \
  --data-dir /opt/proxystack/sub \
  --port 3003
```

导入发布包：

```bash
docker cp sub-bundle.zip proxystack-sub:/tmp/sub-bundle.zip
docker exec proxystack-sub proxystack-sub import /tmp/sub-bundle.zip --data-dir /data
docker exec proxystack-sub python -c "import json; print(json.load(open('/data/current/index.json'))['index_version'])"
```

Docker Compose 示例：

```yaml
services:
  proxystack-sub:
    build:
      context: .
      dockerfile: Dockerfile.sub
    image: proxystack-sub:latest
    container_name: proxystack-sub
    restart: unless-stopped
    ports:
      - "3003:3003"
    volumes:
      - /opt/proxystack/sub:/data
    user: "10001:10001"
    read_only: true
    cap_drop:
      - ALL
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=64m
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3003/health', timeout=2)"]
      interval: 30s
      timeout: 3s
      retries: 3
    command:
      - proxystack-sub
      - serve
      - --host
      - 0.0.0.0
      - --port
      - "3003"
      - --data-dir
      - /data
```

仓库提供了可直接参考的 [Dockerfile.sub](../Dockerfile.sub) 和 [docker-compose.sub.yml](../docker-compose.sub.yml)。镜像只安装 proxystack Python 包和订阅服务依赖，不包含 mihomo 或 xray-core。

Docker 部署安全要求：

- 容器内服务默认不需要 root 权限。
- `/data` volume 必须持久化，否则重启后会丢失 inputs、已导入发布包和 current 索引。
- 容器应 drop capabilities、只读根文件系统，并配置 healthcheck。
- 不把完整 stack 或 mihomo 配置挂载进容器。
- 如果公网暴露订阅服务，建议在反向代理层加 HTTPS、访问控制、限流和日志。

## 7. 发布包同步方式

P0 只要求手动上传/导入：

```bash
proxystack-agent publish -o /opt/proxystack/publish/sub-bundle.zip
scp /opt/proxystack/publish/sub-bundle.zip user@sub-server:/tmp/sub-bundle.zip
ssh user@sub-server 'proxystack-sub import /tmp/sub-bundle.zip'
```

多输入文件场景：

```bash
proxystack-agent sub export-input --source usa1 -o usa1.yaml
proxystack-agent sub export-input --source usa2 -o usa2.yaml
scp usa1.yaml usa2.yaml user@sub-server:/opt/proxystack/sub/inputs/
ssh user@sub-server 'proxystack-sub rebuild --data-dir /opt/proxystack/sub'
```

同一批 inputs 也可以直接给本地 agent 使用，例如在上传前先校验、输出合并结果并打包：

```bash
mkdir -p ./inputs
cp usa1.yaml usa2.yaml ./inputs/
proxystack-agent sub validate-inputs --input-dir ./inputs
proxystack-agent render sub --input-dir ./inputs
proxystack-agent publish --input-dir ./inputs --source merged -o sub-bundle.zip
```

Docker 场景：

```bash
scp /opt/proxystack/publish/sub-bundle.zip user@sub-server:/tmp/sub-bundle.zip
ssh user@sub-server 'docker cp /tmp/sub-bundle.zip proxystack-sub:/tmp/sub-bundle.zip'
ssh user@sub-server 'docker exec proxystack-sub proxystack-sub import /tmp/sub-bundle.zip --data-dir /data'
```

Docker 多输入文件场景：

```bash
scp usa1.yaml usa2.yaml user@sub-server:/opt/proxystack/sub/inputs/
ssh user@sub-server 'docker exec proxystack-sub proxystack-sub rebuild --data-dir /data'
```

P1 可以增加远端自动拉取发布包，但需要单独设计鉴权、签名和回滚策略。
