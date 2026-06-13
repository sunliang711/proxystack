# Xray outbound tag 使用 stack 名

## 变更摘要

- 将运行时 Xray `outbounds[].tag` 从固定 `proxy` 改为 `egress-{stack}`。
- `clash`、`socks5`、`http` 和 `direct` outbound 统一使用同一命名规则。
- 更新 Xray golden 文件和文档说明，便于日志与 stats 中按 stack 区分出口。

## 验证

- `.venv/bin/python -m pytest tests/test_xray_generator.py -q`
- `.venv/bin/python -m pytest -q`
