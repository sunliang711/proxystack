# 模板与测试 fixture 来源收敛

## 重构摘要

- 将 `ps-agent init` 使用的全局配置模板移入 `src/proxystack/templates/agent-config.yaml`，运行时代码通过 package resources 读取。
- 将 `ps-sub` 独立配置参考模板移入 `src/proxystack/templates/sub-config.yaml`。
- 将完整测试项目从 `examples/` 迁移到 `tests/fixtures/example-project/`，测试继续使用同一组 stack fixture 做回归。
- 删除仓库根目录 `examples/`，避免运行模板、文档示例和测试 fixture 混在同一目录。

## 保持不变的行为

- `ps-agent init` 仍会改写目标环境的 `base_dir` 和 `external_host`。
- 包内模板缺失时，`init` 仍回退到代码里的保守默认配置。
- `ps-agent add --template ...` 仍只读取 `src/proxystack/templates/stack.*.yaml`。

## 验证结果

- `PYTHONPATH=src /tmp/proxystack-test-venv/bin/python -m pytest -q`：299 passed
- `git diff --check`：通过
