# Task 06: 订阅生成与 HTTP 服务

## 目标

基于 xrelay inbound 的 `sub: true` 生成订阅索引，并提供支持本地部署和 Docker 部署的 HTTP 订阅服务。

## 技术方案

- 新建 `src/proxystack/generator/sub` 生成 `index.json` 和 `sub-bundle.zip`。
- 新建 `src/proxystack/subserver` 提供 FastAPI 服务。
- 订阅服务启动时只读取合并后的 `current/index.json`，不直接解析 stack。
- 支持类似 `clashsub` 的 inputs 目录，agent 和 sub 共用同一套合并逻辑。
- 本地部署使用 Python venv + systemd；Docker 部署使用 volume 持久化 `/data`。
- 同机非 Docker 部署时，sub 只写 `/opt/proxystack/sub/inputs/`、`/opt/proxystack/sub/bundles/`、`/opt/proxystack/sub/current/`，不能写 agent 的 `runtime/`、`publish/`、`downloads/` 或 `stacks/`。
- 订阅 HTTP 默认支持 token 访问控制；`none` 只允许本地监听或显式风险确认。

## 实现步骤

1. 从编译模型筛选 `sub: true` 的 xrelay inbound。
2. 生成协议无关的订阅节点模型。
3. 实现 Clash、Premium Clash、Surge 渲染。
4. 实现 `proxystack-agent sub export-input --source <source> -o <source>.yaml`。
5. 实现 `proxystack-agent publish --source <source> -o sub-bundle.zip`。
6. 实现 `proxystack-agent publish --input-dir --source`，用于多 inputs 合并后生成发布包；实现 `--include-stack`，仅在用户显式传入时把当前 stack 生成的临时 input 一起合并。
7. 实现 `proxystack-sub import sub-bundle.zip`、发布包 hash 校验和默认自动 rebuild；`--no-rebuild` 作为高级选项。
8. 实现 `proxystack-sub rebuild`，扫描 inputs 目录并合并多个输入。
9. 实现 `proxystack-agent sub validate-inputs --input-dir`。
10. 实现 `proxystack-agent render sub --input-dir`。
11. 实现 `/health`、`/sub/:user`、`/premium_sub/:user`、`/surge_sub/:user`。
12. 实现 token query 或等价反向代理鉴权支持。
13. 实现 `proxystack-sub serve --host --port --data-dir`。
14. 增加 Dockerfile 和 Docker Compose 示例，包含非 root、只读 rootfs、`cap_drop: ALL` 和 healthcheck。
15. 增加 agent/sub 分离锁，避免 import/rebuild 和 agent publish 互相覆盖。
16. 增加用户不存在和空节点场景处理。

## 验收标准

- 订阅输出不包含任何 clash upstream/proxy/group/rules 信息。
- `sub: false` 的 inbound 不进入订阅。
- 客户端连接所需凭据可以进入订阅，例如 vmess uuid、shadowsocks password、socks/http auth。
- FastAPI TestClient 覆盖所有路由。
- 发布包不包含完整 stack、clash upstream、rules、mode 或 controller 配置。
- 多个 input 文件按文件名稳定合并。
- agent 和 sub 对同一 inputs 目录生成一致的合并结果。
- `publish --input-dir` 默认不包含当前 stack；传入 `--include-stack` 时才合并当前 stack 生成的临时 input。
- 重复 `node.id` 默认让 rebuild 失败，并输出冲突报告。
- 本地部署可通过 `proxystack-sub.service` 读取 `/opt/proxystack/sub/current`。
- Docker 部署可通过 `/data` volume 读取同一套 current 数据结构。
- Docker 容器不包含 mihomo、xray-core，也不管理 systemd。
- 同机部署测试覆盖 agent publish 后 sub import 默认 rebuild，不允许 agent 直接写 `sub/current`。
- 未携带有效 token 的订阅请求返回 401 或 403。

## 依赖

Task 02、Task 04。

## 风险

订阅模板容易把 server/port 与内部本机地址混淆；订阅必须使用 `global.external_host` 或 inbound 显式 server。
