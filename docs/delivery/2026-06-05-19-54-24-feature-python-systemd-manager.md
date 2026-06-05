# Task 09 交付记录：systemd 服务管理 P0

## 变更摘要

- 新增 `src/proxystack/systemd`，封装 systemd unit 生成、安装/卸载、`systemctl` 和 `journalctl` 调用。
- 新增 `proxystack-agent service install|uninstall|enable|disable|start|stop|restart|status|log`。
- 顶层 `up/down/restart/status/logs/enable/disable` 已接入真实 systemd runner；`up` 会先写入代理生成文件，再只重启本次变化影响到的目标服务。
- `up sub`、`service <action> sub` 只作用于 `proxystack-sub.service`，不读取或改写 stack 文件。
- 更新 CLI、部署、进度和任务文档。

## 关键边界

- `service install|uninstall` 是唯一 systemd unit 文件安装卸载入口；`install/update` 分组不提供 unit 安装命令。
- xray/clash unit 只引用 `runtime/generated` 下的实例配置文件，不把 `config.yaml` 或 `stacks/*.yaml` 传给运行服务。
- xray/clash unit 只允许写 agent runtime 相关目录；sub unit 只允许写订阅数据目录。
- `systemctl` 和 `journalctl` 均通过参数数组调用；非零退出码会展示 stdout/stderr 摘要。
- `service log --follow/-f` 对真实命令使用流式输出，测试仍通过 fake runner 隔离外部命令。
- `service uninstall` 只删除 unit 文件并执行 `daemon-reload`，不删除 `/opt/proxystack/config.yaml` 或 `stacks/*.yaml`。

## 测试情况

- 已新增 `tests/test_systemd.py`。
- 已扩展 `tests/test_cli.py`。
- 已覆盖 unit hardening、ExecStart、ReadWritePaths、fake unit_dir 安装卸载、fake runner 生命周期命令、`up sub` 不扫描 stack、`install/update` 分组无 unit 安装入口、非零命令错误摘要和 `journalctl -f` 流式执行。
