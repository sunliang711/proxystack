# Task07 CLI 生命周期命令交付记录

## 交付范围

- 新增 `src/proxystack/cli/lifecycle.py`，承载 `init/add/clone/list/remove/edit/check/plan/apply/doctor` 等生命周期命令的支撑逻辑。
- 更新 `proxystack-agent`，新增 `init`、`add`、`edit`、`list`、`remove`、`clone`、`check`、`apply`、`up`、`down`、`restart`、`status`、`logs`、`enable`、`disable`、`doctor` 和 `render model`。
- `plan` 输出生成文件 create/update/delete/unchanged 视图、受影响服务和依赖操作顺序，不写运行目录。
- `apply` 写入 `runtime/generated` 下的 Xray JSON、mihomo YAML、订阅 input/index 和 `manifest.json`，内容未变化时不改写文件。
- `up` 默认执行 `apply`，并通过 service adapter 输出目标范围内本次受文件变化影响的服务；`--dry-run` 只展示目标服务动作。
- `down/restart/status/logs/enable/disable` 支持全部、stack、组件和 `sub` 目标选择，Task07 阶段只输出 service adapter 动作。

## 关键规则

- `add` 不覆盖已有 stack，支持内置模板、`--from-file`、`--members` 和 `--allocate-ports`。
- `add/clone/edit` 写入前会做全局 stack 校验，避免留下 ref、重复端口或安全策略无效的配置。
- `clone` 默认不改端口；如果候选配置无法通过全局校验则拒绝写入。`clone --allocate-ports` 基于 `config.port_ranges` 分配当前配置未声明且系统未占用的端口。
- `remove --purge` 删除该 stack 对应的生成文件，并从 manifest 中移除对应记录。
- `edit` 使用临时文件调用编辑器，校验通过后再替换原文件；`--check-only` 只校验不启动编辑器。
- 生命周期服务命令默认跳过系统端口占用检查，不会调用 `systemctl`，也不会写 `/etc/systemd/system`；真实 systemd 接入留给 Task09。
- agent 运行期命令不写 `config.yaml`；只有 `init` 和 `edit` 会写配置文件。

## 测试结果

- `tests/test_cli.py` 新增覆盖生命周期 help、`init/add/clone/check/plan/apply/render model/remove/doctor/up` 和 service target selection。
- `plan` 通过测试确认不写 `runtime/generated`。
- `apply` 通过测试确认第二次执行输出 0 个文件变化，并保持 manifest mtime 不变。

## 残余事项

- systemd unit 安装、卸载、真实启停、状态查询和日志读取留给 Task09。
- install/update 下载和升级流程留给 Task08。
