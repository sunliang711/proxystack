# 参考项目

## 1. 定位

`../clash`、`../xrelay`、`../clashsub` 是新项目的参考项目，用来理解旧实现中的领域行为、配置样例和运维经验。

它们不是 `proxystack` 的源码依赖，不作为自动导入来源，也不要求新项目兼容旧目录结构。后续开发可以参考其中的实现思路，但新项目以 `proxystack/docs` 中的配置规范、生成规则和任务文档为准。

## 2. 参考边界

### `../clash`

参考内容：

- mihomo 多实例管理经验。
- systemd 模板服务和服务生命周期命令。
- mihomo 下载、更新、geo 数据安装。
- mihomo REST API 代理组切换、状态查询、日志查看。
- 透明代理相关实现可以作为 P2 参考，不进入 P0 范围。

不继承内容：

- 旧配置目录结构。
- 旧 CLI 命令名。
- 手写 mihomo 配置作为长期用户入口的方式。

### `../xrelay`

参考内容：

- Xray YAML 到 JSON 的生成规则。
- Xray inbound 类型：`vmess`、`shadowsocks`、`socks5`、`http`。
- Xray outbound 指向 socks/http 上游的实现经验。
- systemd 模板服务和日志查看。

不继承内容：

- xrelay 独立配置文件作为主配置入口。
- 端口在 xrelay 与 clash 配置里重复维护的方式。
- 旧 yaml2json 目录结构。

### `../clashsub`

参考内容：

- 订阅 HTTP 路由：`/sub/:user`、`/premium_sub/:user`、`/surge_sub/:user`。
- 订阅节点按 `user` 过滤、按 `sub: true` 输出。
- Clash/Premium Clash/Surge 模板字段。
- 健康检查和请求日志格式。

可继承的设计思想：

- 支持 inputs 目录，扫描多个订阅输入文件并合并生成订阅。
- 按 `user` 过滤节点，只有 `sub: true` 的节点进入订阅。

不继承内容：

- 旧输入文件 schema。
- 订阅服务读取完整 stack 或 clash 信息。
- 旧服务结构和模板路径约定。

## 3. 开发使用规则

- 需要确认某个协议字段或旧行为时，可以阅读参考项目。
- 如果参考项目与本文档冲突，以 `proxystack` 文档为准。
- 不从参考项目复制目录结构；只复用已验证的领域规则和测试样例思路。
- P0 不做旧目录自动导入。未来如需迁移工具，必须作为单独任务重新设计。
