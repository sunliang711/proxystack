# Task12 部署脚本交付记录

## 变更摘要

- 新增 `scripts/lib/common.sh`，统一日志、dry-run、命令检查、root 检查、托管路径保护、目录创建、venv 创建和按用户执行命令。
- 新增 `scripts/install-agent.sh`，支持 wheel/source/package 三种 Python 包安装来源，创建系统用户/组、托管目录、venv、console script 链接，并可选执行 `proxystack-agent service install`。
- 新增 `scripts/install-sub-local.sh`，支持本地非 Docker 订阅服务安装、sub 数据目录创建、可选发布包导入、可选安装和启动 `proxystack-sub.service`。
- 新增 `scripts/deploy-sub-docker.sh`，用安全默认参数运行 Docker 订阅服务，默认不覆盖同名容器，只有显式 `--replace` 才删除同名容器。
- 新增 `scripts/README.md` 和 dry-run 单元测试，明确脚本职责边界：不下载 mihomo、xray-core 或 geo，不提供 `--install-core`。
- 加固托管路径和安装身份校验：生产托管目录限制为 `/opt/proxystack` 及其子路径，dry-run 仅额外允许 `/tmp/proxystack-*` 前缀，并拒绝 root 用户/组。
- 调整 Docker 同名容器处理顺序：未指定 `--replace` 时在目录写入和拉镜像前失败；指定 `--replace` 时仍在镜像可用后再删除旧容器。

## 验证

```bash
bash -n scripts/*.sh scripts/lib/*.sh
shellcheck scripts/*.sh scripts/lib/*.sh
.venv/bin/python -m pytest tests/unit/test_task12_deployment_scripts.py -q
.venv/bin/python -m pytest -q
```

以上检查通过。Task12 专项测试覆盖 help、dry-run、危险路径拒绝、托管路径白名单、root 用户/组拒绝、`--bin-dir` 敏感目录拒绝、Docker 安全默认、同名容器冲突先于目录写入失败、`--pull` 先于 `--replace`、`--replace` 显式替换和 agent 脚本不越界下载代理核心。

## 风险

- 自动化测试只覆盖 help、dry-run 和静态边界，不启动真实 Docker 容器，也不执行真实 root/systemd 安装。
- `install-sub-local.sh` 为了安装 `proxystack-sub.service` 需要可读取的 `config.yaml`；当配置不存在时会生成默认配置，但不会覆盖已有配置。
