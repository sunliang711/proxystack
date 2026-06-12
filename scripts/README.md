# 部署脚本说明

本目录提供首次安装和订阅服务部署脚本。脚本只负责 bootstrap 和部署编排，不负责后续 proxystack 代码更新，也不下载 mihomo、xray-core 或 geo 数据。

## 通用安全边界

- 所有脚本都支持 `--help` 和 `--dry-run`。
- Shell 日志 message 使用英文，便于自动化日志检索。
- 写入动作会通过 `run` 统一打印；`--dry-run` 只预览命令，不创建目录、不安装包、不删除容器。
- 托管路径必须是绝对路径，不能是空路径、根目录、`/usr`、`/etc`、`/bin`、`/sbin`、`/var` 等系统目录，也不能包含 `..` 路径穿越。
- 脚本默认不删除已有配置；Docker 部署默认不覆盖同名容器。
- `install-agent.sh` 不提供 `--install-core`，也不会下载 mihomo、xray-core 或 geo 数据。代理核心和 geo 仍通过 `proxystack-agent install/update mihomo|xray|geo|all` 显式执行。
- 安装 Python 包时会自动尝试多个 pip index。优先使用环境变量 `PIP_INDEX_URL`，也可以用空格分隔的 `PIP_INDEX_URLS` 覆盖候选列表；未配置时依次尝试 PyPI、清华、阿里云和中科大镜像。
- 安装脚本会记录源码目录指纹；重复运行时，如果源码未变化且 venv 内 `proxystack-agent`、`proxystack-sub`、`ps-agent`、`ps-sub` 仍可执行，会跳过 pip 安装，源码变化时会自动重新安装。
- `ps-agent` 是 `proxystack-agent` 的短命令别名，`ps-sub` 是 `proxystack-sub` 的短命令别名。

## scripts/install-agent.sh

安装本地 `proxystack-agent`：

```bash
sudo scripts/install-agent.sh
```

安装脚本完成后会输出 `Next steps`，首次部署可继续执行：

```bash
sudo ps-agent setup
sudo ps-agent doctor
sudo ps-agent add usa1
sudo ps-agent config usa1
sudo ps-agent check usa1
sudo ps-agent start usa1
```

`--install-systemd` 适用于只想在 bootstrap 阶段提前安装 unit、暂不执行 `setup` 下载代理核心的高级场景。普通首次安装优先使用上面的 `ps-agent setup` 主路径。

提前安装 systemd unit：

```bash
sudo scripts/install-agent.sh \
  --install-systemd
```

从源码目录安装到自定义目录：

```bash
sudo scripts/install-agent.sh \
  --source /path/to/proxystack \
  --base-dir /opt/proxystack \
  --bin-dir /usr/local/bin
```

主要参数：

- `--source DIR` 默认脚本所在仓库根目录，用于覆盖源码安装目录。
- `--base-dir DIR` 默认 `/opt/proxystack`。
- `--bin-dir DIR` 默认 `/usr/local/bin`，用于链接 `proxystack-agent`、`proxystack-sub`、`ps-agent` 和 `ps-sub`。
- `--python CMD` 默认 `python3`。
- `--user USER`、`--group GROUP` 默认 `proxystack`。
- `--no-init` 跳过 `proxystack-agent init`。
- `--install-systemd` 执行 `proxystack-agent service install`。

## scripts/install-sub-local.sh

安装本地非 Docker 的 `proxystack-sub`：

```bash
sudo scripts/install-sub-local.sh \
  --import-bundle /opt/proxystack/publish/sub-bundle.zip \
  --install-systemd \
  --start
```

主要参数：

- `--source DIR` 默认脚本所在仓库根目录，用于覆盖源码安装目录。
- `--base-dir DIR` 默认 `/opt/proxystack`，订阅数据目录固定为 `${base_dir}/sub`。
- `--bin-dir DIR` 默认 `/usr/local/bin`，用于链接 `proxystack-agent`、`proxystack-sub`、`ps-agent` 和 `ps-sub`。
- `--import-bundle FILE` 调用 `proxystack-sub import FILE --data-dir ${base_dir}/sub`。
- `--install-systemd` 只安装 `proxystack-sub.service`。
- `--start` 启动 `proxystack-sub.service`。

脚本会在 `config.yaml` 不存在时运行 `proxystack-agent init` 生成默认配置和初始 `sub/config.yaml`；已存在配置不会被覆盖。

## scripts/uninstall-local.sh

安全卸载本地服务。默认停止并禁用服务、删除 systemd unit 和 CLI 链接，保留配置、运行数据、用户和用户组：

```bash
sudo scripts/uninstall-local.sh
```

彻底清理托管目录、用户和用户组需要显式确认：

```bash
sudo scripts/uninstall-local.sh --purge
```

主要参数：

- `--base-dir DIR` 默认 `/opt/proxystack`。
- `--bin-dir DIR` 默认 `/usr/local/bin`。
- `--purge` 删除 `${base_dir}`、系统用户和用户组。

## scripts/deploy-sub-docker.sh

用 Docker 部署订阅服务：

```bash
sudo scripts/deploy-sub-docker.sh \
  --image proxystack-sub:latest \
  --data-dir /opt/proxystack/sub \
  --port 3003
```

脚本要求数据目录中已存在 `config.yaml`，避免容器以无鉴权默认配置启动。

拉取镜像并显式替换同名容器：

```bash
sudo scripts/deploy-sub-docker.sh \
  --image proxystack-sub:latest \
  --pull \
  --replace
```

主要参数：

- `--image IMAGE` 默认 `proxystack-sub:latest`。
- `--name NAME` 默认 `proxystack-sub`。
- `--data-dir DIR` 默认 `/opt/proxystack/sub`，会挂载到容器内 `/data`。
- `--host HOST` 默认 `0.0.0.0`。
- `--port PORT` 默认 `3003`，映射到容器内 `3003`。
- `--user UID:GID` 默认 `10001:10001`。
- `--data-owner UID:GID` 默认 `10001:10001`。
- `--pull` 运行前拉取镜像。
- `--replace` 删除同名容器后重新运行；未提供时同名容器存在会失败。

默认 `docker run` 参数包含 `--read-only`、`--cap-drop ALL`、`--tmpfs /tmp:rw,noexec,nosuid,size=64m` 和 `--restart unless-stopped`。

## dry-run 示例

```bash
scripts/install-agent.sh --install-systemd --dry-run
scripts/install-sub-local.sh --import-bundle sub-bundle.zip --dry-run
scripts/uninstall-local.sh --purge --dry-run
scripts/deploy-sub-docker.sh --replace --dry-run
```
