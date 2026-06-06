# Task 03 交付记录：引用解析与依赖图

## 变更摘要

- 新增 `src/proxystack/graph/`，实现结构化 ref 解析、xrelay inbound 索引、clash listener 索引、服务依赖图和循环检测。
- 在 `validate_stack_set` 中接入跨 stack ref 校验，覆盖 xrelay outbound 指向 clash listener、clash xrelay-socks5 upstream 指向 socks5 inbound，以及循环依赖。
- 新增 `proxystack-agent plan`，只展示依赖服务和建议操作顺序，不写文件、不操作服务。
- 补充测试覆盖示例索引、依赖排序、缺失 ref、组件错配、协议错配、循环依赖和 CLI plan。

## 当前 ref 规则

- `clash.upstreams[].type: xrelay-socks5` 使用两段 ref：`<stack>.<inbound_name>`，例如 `usa1.relay`。
- `xrelay.outbound.type: clash` 使用三段 ref：`<stack>.clash.socks`，例如 `usa1.clash.socks`。

## 验证命令

```bash
make test PYTHON=.venv/bin/python
make lint PYTHON=.venv/bin/python
.venv/bin/proxystack-agent plan -c examples/config.yaml
```

## 风险与后续

- 当前 plan 只展示依赖关系和建议顺序，不做 manifest 对比、文件生成或 systemd 操作；这些属于后续任务。
- 当前 clash listener 索引只覆盖 P0 已支持的 socks listener。
