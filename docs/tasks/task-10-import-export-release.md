# Task 10: 发布构建与后续备份导入导出

## 目标

实现订阅发布包、Python 包、订阅服务 Docker 镜像发布，以及 agent 原生配置备份恢复。

## 技术方案

- `proxystack-agent sub export [stack]` 生成远端订阅服务可导入的发布包。
- 发布包内按 stack 写入 `inputs/<stack>.yaml`，支持全部 stack 或指定单个 stack 导出。
- `proxystack-agent` 可直接读取 inputs 目录并校验或预览合并结果。
- `proxystack-sub` Docker 镜像只包含订阅服务运行依赖。
- 原生备份 `export/import` 使用独立 `proxystack.native-backup` schema，只包含 config 和 stacks，不包含 runtime。
- P0 不支持旧 `clash`、`xrelay`、`clashsub` 或旧 `proxy-stack` 目录自动导入。

## 实现步骤

1. [x] 定义 `sub-bundle.zip` 版本元数据和校验规则。
2. [x] 定义 subscription input 文件 schema 和版本元数据。
3. [x] 实现 agent 从全部 stack 或指定 stack 生成 bundle 的 `sub export` 流程。
4. [x] 增加 Python wheel/sdist 构建脚本。
5. [x] 增加 `proxystack-sub` Dockerfile 和 Compose 示例。
6. [x] 增加端到端示例测试。
7. [x] 实现原生备份包 `export/import`，并明确不同于订阅发布包。

## 验收标准

- sub bundle 可包含客户端连接所需凭据，但不包含完整 stack、clash upstream、rules、mode 或 controller 配置。
- subscription input 可被多个文件合并，且不包含完整 stack。
- 同一批 subscription input 在 agent 和 sub 中的合并结果一致。
- 构建产物包含 `proxystack-agent` 和 `proxystack-sub` console scripts。
- Docker 镜像默认命令为 `proxystack-sub serve --config /data/config.yaml`。
- Docker 镜像文档明确 `/data` 必须挂载持久化 volume。
- agent 原生 `export/import` 只处理当前 proxystack 配置备份恢复，不接收订阅发布包。

## 依赖

Task 07、Task 08、Task 09。

## 风险

订阅发布包和原生备份包都需要写入版本元数据；后续 schema 升级时要能给出清晰兼容性错误。原生备份包不能和订阅发布包混用。

## P0 实现状态

- subscription input 使用 `input_schema: proxystack.subscription-input` 和 `input_version: 1`；缺少 schema 的 v1 文件按兼容输入读取。
- sub bundle manifest 使用 `bundle_schema: proxystack.sub-bundle` 和 `bundle_version: 1`，导入时校验 input hash、input schema 和合并冲突。
- `proxystack-agent sub export` 与 `proxystack-sub import/serve` 复用同一套 input schema 和合并逻辑。
- `scripts/build_package.py` 和 `make build` 生成 wheel 与 sdist；wheel 包含 `proxystack-agent` 和 `proxystack-sub` console scripts。
- Dockerfile 与 Compose 示例保留 `/data` volume 和订阅服务默认命令。
- 原生备份包结构记录在 `docs/m5-native-backup-package.md`，`proxystack-agent export/import` 已实现 config 和 stacks 迁移；runtime 由目标 agent 动态生成。
