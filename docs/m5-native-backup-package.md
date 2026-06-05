# M5 原生备份包结构预留

本文档只预留 M5 原生配置备份包结构，P0 不实现通用 `export/import` 命令，也不把原生备份包混入订阅发布包流程。

## 目标

- 保存可恢复 proxystack 本地 agent 配置所需的最小文件集合。
- 与 `sub-bundle.zip` 明确区分，避免订阅服务误导入完整 stack、clash upstream、rules、mode 或 controller 配置。
- 为 M5 阶段补充命令入口、签名、加密和回滚策略提供结构基础。

## 建议包结构

```text
proxystack-backup.zip
  manifest.json
  config/
    config.yaml
  stacks/
    <name>.yaml
  runtime/
    manifest.json
  notes/
    README.md
```

`runtime/manifest.json` 和 `notes/README.md` 为可选成员。备份包不包含 `.venv/`、`bin/`、`geo/`、`downloads/`、`publish/`、`sub/current/` 或 systemd unit 文件。

## manifest 草案

```json
{
  "backup_schema": "proxystack.native-backup",
  "backup_version": 1,
  "created_at": "2026-06-05T12:00:00+08:00",
  "source_host": "agent-host",
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
- 后续如支持敏感字段加密，应在 manifest 中声明加密算法和密钥来源，禁止把明文密钥写入日志。

## 与订阅发布包的区别

| 项目 | 订阅发布包 | 原生备份包 |
| --- | --- | --- |
| schema | `proxystack.sub-bundle` | `proxystack.native-backup` |
| 目标组件 | `proxystack-sub` | 本地 `proxystack-agent` |
| 内容 | subscription input 和访问控制 | config、stacks 和可选 runtime manifest |
| P0 状态 | 已实现 | 仅预留结构 |
