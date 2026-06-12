# Task 02: 配置模型与校验

## 目标

实现 `/opt/proxystack/config.yaml` 和 `/opt/proxystack/stacks/*.yaml` 的强类型模型、加载流程和基础校验。

## 技术方案

- 模型放在 `src/proxystack/domain`。
- 配置加载放在 `src/proxystack/config`。
- schema 校验使用 Pydantic v2 和自定义校验函数。
- 凭据字段统一使用明文字段，例如 `uuid`、`password`、`secret`、`token`。
- 全局端口池使用 `port_ranges` 描述，`add` 默认自动分配端口，`clone --allocate-ports` 才会重新分配端口；手写端口可以在端口池之外，但必须合法、唯一且未被系统占用。

## 实现步骤

1. 定义 `GlobalConfig`、`Stack`、`StackSet`、`XrelayConfig`、`ClashConfig`。
2. 定义 inbound、outbound、upstream、group、rules 模型。
3. 实现 `load_config(path: Path) -> GlobalConfig` 和 `load_stacks(config: GlobalConfig) -> StackSet`。
4. 实现基础字段校验：必填、stack 文件名与 `name` 一致、唯一名称、端口范围、mode 枚举、协议枚举。
5. 实现安全校验：socks/http 非回环监听时必须鉴权。
6. 实现凭据字段校验：`validate` 校验明文字段的类型、格式和必填性，不读取外部凭据文件。
7. 实现端口池模型和端口占用校验：手写端口必须全局唯一且不要求落在 `port_ranges` 中；自动分配只能使用 `port_ranges` 中的空闲端口。
8. 增加 `role`、`labels` 字段校验，用于 stack 分类和 auto 成员筛选扩展。
9. 增加 `tests/fixtures/example-project/config.yaml` 和 `tests/fixtures/example-project/stacks/*.yaml` 的解析测试。

## 验收标准

- 合法示例通过校验。
- 非法 mode、重复 stack 名、重复 inbound name、端口越界会失败。
- 非回环 socks/http noauth 默认失败。
- 必填凭据字段缺失或格式错误时失败。
- `--allocate-ports` 分配结果必须稳定写入目标 stack，未传该参数时 clone 保留原端口并由 validate 报冲突。
- 错误消息能定位到具体字段路径。

## 依赖

Task 01。

## 风险

配置模型一旦被生成器依赖，字段迁移成本会变高；本任务完成前应先 review `docs/config-spec.md`。
