# 原生备份包结构

本文档定义 `proxystack-agent export/import` 使用的原生配置备份包结构。原生备份包只用于 agent 到另一个 agent 的配置迁移，不和订阅发布包流程混用。

## 目标

- 保存可恢复 proxystack 本地 agent 配置所需的最小文件集合。
- 与 `sub-bundle.zip` 明确区分，避免订阅服务误导入完整 stack、clash upstream、rules、mode 或 controller 配置。
- 为后续签名、加密和回滚策略提供结构基础。

## 包结构

```text
proxystack-backup.zip
  manifest.json
  config/
    config.yaml
  stacks/
    <name>.yaml
```

备份包不包含 `runtime/`、`runtime/generated/`、`.venv/`、`bin/`、`geo/`、`downloads/`、`publish/`、`sub/inputs/`、`sub/templates/` 或 systemd unit 文件。`runtime` 属于派生运行状态，可以由 `check/start/render` 根据 config 和 stacks 重新生成；订阅 inputs 和模板属于 `proxystack-sub` 运行数据，不随 agent 原生备份包迁移。

## manifest

```json
{
  "backup_schema": "proxystack.native-backup",
  "backup_version": 1,
  "created_at": "2026-06-05T12:00:00+08:00",
  "files_sha256": {
    "config/config.yaml": "...",
    "stacks/usa1.yaml": "..."
  }
}
```

## 校验边界

- `backup_schema` 必须是 `proxystack.native-backup`，不得使用 `proxystack.sub-bundle`。
- zip 成员只允许相对路径，必须拒绝绝对路径、反斜杠、`..` 和未知目录。
- 恢复前必须先用现有 config/stack schema 校验全部 YAML。
- 文件 hash 必须与 manifest 一致。
- 导入后 `base_dir` 默认改写为目标 `config.yaml` 所在目录；也可以通过 `--base-dir` 显式指定。
- 导入写入的 stacks 目录必须位于目标 `base_dir` 下。
- 后续如支持敏感字段加密，应在 manifest 中声明加密算法和密钥来源，禁止把明文密钥写入日志。

## 与订阅发布包的区别

| 项目 | 订阅发布包 | 原生备份包 |
| --- | --- | --- |
| schema | `proxystack.sub-bundle` | `proxystack.native-backup` |
| 目标组件 | `proxystack-sub` | 本地 `proxystack-agent` |
| 内容 | subscription input 和访问控制 | config 和 stacks |
| 状态 | 已实现 | 已实现 |
