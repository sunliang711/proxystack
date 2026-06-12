# Task11 测试矩阵与端到端验证 P0 交付记录

> 历史记录：本次记录中的 `publish`、`import --no-rebuild`、`rebuild/current` 流程已被后续实现替换；当前测试矩阵以 `docs/testing-matrix.md` 为准。

## 变更摘要

- 建立 `tests/unit`、`tests/fixtures`、`tests/e2e` 目录结构，保留原有平铺测试文件不搬动。
- 新增订阅 fixture 和 `tests/golden/sub/` 快照，固化 subscription input、index、Clash、Premium Clash 和 Surge 输出。
- 新增 Task11 增量单元测试，覆盖示例 stack 独立加载、必填凭据缺失、`add` 默认端口写回、P0 子命令 help、`validate` 失败路径、`import --no-rebuild`、rebuild 原子替换、fake `serve`、Docker Compose 安全配置、agent/sub 写入边界和锁隔离文档。
- 新增端到端主流程测试，覆盖 `init -> add -> validate -> plan -> apply -> up -> publish -> sub import -> serve`，并通过 fake systemd runner 和 fake uvicorn 避免真实系统服务或网络监听。

## 验证

```bash
.venv/bin/python -m pytest -q
make lint
git diff --check
```

测试不调用真实 `systemctl`、`journalctl`、真实网络下载、真实 Docker/systemd/root 权限。

## 风险

- Task11 当前自动化验证 Docker Compose/Dockerfile 配置文本，不启动真实 Docker 容器；真实容器运行仍按部署文档作为手工验收。
- agent/sub 锁路径目前是文档约束测试，后续如果实现真实锁文件，需要补运行期锁行为测试。
