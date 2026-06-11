# Bug 修复摘要

- 问题：`ps-agent add <name> --template auto-url-test` 在未指定 `--members` 时，会因为模板内默认 `usa1.relay`、`usa2.relay` 占位 ref 不存在而创建失败。
- 根因：`add` 写入前会把候选 stack 放入全项目执行严格 ref 校验；auto 模板未指定成员时仍保持启用状态，导致占位 ref 被当作真实依赖校验。
- 修复方式：无 `--members` 的 `auto-url-test` 和 `load-balance` 模板生成禁用草稿，保留占位 ref 供用户编辑；显式传入 `--members` 时仍按真实引用做 fail-fast 校验。
- 影响范围：只影响内置 auto 模板未指定 `--members` 的新增流程，不改变 `pair`、`--from-file`、显式 `--members` 和后续 `validate/start` 的严格校验。
- 验证方式：`.venv/bin/python -m pytest tests/test_cli.py -q`
- 回归风险：低。禁用草稿不会参与 ref 依赖图，用户需要编辑成员 ref 后再启用。
