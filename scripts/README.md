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

## scripts/install-agent.sh

安装本地 `proxystack-agent`：

```bash
sudo scripts/install-agent.sh --wheel dist/proxystack-0.1.0-py3-none-any.whl
```

从包源安装并安装 systemd unit：

```bash
sudo scripts/install-agent.sh \
  --package 'proxystack==0.1.0' \
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

- `--wheel FILE`、`--source DIR`、`--package SPEC` 三选一，指定 Python 包安装来源。
- `--base-dir DIR` 默认 `/opt/proxystack`。
- `--bin-dir DIR` 默认 `/usr/local/bin`，用于链接 `proxystack-agent` 和 `proxystack-sub`。
- `--python CMD` 默认 `python3`。
- `--user USER`、`--group GROUP` 默认 `proxystack`。
- `--no-init` 跳过 `proxystack-agent init`。
- `--install-systemd` 执行 `proxystack-agent service install`。

## scripts/install-sub-local.sh

安装本地非 Docker 的 `proxystack-sub`：

```bash
sudo scripts/install-sub-local.sh \
  --wheel dist/proxystack-0.1.0-py3-none-any.whl \
  --import-bundle /opt/proxystack/publish/sub-bundle.zip \
  --install-systemd \
  --start
```

主要参数：

- `--wheel FILE`、`--source DIR`、`--package SPEC` 三选一，指定 Python 包安装来源。
- `--base-dir DIR` 默认 `/opt/proxystack`，订阅数据目录固定为 `${base_dir}/sub`。
- `--import-bundle FILE` 调用 `proxystack-sub import FILE --data-dir ${base_dir}/sub`。
- `--install-systemd` 只安装 `proxystack-sub.service`。
- `--start` 启动 `proxystack-sub.service`。

脚本会在 `config.yaml` 不存在时运行 `proxystack-agent init` 生成默认配置；已存在配置不会被覆盖。

## scripts/deploy-sub-docker.sh

用 Docker 部署订阅服务：

```bash
sudo scripts/deploy-sub-docker.sh \
  --image proxystack-sub:latest \
  --data-dir /opt/proxystack/sub \
  --port 3003
```

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
scripts/install-agent.sh --package proxystack --install-systemd --dry-run
scripts/install-sub-local.sh --package proxystack --import-bundle sub-bundle.zip --dry-run
scripts/deploy-sub-docker.sh --replace --dry-run
```
