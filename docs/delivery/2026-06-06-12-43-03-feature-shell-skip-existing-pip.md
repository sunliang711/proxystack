# 部署脚本跳过已存在 pip

## 背景

`install-agent.sh` 和 `install-sub-local.sh` 在需要安装 proxystack 源码包前，会先执行 `python -m pip install --upgrade pip`。重复运行或源码变更重装时，这一步会无意义访问 pip index。

## 变更

- 新增 `python_module_installed`，用于判断指定 Python 模块是否已经可 import。
- 新增 `ensure_pip_available`，pip 已存在时直接跳过；pip 缺失时才执行 `python -m ensurepip --upgrade`。
- `install-agent.sh` 和 `install-sub-local.sh` 改为调用 `ensure_pip_available`。
- proxystack 源码包仍按 `runtime/source.sha256` 指纹和 console scripts 判断是否需要安装，源码变更时仍会重新安装。

## 验证

- `/tmp/proxystack-test-venv/bin/python -m pytest tests/unit/test_task12_deployment_scripts.py -q`
- `/tmp/proxystack-test-venv/bin/python -m pytest -q`
- `shellcheck scripts/install-agent.sh scripts/install-sub-local.sh scripts/lib/common.sh`
- `git diff --check`
