# Task 01: 项目骨架

## 目标

初始化 Python 项目骨架，建立 CLI、日志、配置加载和测试基础。

## 技术方案

- 使用 `pyproject.toml` 管理项目和 console scripts。
- CLI 使用 Typer。
- 日志使用 Python `logging` 的结构化封装。
- 配置模型使用 Pydantic v2。
- 内置 stack 模板统一维护在 `src/proxystack/templates`，作为运行时代码读取的包内资源。示例使用 `examples/config.yaml` 和 `examples/stacks/*.yaml`。
- 建立 `src/proxystack/*` 和 `tests/*` 基础目录。

## 实现步骤

1. 创建 `pyproject.toml`。
2. 创建 `src/proxystack/cli`，注册 `proxystack-agent` 和 `proxystack-sub` 命令。
3. 创建 `src/proxystack/logging.py` 初始化结构化 logging。
4. 创建 `src/proxystack/config` 的默认配置加载入口。
5. 创建 `src/proxystack/templates` 放置内置模板，作为模板唯一来源。
6. 创建 `examples/config.yaml` 和 `examples/stacks/*.yaml`。
7. 创建基础 Makefile 或等价脚本：`test`、`lint`、`build`。

## 验收标准

- `pytest` 通过。
- `proxystack-agent --help` 和 `proxystack-sub --help` 输出命令帮助。
- 内置模板来源明确，仓库只维护一份模板。
- 生产代码没有 `print()`。
- 每个函数/方法有简洁注释。

## 依赖

无。

## 风险

不要在骨架阶段引入业务逻辑，避免后续模块边界变乱。
