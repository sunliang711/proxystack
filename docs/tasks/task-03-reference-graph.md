# Task 03: 引用解析与依赖图

## 目标

实现 ref 解析、端口索引、rules 目标校验和实例依赖图。

## 技术方案

- 新建 `src/proxystack/graph`。
- ref 解析为结构体，不在业务中反复 split 字符串。
- 依赖图用于 `plan/up` 决定服务操作顺序，并用于循环检测；`apply` 只消费解析后的生成模型。

## 实现步骤

1. 实现 `ParseRef`，支持通用四段 `instance.component.kind.name`。
2. 实现 xrelay inbound 索引：`instance + protocol + inbound_name -> endpoint`。
3. 实现 clash listener 索引：`instance + listener_type + listener_name -> endpoint`。
4. 校验 `xrelay.outbound.type: clash` 的 ref。
5. 校验 `clash.upstreams.type: xrelay-socks5` 的 ref。
6. 校验 `proxy-groups[].proxies[]` 和 rules 目标。
7. 实现循环依赖检测。
8. 输出服务操作顺序建议：被引用的 xrelay socks5 inbound 必须早于引用它的 auto clash 启动。

## 验收标准

- `usa1.xrelay.socks5.relay` 能解析到 xrelay inbound 端口，其中 `kind` 表示 inbound protocol。
- `usa1.clash.socks.local` 能解析到 clash socks listener，其中 `kind` 表示 listener type。
- ref 不存在、组件不匹配、协议不匹配时失败。
- auto 场景无循环时通过，有循环时失败。
- `plan` 能展示目标 stack 的依赖服务和建议操作顺序。

## 依赖

Task 02。

## 风险

不要把 ref 解析逻辑散落在生成器里；生成器只消费解析后的模型。
