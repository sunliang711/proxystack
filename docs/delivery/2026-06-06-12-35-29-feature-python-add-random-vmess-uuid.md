# add 自动生成 vmess inbound UUID

## 背景

`ps-agent add` 使用 `pair` 内置模板时，xrelay vmess inbound 的 UUID 来自模板固定占位值。连续新增多个 stack 时会得到相同 UUID，不适合作为真实部署配置。

## 变更

- 内置模板加载后，自动把 xrelay vmess inbound 中的模板占位 UUID 替换为随机 UUID。
- 仅处理内置模板中的 xrelay vmess inbound；`--from-file` 输入文件保持原样。
- 不自动替换 clash raw upstream 的 UUID，因为该字段通常是远端代理服务凭据，不能随本地 add 随机改写。
- 更新 CLI 文档，说明 add 的 UUID 生成行为。

## 验证

- `/tmp/proxystack-test-venv/bin/python -m pytest tests/test_cli.py -q`
- `/tmp/proxystack-test-venv/bin/python -m pytest -q`
- `git diff --check`
