# install 已安装目标跳过下载

## 背景

`ps-agent install` 重复执行时，即使目标二进制或 geo 数据已经存在，也会再次下载并替换。预期行为是 `install` 做幂等安装，只有 `update` 才强制重新下载。

## 变更

- `install_artifact` 在 `operation == "install"` 时先检查目标是否已安装。
- mihomo/xray 检查 `config.paths.bin` 下对应二进制文件。
- geo 检查 `config.paths.geo` 下已有 `.dat`、`.mmdb`、`.metadb` 文件。
- 已存在时返回 skipped 结果，并输出 `install: skip <target> already installed`。
- CLI 跳过结果输出为 `<target> install 跳过：已存在`，且不打印空 sha256。
- `update` 保持原有行为，即使目标存在也会下载并替换。

## 验证

- `/tmp/proxystack-test-venv/bin/python -m pytest tests/test_install.py -q`
- `/tmp/proxystack-test-venv/bin/python -m pytest -q`
- `git diff --check`
