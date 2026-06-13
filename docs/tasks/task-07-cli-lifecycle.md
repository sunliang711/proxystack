# Task 07: CLI 生命周期命令

## 目标

实现 `init`、`add/config/list/remove/clone/check/start/stop/restart/status/logs/enable/disable/doctor` 常用命令，以及 `validate`、`render` 和 `sub export` 高级命令。

## 技术方案

- Typer 命令按模块拆分。
- `check` 和 `start` 共用编译流程。
- `check` 只展示生成文件和 manifest 变化预览，不启动、不停止、不重启服务。
- 常用命令作为高级命令的安全包装，默认覆盖全部启用实例，传入目标时只操作指定实例或组件。
- `start` 是生成配置、写入 manifest 并启动或重启目标服务的常用包装。
- Task07 阶段只接入可测试的 service adapter 输出，不调用 `systemctl`，真实 systemd 安装和执行留给 Task09。

## 实现状态

- 已实现 `init`、`add`、`config`、`list`、`remove`、`clone`、`check`、`start`、`stop`、`restart`、`status`、`logs`、`enable`、`disable`、`doctor`。
- 已实现 `validate [target]`、`render model`、`render xrelay`、`render clash`、`render sub`。
- `check` 只展示文件变更和依赖顺序，不写运行目录。
- `start` 写入 `runtime/generated` 下的生成文件和 `manifest.json`，内容未变化时不改写文件，并通过 systemd 启动或重启目标服务。
- `start/stop/restart/status/logs/enable/disable` 默认跳过系统端口占用检查，避免运行中的自身服务阻断生命周期命令。

## 实现步骤

1. 实现全局 `-c/--config` 参数，默认 `/opt/proxystack/config.yaml`。
2. 实现 `init` 创建 `/opt/proxystack`、`config.yaml` 和 `stacks/`。
3. 实现 `validate` 输出校验结果。
4. 实现 `render` 输出中间模型、Xray JSON、mihomo YAML、sub index。
5. 实现 `check` 对比 manifest 和将生成文件。
6. 实现 `start` 写文件、更新 manifest 并启动或重启服务。
7. 实现 `add` 使用默认模板或 `--from-file` 创建 `stacks/<name>.yaml`，默认自动分配端口，并支持 auto 模板的 `--members`。
8. 实现 `config [name]` 打开 `config.yaml` 或指定 stack 文件，保存后校验并写回。
9. 实现 `clone <source> <target>` 复制已有 stack 文件为新 stack，支持 `--allocate-ports` 基于端口池重分配监听端口。
10. 实现 `list`、`remove`、`check`、`start`、`stop`、`restart`、`status`、`logs`、`enable`、`disable`、`doctor` 常用包装命令，以及 `sub export` 订阅发布包导出命令。

## 验收标准

- 所有命令有 `--help`。
- `check` 不写任何运行时文件。
- `start` 幂等，第二次执行不改写未变化文件。
- `start` 启动目标范围内服务，配置变化时重启受 manifest 影响的服务，并启动目标范围内未变化的服务。
- `add` 不覆盖已有 stack 文件。
- `clone` 默认不自动修改端口，复制结果必须经 `validate`；传入 `--allocate-ports` 时必须写入新的可用端口。
- `start/stop/restart/status/logs/enable/disable` 不传目标时操作全部 enabled stack；传 `usa1`、`xrelay/usa1`、`clash/usa1` 或 `sub` 时只操作目标范围。
- `config <name>` 编辑 `/opt/proxystack/stacks/<name>.yaml`，不能破坏 YAML 结构；保存后必须先校验再替换原文件。
- agent 运行期命令不写 `config.yaml`；只有 `init` 和 `config` 可以写 `config.yaml`。
- `doctor` 能报告目录权限、缺失二进制、systemd unit 缺失和端口占用。

## 依赖

Task 04、Task 05、Task 06。

## 风险

编辑 YAML 时要保留用户可读性；首期以整文件编辑 `config.yaml` 或单个 stack 文件为主。
