# Task06 订阅生成与 HTTP 服务交付记录

> 历史记录：本次交付中的 `publish`、`sub export-input`、`rebuild` 和 `current/index.json` 模型已被后续实现替换；当前用法以 `docs/cli.md`、`docs/generation.md` 和 `proxystack-agent sub export`、`proxystack-sub import/serve` 为准。

## 交付范围

- 新增 `src/proxystack/generator/sub`，实现订阅 input schema、index schema、stack input 生成、inputs 扫描合并、重复 node.id 冲突检测、Clash/Premium Clash/Surge 订阅渲染，以及 `sub-bundle.zip` manifest/hash 校验。
- 更新 `proxystack-agent`，新增 `render sub`、`sub export-input`、`sub validate-inputs` 和 `publish`。
- 更新 `proxystack-sub`，新增 `import`、`rebuild` 和 `serve`；`rebuild` 原子写入 `<data_dir>/current/index.json`。
- 新增 `src/proxystack/subserver` FastAPI 服务，提供 `/health`、`/sub/{user}`、`/premium_sub/{user}`、`/surge_sub/{user}`，请求只读取 `current/index.json`。
- 新增 `Dockerfile.sub` 和 `docker-compose.sub.yml`，示例包含非 root、只读 rootfs、`cap_drop: ALL` 和 healthcheck，不包含 mihomo/xray-core。

## 关键规则

- 订阅节点只来自 enabled stack 中 enabled xrelay 的 `sub: true` inbound。
- `server` 默认使用 `global.external_host`，允许 inbound 显式 `server` 覆盖。
- input/index 不读取也不输出完整 stack、clash upstream、proxy group、rules、mode 或 controller 配置。
- inputs 支持 `.yaml`、`.yml`、`.json`，按文件名稳定合并，重复 `node.id` 默认失败。
- `publish --input-dir` 默认不包含当前 stack；只有显式 `--include-stack` 才合并当前 stack 生成的临时 input。
- HTTP token 鉴权由 `current/index.json` 中的 `access` 驱动；缺失 token 返回 401，错误 token 返回 403，用户不存在或空节点返回 404。

## 测试结果

- `make test PYTHON=.venv/bin/python`：通过，87 个测试。
- `make lint PYTHON=.venv/bin/python`：通过。
- `make build PYTHON=.venv/bin/python`：通过。
- `git diff --check`：通过。

## 残余事项

- systemd 生命周期管理不在本次范围内。
- agent/sub 分离锁和运行状态命令留给后续生命周期管理任务实现。
