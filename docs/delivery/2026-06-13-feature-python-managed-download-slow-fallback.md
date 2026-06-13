# 托管下载源慢速自动切换

## 变更摘要

- `ps-agent setup`、`install mihomo|xray`、`update mihomo|xray` 使用 `source: auto` 时，首个托管源下载速度过慢会自动切换到下一个源。
- 慢速判定沿用 `../clash/download.py` 的默认策略：预热 10 秒后平均速度低于 200 KiB/s 时中断当前源。
- 慢速切换只作用于 `mihomo` 和 `xray` 的 `auto` 模式；显式 `github`/`r2` 或最后一个候选源不因慢速阈值中断。
- CLI 下载进度新增 `download: slow ...` 提示，便于 setup 时观察切源原因。

## 验证

- `.venv/bin/python -m pytest tests/test_install.py -q`
- `.venv/bin/python -m pytest -q`
