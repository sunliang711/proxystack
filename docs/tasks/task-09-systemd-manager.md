# Task 09: systemd 服务管理

## 目标

实现 systemd 模板安装和服务生命周期管理。

## 技术方案

- 新建 `src/proxystack/systemd`。
- systemd 操作通过接口封装，便于测试。
- 服务单元只引用生成后的配置文件路径。
- 默认使用 `proxystack:proxystack` 用户和用户组运行服务，并启用基础 hardening。
- systemd unit 安装入口统一为 `proxystack-agent service install [target]`，卸载入口统一为 `proxystack-agent service uninstall [target]`；不在 `install` 分组中提供 unit 相关子命令。

## 实现步骤

1. [x] 生成 `ps-xray@.service`。
2. [x] 生成 `ps-clash@.service`。
3. [x] 生成 `ps-sub.service`，只传入 sub 的 `--data-dir`、host 和 port，不读取 agent 的 stack 配置。
4. [x] 实现 `service install/uninstall`，支持 `sub` 目标，便于 sub-only 机器只安装订阅服务 unit。
5. [x] 实现 enable/disable/start/stop/restart/status/log。
6. [x] 支持目标选择：全部、实例对、单组件、sub。
7. [x] 在 unit 中加入 `User`、`Group`、`NoNewPrivileges`、`ProtectSystem`、`ProtectHome`、`PrivateTmp` 和按组件拆分的 `ReadWritePaths`。

## 验收标准

- `service status` 能展示实例对和单组件状态。
- `service log` 代理 `journalctl`，支持 follow 和非 follow。
- `service install|uninstall` 是唯一的 systemd unit 安装卸载入口。
- xray/clash unit 只能写 agent runtime 相关目录，sub unit 只能写 `/opt/proxystack/sub`。
- `up sub` 只影响 `ps-sub.service`，不会读取或改写 stack 文件。
- 单元测试不调用真实 systemctl。
- uninstall 不删除 `/opt/proxystack/config.yaml` 和 `stacks/*.yaml`，除非显式 purge。

## P0 实现状态

- 新增 `src/proxystack/systemd` 服务层，支持 fake runner 和 fake unit_dir。
- `service install|uninstall` 是唯一 unit 文件安装卸载入口；`install/update` 分组仍只负责代理核心和 geo 数据。
- `service log` 代理 `journalctl`，支持 `--follow/-f`。
- 顶层 `down/restart/status/logs/enable/disable` 已接入 systemd runner。
- 顶层 `up` 对普通代理目标先 `apply`，再只 restart 本次变化影响且在目标范围内的服务；`up sub` 只 restart `ps-sub.service`，不读取或改写 stack 文件，也不创建 `runtime/generated`。
- `systemctl` 和 `journalctl` 通过参数数组调用；非零退出码抛出错误并包含 stdout/stderr 摘要；`journalctl -f` 直接流式输出。

## 依赖

Task 07。

## 风险

systemd 命令需要 root 权限；CLI 要给出清晰提示，不要吞掉权限错误。
