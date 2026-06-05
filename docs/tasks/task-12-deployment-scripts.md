# Task 12: 部署脚本

## 目标

实现首次安装和订阅服务部署所需的 Shell 脚本。脚本只负责 bootstrap 和部署编排，不负责 proxystack 后续代码更新，也不直接下载 mihomo、xray-core 或 geo 数据。

## 交付状态

已完成。交付内容包括公共函数库、agent 本地安装脚本、本地 sub 安装脚本、Docker sub 部署脚本、脚本 README、dry-run/静态边界测试和交付记录。详见 [Task12 部署脚本交付记录](../delivery/2026-06-05-20-58-01-feature-shell-deployment-scripts.md)。

## 技术方案

- 脚本放在项目根目录的 `scripts/` 下。
- 公共函数放在 `scripts/lib/common.sh`，统一处理日志、`--dry-run`、命令检查、路径保护和目录创建。
- `scripts/install-agent.sh`：本地安装 agent，创建系统用户、目录、Python venv、安装 wheel/source/package、链接 console scripts，可选安装 systemd unit；可以创建 `/opt/proxystack/bin` 和 `/opt/proxystack/geo` 空目录，但不下载代理核心或 geo 数据。
- `scripts/install-sub-local.sh`：本地或远端非 Docker 部署订阅服务，创建 sub 数据目录，可选导入发布包，可选安装和启动 `proxystack-sub.service`。
- `scripts/deploy-sub-docker.sh`：Docker 部署订阅服务，创建 `/data` 持久化目录，启动安全默认的容器。
- 日志 message 使用英文；面向用户的文档说明使用中文。

## 实现步骤

1. [x] 编写 `scripts/lib/common.sh`，包含 `log`、`warn`、`die`、`run`、`require_cmd`、`require_root`、`guard_managed_path`、`ensure_dir`、`ensure_venv` 等函数。
2. [x] 编写 `scripts/install-agent.sh`，支持 `--wheel`、`--source`、`--package`、`--base-dir`、`--bin-dir`、`--python`、`--user`、`--group`、`--no-init`、`--install-systemd`、`--dry-run`。
3. [x] 编写 `scripts/install-sub-local.sh`，支持 `--wheel`、`--source`、`--package`、`--base-dir`、`--import-bundle`、`--install-systemd`、`--start`、`--dry-run`。
4. [x] 编写 `scripts/deploy-sub-docker.sh`，支持 `--image`、`--name`、`--data-dir`、`--host`、`--port`、`--user`、`--data-owner`、`--pull`、`--replace`、`--dry-run`。
5. [x] 编写 `scripts/README.md`，说明三类脚本的使用方式、安全边界和常见示例。
6. [x] 在部署文档中引用脚本任务和最终脚本入口，不把脚本职责扩展到后续更新。

## P0 实现状态

- 已新增 `scripts/lib/common.sh`，统一日志、dry-run、命令检查、root 检查、路径保护、目录创建和 venv 创建。
- 已新增 `scripts/install-agent.sh`、`scripts/install-sub-local.sh`、`scripts/deploy-sub-docker.sh` 和 `scripts/README.md`。
- 已补充 Task12 静态和 dry-run 测试，覆盖 help、危险路径拒绝、Docker 安全默认、`--replace` 显式替换和 agent 脚本不越界下载代理核心。
- Shell 脚本仍只负责首次 bootstrap；后续 self update、mihomo/xray-core/geo 安装更新继续由 `proxystack-agent` 子命令负责。

## 验收标准

- 所有脚本有 `--help`。
- 所有脚本支持 `--dry-run`。
- `bash -n scripts/*.sh scripts/lib/*.sh` 通过。
- `shellcheck scripts/*.sh scripts/lib/*.sh` 通过。
- 脚本默认不删除已有配置。
- Docker 脚本默认不覆盖同名容器，除非传入 `--replace`。
- `install-agent.sh` 不提供 `--install-core`，不下载 mihomo、xray-core 或 geo 数据。
- 后续 proxystack 代码更新只通过 `proxystack-agent update self`；代理核心下载和更新只通过 `proxystack-agent install/update mihomo|xray|geo|all`。

## 依赖

Task 01、Task 08、Task 09。

## 风险

Shell 脚本容易把安装、更新和运行时管理混在一起；实现时必须守住边界：Shell 只做首次 bootstrap，重复运维动作交给 Python 子命令。

## 实现备注

- `install-agent.sh` 不提供 `--install-core`，不会下载 mihomo、xray-core 或 geo 数据。
- `deploy-sub-docker.sh` 默认不删除同名容器，只有传入 `--replace` 才会执行 `docker rm -f`。
- 所有脚本都支持 `--dry-run`，写入动作可预览。
