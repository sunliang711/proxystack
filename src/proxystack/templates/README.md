内置模板供运行时代码通过 package resources 读取。

本目录是内置模板来源；修改 `ps-agent add --template ...` 使用的默认 stack 模板时，只需要更新 `stack.*.yaml` 文件。

`agent-config.yaml` 是 `ps-agent init` 使用的默认全局配置模板。`sub-config.yaml` 是 `ps-sub` 独立配置的参考模板。

`sub/` 目录保存 `ps-sub` 订阅输出的默认 Jinja2 模板。本地运行时可以通过 `<data_dir>/templates/sub/` 或 `ps-sub config.yaml` 中的 `templates_dir` 覆盖同名模板。

订阅模板上下文中的 `nodes` 可包含可选 `region` 字段，只校验两位大写国家/地区简称格式，不限制固定国家列表。Surge 模板还会收到 `surge_region_groups`，用于按 `region` 或节点 `remark` 前缀生成带 emoji 和 `icon-url` 的地区代理组。

Surge 模板在 HTTP 渲染时会收到 `managed_config_url`、`managed_config_interval` 和 `managed_config_strict`，用于在配置第一行生成 `#!MANAGED-CONFIG` 托管配置头。
