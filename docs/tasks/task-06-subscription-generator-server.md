# Task 06: 订阅生成与 HTTP 服务

## 目标

基于 xrelay inbound 的 `sub: true` 生成订阅索引，并提供支持本地部署和 Docker 部署的 HTTP 订阅服务。

## 技术方案

- 新建 `src/proxystack/generator/sub` 生成 subscription input/index 和 `sub-bundle.zip`。
- 新建 `src/proxystack/subserver` 提供 FastAPI 服务。
- 订阅服务启动时扫描 inputs 目录并构建内存索引，运行中通过 watcher reload，不直接解析 stack。
- 支持类似 `clashsub` 的 inputs 目录，agent 和 sub 共用同一套合并逻辑。
- 本地部署使用 Python venv + systemd；Docker 部署使用 volume 持久化 `/data`。
- 同机非 Docker 部署时，sub 只写 `/opt/proxystack/sub/inputs/`，并读取 `/opt/proxystack/sub/config.yaml` 和可选模板目录，不能写 agent 的 `runtime/`、`publish/`、`downloads/` 或 `stacks/`。
- 订阅 HTTP 默认支持 token 访问控制；`none` 只允许本地监听或显式风险确认。

## 实现步骤

1. 从编译模型筛选 `sub: true` 的 xrelay inbound。
2. 生成协议无关的订阅节点模型。
3. 实现 Clash、Premium Clash、Surge 渲染。
4. 实现 `proxystack-agent sub export [stack] -o sub-bundle.zip`，缺省导出全部 stack，指定 stack 时只导出该 stack。
5. 实现 `proxystack-sub import sub-bundle.zip`、发布包 hash 校验和 inputs 增量导入；`--replace-all` 用于清空旧 inputs 后全量替换。
6. 实现 `proxystack-sub serve` 启动时扫描 inputs 目录并构建内存索引。
7. 实现 inputs 目录 watcher，文件增加、删除、保存完成或原子替换后 reload 内存索引。
8. 实现 `proxystack-sub serve` 从 ps-sub 配置读取 access token 和可选模板目录。
9. 实现 `proxystack-agent sub validate-inputs --input-dir`。
10. 实现 `proxystack-agent render sub --input-dir`。
11. 实现 `/health`、`/sub/:user`、`/premium_sub/:user`、`/surge_sub/:user`。
12. 实现 token query 或等价反向代理鉴权支持。
13. 实现 `proxystack-sub serve --host --port --data-dir`。
14. 增加 Dockerfile 和 Docker Compose 示例，包含非 root、只读 rootfs、`cap_drop: ALL` 和 healthcheck。
15. 增加 agent/sub 目录边界，避免 agent 直接写入 sub inputs。
16. 增加用户不存在和空节点场景处理。

## 验收标准

- 订阅输出不包含任何 clash upstream/proxy/group/rules 信息。
- `sub: false` 的 inbound 不进入订阅。
- 客户端连接所需凭据可以进入订阅，例如 vmess uuid、shadowsocks password、socks/http auth。
- FastAPI TestClient 覆盖所有路由。
- 发布包不包含完整 stack、clash upstream、rules、mode 或 controller 配置。
- 多个 input 文件按文件名稳定合并。
- agent 和 sub 对同一 inputs 目录生成一致的合并结果。
- `sub export` 缺省按 stack 拆分写入发布包中的 `inputs/<stack>.yaml`，指定 stack 时只包含该 stack。
- 重复 `node.id` 默认让启动或 reload 失败，并输出冲突报告；运行期 reload 失败时保留上一份可用内存索引。
- 本地部署可通过 `proxystack-sub.service` 读取 `/opt/proxystack/sub/config.yaml` 和 `/opt/proxystack/sub/inputs/`。
- Docker 部署可通过 `/data` volume 读取同一套 config、inputs 和可选 templates 数据结构。
- Docker 容器不包含 mihomo、xray-core，也不管理 systemd。
- 同机部署测试覆盖 agent `sub export` 后 sub import 写入 inputs，不允许 agent 直接写 `sub/inputs`。
- 未携带有效 token 的订阅请求返回 401 或 403。

## P0 实现状态

已完成：

- `src/proxystack/generator/sub` 支持从 enabled stack 的 `sub: true` inbound 生成 subscription input、扫描合并 inputs、生成 index、渲染 Clash/Premium Clash/Surge，并生成/校验 `sub-bundle.zip`。
- `proxystack-agent render sub`、`sub validate-inputs`、`sub export [stack]` 已接入。
- `proxystack-sub import`、`serve` 已接入；服务启动时读取 `<data_dir>/inputs/` 到内存，请求只读取内存索引。
- FastAPI 路由 `/health`、`/sub/{user}`、`/premium_sub/{user}`、`/surge_sub/{user}` 已实现 token query 鉴权、模板渲染和统一 JSON 错误。
- 已新增 Dockerfile 和 Docker Compose 示例，容器不包含 mihomo/xray-core。
- 运行中的 `serve` 会监控 inputs 目录，Linux 优先使用 inotify，不可用时回退轮询。

后续任务：

- 更完整的运行状态命令留到后续生命周期管理任务中实现。

## 依赖

Task 02、Task 04。

## 风险

订阅模板容易把 server/port 与内部本机地址混淆；订阅必须使用 `global.external_host` 或 inbound 显式 server。
