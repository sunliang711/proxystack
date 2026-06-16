# 功能开发：订阅 path token 路由

## 实现方案

- 影响范围：订阅 HTTP 服务路由、Surge 托管配置自引用 URL、当前接口文档和默认配置注释。
- 入口类型：HTTP。
- 核心流程：保留旧的 `/sub/:user?token=<token>`、`/premium_sub/:user?token=<token>`、`/surge_sub/:user?token=<token>`；新增推荐路由 `/sub/:token/:user`、`/premium_sub/:token/:user`、`/surge_sub/:token/:user`，让最后路径段继续作为客户端文件名。
- 数据与依赖变更：无。
- 配置项变更：无；仅更新配置注释中 Surge 托管配置路由说明。
- 风险与验证方式：新增路由复用原有 token 校验和渲染逻辑，风险低；通过 TestClient 覆盖新旧路由成功和错误 token 场景。

## 变更摘要

- 新增文件：`docs/delivery/2026-06-16-20-32-05-feature-python-sub-path-token-route.md`。
- 修改文件：`src/proxystack/subserver/app.py`、`src/proxystack/subserver/config.py`、`src/proxystack/templates/sub-config.yaml`、`tests/test_subserver.py`、`docs/cli.md`、`docs/generation.md`、`docs/architecture.md`、`docs/reference-projects.md`、`docs/config-spec.md`。
- 新增接口：`GET /sub/:token/:user`、`GET /premium_sub/:token/:user`、`GET /surge_sub/:token/:user`。
- 配置或依赖变更：无。
- 测试情况：`.venv/bin/python -m pytest -q tests/test_subserver.py tests/test_cli.py::test_sub_config_creates_default_config tests/test_cli.py::test_sub_serve_uses_config_access_and_memory_index tests/e2e/test_task11_main_flow.py`，结果 `20 passed, 1 skipped`；`git diff --check` 通过。全量 `.venv/bin/python -m pytest -q` 结果为 `1 failed, 333 passed, 1 skipped`，失败项是 `tests/golden/test_subscription_golden.py::test_subscription_formats_match_golden`，原因是当前 Surge 模板输出包含 WireGuard 占位符但 golden 未同步，和本次路由改动无关。

## 自检清单

- [x] 分层清晰，入口层仅复用已有渲染和鉴权逻辑。
- [x] 输入校验和错误处理沿用原有 token 校验。
- [x] 配置、凭据、路径未硬编码。
- [x] 日志未新增敏感信息。
- [x] 无事务、分页或新增资源生命周期。
- [x] 测试覆盖核心路径并可运行。
