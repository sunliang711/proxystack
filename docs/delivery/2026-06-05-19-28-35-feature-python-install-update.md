# Task 08 交付记录：下载安装与更新 P0 候选版

## 变更摘要

- 新增 `src/proxystack/install`，提供安装请求/结果 dataclass、下载与本地源读取、sha256 校验、zip/tar 抽取、原子替换、权限设置、组件版本检测和 self update。
- 扩展 `config.install`，支持 `mihomo/xray/geo` 的 `version`、`source`、`sha256` 和 `archive_member`。
- 新增 `proxystack-agent install mihomo|xray|geo|all` 和 `proxystack-agent update mihomo|xray|geo|all|self`。
- 扩展 `proxystack-agent version [mihomo|xray|geo]`。
- 更新 CLI、部署、进度和任务文档。

## 关键边界

- `install all` 和 `update all` 只包含 `mihomo/xray/geo`，不包含 `self`，不安装 systemd unit。
- `update self` 只调用 venv 内 `python -m pip install --upgrade`，不更新代理核心。
- 远端下载必须提供 sha256，生产下载路径拒绝本机/私网地址、DNS 私网解析和 HTTP 重定向。
- 校验或替换失败不会覆盖既有目标文件；geo 多文件归档替换失败会回滚本次已替换文件。
- P0 只输出 service adapter 文本计划，不真实调用 `systemctl`，不写 `/etc/systemd/system`。

## 测试情况

- 已新增 `tests/test_install.py`。
- 已覆盖本地文件安装、fake downloader、远端缺 sha256、私网 URL 拒绝、sha256 失败、单文件和 geo 多文件替换失败保护旧文件、归档路径穿越拒绝、self update fake runner、install/update all 不包含 self、help 输出。
