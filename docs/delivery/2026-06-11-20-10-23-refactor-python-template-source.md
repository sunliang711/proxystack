# 模板来源收敛

## 重构摘要

- 删除仓库根目录 `templates/` 下的重复 stack 模板文件。
- 保留 `src/proxystack/templates/` 作为 `ps-agent add --template ...` 的唯一模板来源。
- 更新 README、编码规范、任务文档和模板目录说明，避免继续提示维护两份模板。

## 保持不变的行为

- `ps-agent add` 仍通过 Python package resources 读取内置模板。
- Python package data 配置不变，发布包继续包含 `src/proxystack/templates/*.yaml`。

## 验证结果

- `.venv/bin/python -m pytest -q`：250 passed
