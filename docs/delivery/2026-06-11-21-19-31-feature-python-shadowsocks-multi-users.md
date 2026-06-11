# shadowsocks 多用户与 SS2022 支持

## 背景

shadowsocks inbound 原先只支持顶层 `method/cipher` 和 `password` 单用户配置，无法在同一端口下区分多个用户，也没有明确说明 SS2022 method 集合。

## 变更

- `users` 字段扩展到 shadowsocks inbound，支持传统 SS 和 SS2022 多用户。
- 传统 SS 多用户会生成 Xray `settings.users[]`，用户级 `method/cipher` 可覆盖 inbound method。
- SS2022 多用户统一使用 inbound method，禁止配置用户级 `method/cipher`。
- SS2022 订阅节点密码使用 `ServerPassword:UserPassword`。
- `users[].email` 可选；未配置时使用 `users[].user` 作为 Xray 用户统计 email。
- 模板注释补充 shadowsocks 支持 method 全集。
- 更新配置规范、生成规则和相关测试。

## 测试

- `.venv/bin/python -m pytest tests/test_config_loader.py tests/test_xray_generator.py tests/test_sub_generator.py -q`：91 passed
- `.venv/bin/python -m pytest -q`：270 passed
