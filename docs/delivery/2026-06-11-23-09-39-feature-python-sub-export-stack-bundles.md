# sub export 按 stack 导出订阅发布包

## 背景

原有订阅发布入口拆分为 `publish` 和 `sub export-input`，使用时需要区分发布包和 input 文件；`proxystack-sub import` 连续导入多个发布包时会清空旧 inputs，不适合多个 stack 或多个 agent 分批同步到同一个订阅服务。

## 变更

- 新增 `proxystack-agent sub export [stack]` 作为统一订阅发布包导出入口。
- 删除 agent 顶层 `publish` 和 `sub export-input` CLI 入口。
- `sub export` 缺省按 stack 拆分写入 `inputs/<stack>.yaml`，默认输出 `/opt/proxystack/publish/sub-bundle.zip`。
- `sub export <stack>` 只导出指定 stack，默认输出 `/opt/proxystack/publish/<stack>-sub-bundle.zip`。
- `proxystack-sub import` 默认增量导入发布包，覆盖同名 input，保留其它 input；运行中的 `serve` 由 watcher 自动 reload。
- 新增 `proxystack-sub import --replace-all`，用于清空旧 inputs 后全量替换。
- 订阅 access token 由 `ps-sub config.yaml` 管理，导入发布包不覆盖订阅服务 token。
- 更新 CLI、生成规则、部署、架构和测试矩阵文档。

## 验证

```bash
/tmp/proxystack-test-venv/bin/python -m pytest tests/test_cli.py tests/test_sub_generator.py tests/unit/test_task11_cli_matrix.py tests/e2e/test_task11_main_flow.py -q
/tmp/proxystack-test-venv/bin/python -m pytest -q
```

结果：`273 passed`。
