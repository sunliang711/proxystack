# Task10 发布构建与订阅包交付记录

## 变更摘要

- 补强 subscription input 和 sub bundle 的 schema/version 元数据，并在导入发布包时校验 bundle 内 input 内容。
- 导入发布包会在清理旧 inputs 前完成 hash、schema 和合并冲突校验，避免坏 bundle 污染旧订阅输入。
- 增加 wheel/sdist 构建脚本，`make build` 统一调用 `scripts/build_package.py`，并在构建前清理旧 `dist/`、`build/` 和 egg-info 状态。
- 补充端到端测试，覆盖 agent 从 inputs 发布、sub 导入重建和两端合并结果一致。
- 同步 P0 命令清单、订阅格式文档，并预留 M5 原生备份包结构文档。

## 验证

```bash
.venv/bin/python -m pytest
make build PYTHON=.venv/bin/python
.venv/bin/python -c "from zipfile import ZipFile; p='dist/proxystack-0.1.0-py3-none-any.whl'; z=ZipFile(p); print(z.read('proxystack-0.1.0.dist-info/entry_points.txt').decode())"
git diff --check
```

全部通过；构建产物已清理。
