# 订阅服务近期优先项增强

## 变更摘要

- `proxystack-agent sub export` 新增 `--summary` / `--dry-run` 预览模式，只输出发布包将包含的 input、node、user 统计，不写 zip。
- `proxystack-sub import` 成功后输出导入摘要，包含 source、input/node/user 数量、写入或覆盖的 input，以及 `--replace-all` 删除的旧 input。
- `proxystack-sub serve` 启动时记录 data_dir、input_dir、listen、access 类型、watch 参数、模板来源和已加载 input/source/node/user 统计。
- inputs reload 成功日志补充 `inputs=` 字段；reload 失败仍只输出错误类型并保留旧内存索引，避免日志泄露 token/password。
- 新增 `examples/sub-config.yaml`，覆盖 `data_dir`、`listen`、`access`、`templates_dir`、`watch_interval` 和 `watch_debounce`。
- 更新 CLI、生成规则、部署、测试矩阵和进度文档。

## 验证

```bash
PYTHONPATH=src /tmp/proxystack-test-venv/bin/python -m pytest -q tests/test_cli.py::test_agent_sub_export_summary_does_not_write_bundle tests/test_cli.py::test_sub_import_writes_bundle_inputs_only tests/test_cli.py::test_sub_serve_uses_config_access_and_memory_index tests/test_cli.py::test_sub_import_keeps_existing_inputs_by_default tests/test_cli.py::test_sub_import_replace_all_clears_existing_inputs tests/test_subserver.py::test_subscription_state_reload_writes_reload_logs tests/test_sub_generator.py::test_extract_bundle_rejects_duplicate_nodes_before_replacing_inputs
PYTHONPATH=src /tmp/proxystack-test-venv/bin/python -m compileall -q src tests
PYTHONPATH=src /tmp/proxystack-test-venv/bin/python -m pytest -q
git diff --check
```

结果：专项测试通过，compileall 通过，全量测试 `285 passed`，`git diff --check` 通过。
