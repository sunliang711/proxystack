# Feature: ps-sub 订阅模板渲染

## 变更摘要

- 新增包内默认订阅模板：`clash.yaml.j2`、`premium-clash.yaml.j2`、`surge.conf.j2`。
- `ps-sub` 支持从 `templates_dir` 或 `<data_dir>/templates/sub/` 读取本地同名模板覆盖默认模板。
- 订阅渲染器保留节点转换逻辑，把完整 Clash/Premium Clash/Surge 外层配置交给 Jinja2 模板生成。
- 订阅路由区分模板错误和用户不存在：模板错误返回 `503 template_error`，用户不存在仍返回 `404 not_found`。

## 配置变更

- `ps-sub config.yaml` 新增可选字段：

```yaml
templates_dir: /opt/proxystack/sub/templates
```

- 未配置时，服务会自动读取 `<data_dir>/templates/sub/` 下的同名模板。

## 测试情况

- `PYTHONPATH=src /tmp/proxystack-test-venv/bin/python -m pytest -q tests/golden/test_subscription_golden.py tests/test_sub_generator.py tests/test_subserver.py tests/test_cli.py::test_sub_serve_uses_config_access_and_memory_index tests/test_cli.py::test_sub_serve_defaults_data_dir_to_config_parent tests/test_cli.py::test_sub_serve_uses_config_templates_dir`
- `PYTHONPATH=src /tmp/proxystack-test-venv/bin/python -m pytest -q tests/test_cli.py tests/test_sub_generator.py tests/test_subserver.py tests/golden/test_subscription_golden.py tests/e2e/test_task11_main_flow.py`
- `PYTHONPATH=src /tmp/proxystack-test-venv/bin/python -m pytest -q`
- `PYTHONPATH=src /tmp/proxystack-test-venv/bin/python -m compileall -q src tests`
- `git diff --check`
