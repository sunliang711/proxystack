# 原生配置备份导入导出交付记录

## 变更摘要

- 新增 `proxystack-agent export`，导出 `proxystack.native-backup` 原生备份包。
- 新增 `proxystack-agent import`，导入原生备份包并默认拒绝覆盖既有 `config.yaml` 或同名 stack。
- 原生备份包只包含 `config/config.yaml`、`stacks/*.yaml` 和包级 `manifest.json`，不包含 `runtime`。
- 导入时校验 schema/version、zip 成员路径、sha256、config/stack schema 和跨 stack 引用，并限制 stacks 写入目录位于目标 `base_dir` 内。
- 更新 CLI 文档、原生备份包格式文档和 Task10 状态说明。

## 验证

```bash
.venv/bin/python -m pytest tests/test_cli.py::test_agent_lifecycle_command_help_is_available tests/test_cli.py::test_agent_native_backup_export_import_roundtrip tests/test_cli.py::test_agent_native_backup_import_refuses_existing_files_without_force tests/test_cli.py::test_agent_native_backup_import_rejects_subscription_bundle tests/test_cli.py::test_agent_native_backup_import_rejects_unsafe_member_path tests/test_cli.py::test_agent_native_backup_import_rejects_hash_mismatch tests/test_cli.py::test_agent_native_backup_import_rejects_stack_path_outside_base_dir -q
.venv/bin/python -m pytest tests/unit/test_task11_cli_matrix.py::test_agent_and_sub_p0_subcommand_help_matrix tests/test_sub_generator.py::test_extract_bundle_rejects_native_backup_schema -q
```
