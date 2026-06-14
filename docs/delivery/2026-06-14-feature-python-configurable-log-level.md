# 可配置运行日志级别交付记录

## 变更摘要

- 在配置模型中新增 Xray 和 mihomo/clash 日志级别枚举校验。
- Xray 生成优先使用 `stack.xrelay.loglevel`，未配置时使用 `defaults.xrelay.loglevel`。
- mihomo/clash 生成优先使用 `stack.clash.loglevel`，未配置时使用 `defaults.clash.loglevel`。
- 同步全局配置模板、stack 模板注释示例、配置规范和生成规则文档。

## 兼容性

- 旧配置不写新字段时，Xray 仍生成 `warning`。
- 旧配置不写新字段时，mihomo/clash 仍生成 `info`。

## 验证

- `.venv/bin/pytest tests/test_config_loader.py tests/test_xray_generator.py tests/test_mihomo_generator.py`
- `PYTHONPATH=src:. .venv/bin/pytest`
