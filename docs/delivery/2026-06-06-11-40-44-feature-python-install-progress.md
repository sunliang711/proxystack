# install/update 进度输出交付说明

## 变更摘要

- 为 `ps-agent install` 和 `ps-agent update` 增加 stderr 进度输出。
- 下载托管源时展示来源解析、候选源尝试、下载字节进度、来源选择和失败回退信息。
- 安装过程展示 prepare、verify、install、complete 阶段。
- 服务层默认保持静默，只有 CLI 传入 progress 回调时输出进度。

## 核心规则

- 本地文件安装会显示来源、校验和安装阶段。
- 远端下载已知 `Content-Length` 时显示已下载大小、总大小和百分比。
- 远端下载未知总大小时显示已下载大小。
- 自定义 fake downloader 仍按原有签名工作，不强制输出进度。

## 验证方式

- `/tmp/proxystack-test-venv/bin/python -m pytest tests/test_install.py -q`
- `/tmp/proxystack-test-venv/bin/python -m pytest -q`
- `git diff --check`
