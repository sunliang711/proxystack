# 远端全流程测试与修复交付说明

## 变更摘要

- 在 `10.2.7.195` 使用 root 免密 SSH 完成非 Docker 全流程测试。
- 通过项目安装命令真实下载并安装 `mihomo` 和 `xray`，并验证 systemd 服务真实启动。
- 修复 `status` 查询 inactive 服务时被 systemd 退出码 3 误判为失败的问题。
- 修复 `sub export-input` 在服务运行时被自身监听端口阻断的问题。

## Bug 定位分析

- 问题现象：停止单个 xray 实例后，`ps-agent status xrelay/usa1` 报“服务操作失败”，无法展示 inactive 状态。
- 根因位置：`src/proxystack/systemd/service.py` 对所有 `systemctl` 非零退出码统一抛错，未区分 `systemctl status` 的 inactive 返回码 3。
- 修复方式：仅对 `status` 动作允许退出码 3，并继续展示 stdout；其他动作仍保持失败抛错。
- 影响范围：`ps-agent status` 与 `ps-agent service status`。

## 订阅导出问题

- 问题现象：代理服务运行后执行 `ps-agent sub export-input`，端口检查把自身已监听端口判定为冲突。
- 根因位置：`src/proxystack/cli/agent.py` 中 `export-input` 默认启用系统端口检查，与 `publish` 默认跳过运行中服务端口的行为不一致。
- 修复方式：`export-input` 默认跳过系统端口检查，并保留 `--check-system-ports/--skip-system-ports` 显式开关。
- 影响范围：`proxystack-agent sub export-input`。

## 验证方式

- 本地：`/tmp/proxystack-test-venv/bin/python -m pytest -q`，结果 `216 passed`。
- 远端：`scripts/install-agent.sh --source /tmp/proxystack-src --install-systemd`。
- 远端：`ps-agent install mihomo`、`ps-agent install xray`、`ps-agent update mihomo`、`ps-agent update xray`。
- 远端：`ps-agent start/status/restart/stop/enable/disable` 覆盖 stack、组件和 sub 目标。
- 远端：`ps-agent publish`、`ps-sub import`、`ps-sub rebuild`、`ps-agent start sub`、HTTP health 与订阅接口请求。
- 远端：`ps-agent ipinfo usa1 --family ipv4` 通过 mihomo socks 完成真实出口查询。
