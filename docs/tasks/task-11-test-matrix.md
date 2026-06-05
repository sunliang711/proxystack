# Task 11: 测试矩阵与端到端验证

## 目标

建立覆盖配置、生成器、CLI、systemd、订阅服务和 Docker 部署的测试矩阵，保证 P0 能按文档进入实现和验收。

## 技术方案

- 单元测试使用 pytest、fixture、mock 和 fake adapter。
- 生成器使用 golden tests 固化 Xray JSON、mihomo YAML、subscription input 和订阅输出。
- systemd、下载器、文件系统和外部命令通过接口抽象，测试中不得调用真实 `systemctl`、`journalctl` 或网络下载。
- 订阅 HTTP 使用 FastAPI TestClient。
- Docker 部署验证以 Compose 配置、容器命令和持久化目录结构为主，P0 可先使用文档化手工验收步骤。

## 实现步骤

1. [x] 建立测试目录结构：`tests/unit`、`tests/golden`、`tests/fixtures`、`tests/e2e`。
2. [x] 覆盖 `examples/config.yaml` 和 `examples/stacks/*.yaml` 的加载与校验。
3. [x] 覆盖非法配置：端口冲突、ref 缺失、循环依赖、危险 socks/http 暴露、必填凭据缺失、重复订阅 node id。
4. [x] 覆盖 `add` 默认端口分配和 `clone --allocate-ports` 的端口池分配写回行为。
5. [x] 覆盖 Xray、mihomo、subscription 生成器 golden 输出。
6. [x] 覆盖 `plan/apply/up` 的职责边界：`plan` 不写文件，`apply` 不操作服务，`up` 才启动或重启变化服务。
7. [x] 覆盖订阅发布包 import 默认 rebuild、`--no-rebuild` 跳过 rebuild、current 原子切换。
8. [x] 覆盖 agent/sub 同机部署目录边界；锁隔离作为文档化手工验收项保留。
9. [x] 覆盖订阅 HTTP token 鉴权、无用户、空节点和三类订阅格式。
10. [x] 覆盖 Docker Compose 示例的关键安全配置：非 root、只读 rootfs、`cap_drop: ALL`、持久化 `/data`、healthcheck。

## 验收标准

- `pytest` 能在无 root、无 systemd、无真实代理核心二进制的环境中通过。
- golden tests 变更必须显式更新快照，不能由普通格式化命令误改。
- 所有 P0 命令至少有 help 测试和一条成功/失败路径测试。
- 端到端测试覆盖 `init -> add -> validate -> plan -> apply -> up -> publish -> sub import -> serve` 的主流程。
- 测试夹具使用示例明文凭据，不使用真实生产凭据。

## 依赖

Task 01、Task 02、Task 06、Task 07、Task 09。

## 风险

systemd 和 Docker 在 CI 中可能不可用；需要把自动化测试和手工验收步骤分开，不把环境限制混进业务测试。

## P0 实现状态

- 已建立 `tests/unit`、`tests/golden`、`tests/fixtures`、`tests/e2e` 目录结构；现有 `tests/test_*.py` 未搬动。
- 已补充 Task11 增量测试，覆盖示例 stack 独立加载、必填凭据缺失、`add` 默认端口写回、订阅 input/index/格式 golden、`proxystack-sub import --no-rebuild` 和 rebuild 原子替换、fake `serve` 成功路径、Docker Compose 安全配置、agent/sub 目录边界和锁路径文档约束。
- 已补充端到端主流程测试：`init -> add -> validate -> plan -> apply -> up -> publish -> sub import -> serve`，通过 fake systemd runner 和 fake uvicorn 隔离真实系统服务和网络监听。
- 既有测试继续覆盖 Xray/mihomo golden、非法配置端口/ref/循环依赖、plan/apply/up 边界、订阅 HTTP token/无用户/空节点/三类格式、订阅发布包 schema/hash/path 安全。
- 自动化测试不调用真实 `systemctl`、`journalctl`、真实网络下载、真实 Docker/systemd/root 权限。
