内置 stack 模板供运行时代码通过 package resources 读取。

本目录是内置模板来源；修改 `ps-agent add --template ...` 使用的默认 stack 模板时，只需要更新这里的 YAML 文件。

`sub/` 目录保存 `ps-sub` 订阅输出的默认 Jinja2 模板。本地运行时可以通过 `<data_dir>/templates/sub/` 或 `ps-sub config.yaml` 中的 `templates_dir` 覆盖同名模板。
