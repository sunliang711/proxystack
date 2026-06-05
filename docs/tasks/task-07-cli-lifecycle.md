# Task 07: CLI 生命周期命令

## 目标

实现 `init`、`add/edit/list/remove/clone/check/up/down/restart/status/logs/enable/disable/publish/doctor` 常用命令，以及 `validate`、`plan`、`apply`、`render` 高级命令。

## 技术方案

- Typer 命令按模块拆分。
- `plan` 和 `apply` 共用编译流程。
- `apply` 只写入生成文件和 manifest，不启动、不停止、不重启服务。
- 常用命令作为高级命令的安全包装，默认覆盖全部启用实例，传入目标时只操作指定实例或组件。
- `up` 是 `validate + apply + service start/restart changed` 的常用包装。

## 实现步骤

1. 实现全局 `-c/--config` 参数，默认 `/opt/proxystack/config.yaml`。
2. 实现 `init` 创建 `/opt/proxystack`、`config.yaml` 和 `stacks/`。
3. 实现 `validate` 输出校验结果。
4. 实现 `render` 输出中间模型、Xray JSON、mihomo YAML、sub index。
5. 实现 `plan` 对比 manifest 和将生成文件。
6. 实现 `apply` 写文件和 manifest。
7. 实现 `add` 使用默认模板或 `--from-file` 创建 `stacks/<name>.yaml`，支持 `--allocate-ports` 和 auto 模板的 `--members`。
8. 实现 `edit [name]` 打开 `config.yaml` 或指定 stack 文件，保存后校验并写回。
9. 实现 `clone <source> <target>` 复制已有 stack 文件为新 stack，支持 `--allocate-ports` 基于端口池重分配监听端口。
10. 实现 `list`、`remove`、`check`、`up`、`down`、`restart`、`status`、`logs`、`enable`、`disable`、`publish`、`doctor` 常用包装命令。

## 验收标准

- 所有命令有 `--help`。
- `plan` 不写任何运行时文件。
- `apply` 幂等，第二次执行不改写未变化文件，也不触发服务操作。
- `up` 只启动或重启目标范围内受 manifest 影响的服务。
- `add` 不覆盖已有 stack 文件。
- `clone` 默认不自动修改端口，复制结果必须经 `validate`；传入 `--allocate-ports` 时必须写入新的可用端口。
- `up/down/restart/status/logs/enable/disable` 不传目标时操作全部 enabled stack；传 `usa1`、`xrelay/usa1`、`clash/usa1` 或 `sub` 时只操作目标范围。
- `edit <name>` 编辑 `/opt/proxystack/stacks/<name>.yaml`，不能破坏 YAML 结构；保存后必须先校验再替换原文件。
- agent 运行期命令不写 `config.yaml`；只有 `init` 和 `edit` 可以写 `config.yaml`。
- `doctor` 能报告目录权限、缺失二进制、systemd unit 缺失和端口占用。

## 依赖

Task 04、Task 05、Task 06。

## 风险

编辑 YAML 时要保留用户可读性；首期以整文件编辑 `config.yaml` 或单个 stack 文件为主。
