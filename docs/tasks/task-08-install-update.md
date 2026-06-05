# Task 08: 下载安装与更新

## 目标

实现 proxystack 后续 self update、mihomo、xray-core 和 geo 数据的安装/更新能力。

## 技术方案

- 新建 `src/proxystack/install`。
- 默认安装根目录使用 `/opt/proxystack`，代理核心二进制安装到 `/opt/proxystack/bin`，geo 数据安装到 `/opt/proxystack/geo`，下载缓存放在 `/opt/proxystack/downloads`。
- 下载、解压、校验、替换拆成独立接口。
- 所有外部命令使用参数数组调用，不拼接 shell 字符串。
- Python 包安装推荐使用 wheel + `/opt/proxystack/.venv`，systemd unit 使用 venv 内 console script 的绝对路径，不依赖 shell activate。
- 本任务不实现 systemd unit 安装入口；unit 安装和卸载统一由 Task 09 的 `service install|uninstall` 负责。
- 首次 bootstrap 脚本在 Task 12 中消费本任务定义的安装和更新接口；本任务不依赖部署脚本实现。
- 后续 proxystack 代码更新由 `proxystack-agent update self` 管理；代理核心下载和更新由 `proxystack-agent install/update mihomo|xray|geo|all` 管理。

## 实现步骤

1. 定义安装配置：版本、下载源、sha256、安装目录。
2. 定义本地运行目录和权限要求：`/opt/proxystack`、`.venv`、`bin`、`geo`、`runtime`、`publish`、`downloads`。
3. 实现 `update self`：支持 wheel/package spec、sha256 校验、调用 venv 内 `python -m pip install --upgrade`，完成后尽快退出或重新 exec；命令必须校验当前用户对 `.venv` 的写权限，不自动提权。
4. 实现 mihomo 下载和安装。
5. 实现 xray-core 下载和安装。
6. 实现 geo 数据下载和安装。
7. 实现 `version` 检测。
8. 实现 `update` 的停止服务、替换、恢复流程。

## 验收标准

- 支持指定版本和 sha256。
- 部署文档包含从空机器安装 agent、创建 Python venv、安装 wheel 和暴露 CLI 的步骤。
- `update self` 不隐式更新代理核心；`update all` 不隐式更新 proxystack Python 包。
- `install all` 只安装 mihomo、xray-core 和 geo 数据，不安装 systemd unit。
- systemd unit 使用 venv 内路径，不要求用户执行 `source /opt/proxystack/.venv/bin/activate`。
- mihomo 和 xray-core 安装到 `/opt/proxystack/bin`，geo 数据安装到 `/opt/proxystack/geo`，owner 为 `proxystack:proxystack`。
- 下载失败不会破坏现有可执行文件。
- 更新前后服务状态尽量保持一致。
- 单元测试用 fake downloader 覆盖成功和失败路径。

## 依赖

Task 01。

## 风险

不要在服务启动时自动下载；下载安装必须由用户显式命令触发。

## P0 候选版交付状态

- 已新增 `src/proxystack/install`，拆分下载/本地文件读取、sha256 校验、归档抽取、原子替换、权限设置、版本检测和 self update 服务函数。
- 已接入 `proxystack-agent install mihomo|xray|geo|all` 和 `proxystack-agent update mihomo|xray|geo|all|self`。
- `mihomo/xray` 默认安装到 `config.paths.bin`；`geo` 默认安装到 `config.paths.geo`；远端下载缓存到 `config.paths.downloads`。
- `install all` 与 `update all` 只展开 `mihomo/xray/geo`，不包含 systemd unit，也不包含 `self`。
- `update self` 只调用 venv 内 `python -m pip install --upgrade`，支持 `--wheel <file>` 或 package spec；命令执行可通过 fake runner 测试。
- P0 更新流程只输出 service adapter 文本计划，不真实调用 `systemctl`，不写 `/etc/systemd/system`。
- 远端下载必须提供 sha256，生产下载路径拒绝本机/私网地址和 HTTP 重定向；校验失败和替换失败不会覆盖既有目标文件。
- geo 多文件归档采用批量替换事务，任一文件失败会回滚本次已替换文件。
- 未内置 GitHub Release 自动解析器；单目标通过 `--source/--url` 或 `config.install.<target>.source` 指定来源，`all` 使用配置中三类目标各自的来源。
