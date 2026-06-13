# sub 配置 public_base_url 占位和字段说明修复

## 问题

安装或初始化后生成的 `sub/config.yaml` 中缺少 `managed_config.public_base_url` 空占位，用户需要反代部署时不容易发现该配置项。同时生成文件没有保留每个配置项的说明。

## 根因

`SubServerConfig` 写回 YAML 时使用 `exclude_none=True`，导致值为 `None` 的 `managed_config.public_base_url` 被序列化阶段移除；生成配置也没有从模板保留注释。

## 修复方式

- 为 ps-sub 配置输出新增带注释的 mapping 生成逻辑。
- 显式保留 `managed_config.public_base_url:` 空占位。
- `proxystack-agent init` 生成 `sub/config.yaml` 时复用同一套 ps-sub YAML 输出逻辑。
- 更新包内 `src/proxystack/templates/sub-config.yaml`，为每个配置项补充说明。

## 验证

- `PYTHONPATH=src:. .venv/bin/pytest tests/test_cli.py -k "agent_init or sub_config" -q`
- `PYTHONPATH=src:. .venv/bin/pytest tests/test_subserver.py tests/test_cli.py::test_sub_serve_uses_config_access_and_memory_index -q`

## 回归风险

低。变更只影响 ps-sub 配置文件的生成文本，运行时仍通过原有 Pydantic 模型加载和校验。
