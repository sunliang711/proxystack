# 统一配置规范

## 1. 文件定位

所有本地文件默认放在一个目录：

```text
/opt/proxystack/
  .venv/
  bin/
    mihomo
    xray
  config.yaml
  geo/
  stacks/
    usa1.yaml
    usa2.yaml
    auto.yaml
  runtime/
    generated/
    manifest.json
  publish/
  downloads/
  sub/
    config.yaml
    inputs/
```

`config.yaml` 是全局配置；`stacks/*.yaml` 是每个 stack 的独立配置文件。每个 stack 文件包含一组 `xrelay -> clash` 配置，文件名默认就是 stack 名称。

开发环境可以使用：

```bash
proxystack-agent validate -c ./tests/fixtures/example-project/config.yaml
proxystack-agent check -c ./tests/fixtures/example-project/config.yaml
```

仓库内的 `src/proxystack/templates/agent-config.yaml` 是 `init` 初始配置模板；`init` 会通过 package resources 读取它，并按目标环境改写 `base_dir` 和 `external_host`。如果包内模板缺失，`init` 会退回代码内置默认配置。`tests/fixtures/example-project/config.yaml` 只作为开发和测试用完整项目 fixture。生产环境仍使用 `/opt/proxystack` 作为默认 `base_dir`。

关键规则：

- `config.yaml` 不放具体 stack 的端口、inbound、upstream、rules 细节。
- 每个 `stacks/<name>.yaml` 只描述一个 stack，必须包含 `name`、`xrelay` 和 `clash`。
- `stacks/<name>.yaml` 中的 `name` 必须与文件名一致，避免日志和 systemd 服务名混乱。
- xrelay 可以写在 clash 之前，解析器基于全部 stack 文件构建引用图，不依赖 YAML 顺序。
- 用户只编辑 `config.yaml` 和 `stacks/*.yaml`；生成的 Xray JSON、mihomo YAML 和订阅 input/index 不作为长期人工维护入口。

## 2. 全局 config.yaml

```yaml
version: 1
base_dir: /opt/proxystack

paths:
  bin: bin
  geo: geo
  stacks: stacks
  runtime: runtime
  generated: runtime/generated
  publish: publish
  downloads: downloads
  sub: sub

external_host: proxy.example.com

subscription:
  source: local
  listen: 0.0.0.0:3003
  base_url: https://sub.example.com
  remark_policy: prefix-source
  access:
    type: token
    token: demo-subscription-token

port_ranges:
  xrelay_inbound: 24000-24999
  clash_socks: 17000-17999
  clash_controller: 19000-19999

defaults:
  clash:
    mode: Rule
    rule_profile: default
  xrelay:
    loglevel: warning
    api:
      enabled: true
      tag: api
      listen: 127.0.0.1:10085
      services: [StatsService]
    stats:
      enabled: true
    policy:
      enabled: true

security:
  require_auth_for_public_socks_http: true
  allow_noauth_public: false

install:
  mihomo:
    version: latest
    source: auto
  xray:
    version: latest
    source: auto
  geo:
    version: latest
    source: auto
```

全局配置只放跨 stack 生效的默认值：

- `base_dir`：项目根目录，默认 `/opt/proxystack`。
- `paths.bin`：代理核心二进制目录，默认 `/opt/proxystack/bin`。
- `paths.geo`：geo 数据目录，默认 `/opt/proxystack/geo`。
- `paths.stacks`：stack 配置目录，默认相对 `base_dir`。
- `paths.runtime`：manifest、锁文件和运行状态目录。
- `paths.generated`：生成的 Xray JSON、mihomo YAML、订阅 input/index 目录。
- `paths.publish`：订阅发布包输出目录。
- `install.mihomo.source` / `install.xray.source` / `install.geo.source`：可填 `auto`、`github`、`r2` 或普通文件/URL；`auto` 按 GitHub Release 优先、Cloudflare R2 回退下载。
- `install.geo.source` 使用托管源别名时默认下载 `MetaCubeX/meta-rules-dat` 的 `geoip.metadb`；本地 `.dat`、`.mmdb`、`.metadb`、zip/tar 文件或普通 URL 仍可显式指定。
- `paths.downloads`：mihomo、xray-core 和 geo 数据下载缓存。
- `paths.sub`：本地非 Docker 订阅服务数据目录，默认 `/opt/proxystack/sub`。
- `external_host`：订阅节点默认对外 host。
- `subscription`：agent 生成订阅 input/index、导出发布包和初始化 ps-sub 配置时使用的默认参数。
- `subscription.access`：agent 本地订阅预览和初始化 ps-sub 配置时使用的访问控制。实际 HTTP 服务只读取 `sub/config.yaml` 中的 `access`；公网部署必须使用 token 或由反向代理鉴权。
- `subscription.remark_policy`：订阅节点展示名生成策略，默认 `prefix-source`，会把 stack/source 前缀用横杠加到最终 `remark` 前，避免多个 stack 的同名节点在客户端冲突。
- `subscription.remark_template`：当 `remark_policy: template` 时必填。支持 `{source}`、`{inbound}`、`{protocol}`、`{port}`、`{user}`、`{remark}`。
- `port_ranges`：`add` 默认自动分配端口、`clone --allocate-ports` 重分配端口时使用的端口池。手写端口不受端口池范围限制，只要端口在 `1-65535` 内、全局唯一且当前系统未占用即可；需要保留模板端口时使用 `add --keep-template-ports`。
- `defaults`：xrelay 和 clash 的默认值。
- `security`：socks/http 公开监听、安全确认和鉴权策略。
- `install`：二进制安装和更新默认版本。

安装路径和权限规则：

- `/opt/proxystack/bin/mihomo` 和 `/opt/proxystack/bin/xray` 是代理核心默认安装路径。
- `/opt/proxystack/geo/` 保存 `geoip`、`geosite`、ASN 或 mmdb 等运行时 geo 数据。
- `/opt/proxystack/bin/`、`geo/`、`.venv/`、`runtime/`、`publish/`、`downloads/` 默认 owner 为 `proxystack:proxystack`，目录权限为 `0750`。
- 代理核心二进制权限为 `0750`，geo 数据文件权限为 `0640`，更新时必须先写临时文件并校验 sha256，再原子替换。
- `/usr/local/bin/proxystack-agent`、`/usr/local/bin/proxystack-sub`、`/usr/local/bin/ps-agent` 和 `/usr/local/bin/ps-sub` 只是指向 `.venv/bin/` 中 console script 的 root-owned symlink，不作为 Python 包实际安装位置。
- `update self` 只写 `.venv/`，应以 `proxystack` 用户或具备同等写权限的管理员身份运行；CLI 不做隐式提权，权限不足时必须失败并提示明确的 sudo 命令。

同机部署目录边界：

- agent 可写 `runtime/`、`publish/`、`downloads/` 和 stack 配置文件。
- `config.yaml` 运行期只读；只有 `init` 和 `edit` 这类配置管理命令可以写。
- sub 只写 `sub/inputs/`，并读取 `sub/config.yaml` 中的监听地址、access token 和可选 `templates_dir`。
- agent 不直接写 `sub/inputs/`；订阅内容必须通过 `sub export` 生成 bundle，再由 `proxystack-sub import` 导入。
- sub 不读取 `config.yaml`、`stacks/` 或 `runtime/`。
- agent 和 sub 可以共用 `.venv/`，但运行期锁文件必须分开：agent 使用 `runtime/agent.lock`，sub 使用 `sub/sub.lock`。

明文凭据规则：

- P0 不使用外部凭据引用。
- 所有凭据直接写在 YAML 中，例如 `uuid`、`password`、`secret`、`token`。
- `validate` 校验明文字段的类型、格式和必填性，不检查外部凭据文件。
- 运行配置可以包含 Xray uuid、shadowsocks password、socks/http password、mihomo upstream password、mihomo controller secret 和订阅 token。
- 订阅发布包可以包含客户端连接所需凭据，例如 vmess uuid、shadowsocks password、socks/http auth。

## 3. stack 文件结构

`/opt/proxystack/stacks/usa1.yaml`：

```yaml
name: usa1
enabled: true
role: edge
labels: [usa]

xrelay:
  enabled: true
  outbound:
    type: clash
    ref: usa1.clash.socks
  inbounds:
    - name: relay
      protocol: socks5
      listen: 0.0.0.0
      port: 24001
      udp: true
      auth:
        type: password
        username: user1
        password: demo-relay-password
      user: alice
      remark: usa1 relay socks
      sub: true

clash:
  enabled: true
  mode: Rule
  controller:
    listen: 127.0.0.1:19091
    secret: demo-clash-api-secret
  listeners:
    socks:
      - name: local
        listen: 127.0.0.1
        port: 17091
  upstreams:
    - name: server-a
      type: raw
      config:
        type: vmess
        server: server.example.com
        port: 443
        uuid: aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa
        network: ws
        tls: true
  groups:
    - name: AllProxy
      type: select
      proxies: [server-a, DIRECT]
  rules:
    profile: default
```

### stack 顶层字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | stack 名称，必须与文件名一致 |
| `enabled` | 否 | 是否参与 `check/start/sub export`，默认 `true` |
| `role` | 否 | stack 角色，P0 支持 `edge` 和 `auto` |
| `labels` | 否 | 标签列表，用于 `list` 展示和未来 auto selector |
| `xrelay` | 是 | Xray/xrelay 配置 |
| `clash` | 是 | mihomo/clash 配置 |

## 4. xrelay 配置

### API、Stats 和 Policy

`defaults.xrelay` 和单个 stack 的 `xrelay` 都可以配置 Xray API、Stats 和 Policy。stack 内配置只覆盖显式填写的字段：

```yaml
xrelay:
  api:
    enabled: true
    tag: api
    listen: 127.0.0.1:10085
    services: [StatsService]
  stats:
    enabled: true
  policy:
    levels:
      "0":
        statsUserUplink: true
        statsUserDownlink: true
    system:
      statsInboundUplink: true
      statsInboundDownlink: true
      statsOutboundUplink: true
      statsOutboundDownlink: true
```

规则：

- `api.enabled` 默认 `true`；默认 `tag: api`、`listen: 127.0.0.1:10085`、`services: [StatsService]`。
- API listen 只能使用 `127.0.0.1`、`::1` 或 `localhost`，不能配置公网监听地址。
- `stats.enabled` 默认 `true`；开启时生成 `stats: {}`。
- `policy.enabled` 默认 `true`；两个 `policy.levels."0"` 用户统计开关和四个 `policy.system` 流量统计开关默认生成 `true`，显式配置值可以覆盖。

### inbound 字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 本 stack 内唯一名称，也是 ref 的最后一段 |
| `protocol` | 是 | `vmess`、`shadowsocks`、`socks5`、`http` |
| `listen` | 否 | 默认 `0.0.0.0`，socks/http 推荐改为 `127.0.0.1` 或启用 auth |
| `port` | 是 | 监听端口，全部 stack 内必须无冲突 |
| `udp` | 否 | socks5/shadowsocks 可用 |
| `auth` | 否 | socks5/http 支持 `noauth` 或 `password` |
| `user` | socks/http/shadowsocks 单用户可选 | 订阅 URL 中的用户过滤字段；vmess 和 shadowsocks 多用户必须写在 `users[].user` |
| `server` | 否 | 订阅节点 server 覆盖值；不填使用 `external_host` |
| `remark` | socks/http/shadowsocks 单用户可选 | 订阅节点展示名；vmess 和 shadowsocks 多用户必须写在 `users[].remark` |
| `tag` | 否 | 不填则生成 `protocol:port:name` |
| `sub` | 是 | 是否进入订阅输出 |
| `network` | vmess 必填 | vmess 传输网络，例如 `raw` |
| `method` / `cipher` | shadowsocks 必填 | shadowsocks 加密方法；`cipher` 兼容旧写法 |
| `password` | shadowsocks 必填 | shadowsocks 单用户密码，或 SS2022 多用户的服务端密码 |
| `users` | vmess 必填，shadowsocks 可选 | vmess 必须非空；shadowsocks 非空时启用多用户 |

### vmess users

vmess 只支持 `users` 结构；单用户也写成一条 `users` 记录。

- 不支持 inbound 顶层 `uuid`。
- vmess 的 `user` 和 `remark` 必须写在 `users[]` 中。
- `users[].email` 可选，用于 Xray 用户统计；不填时使用 `users[].user`。
- `users` 只能用于 vmess；同一 inbound 内 `users[].user`、`users[].uuid`、最终 email 和最终订阅 tag 不能重复。

```yaml
- name: vmess
  protocol: vmess
  listen: 0.0.0.0
  port: 4301
  network: raw
  sub: true
  users:
    - user: alice
      uuid: 11111111-1111-4111-8111-111111111111
      email: alice@example.com
      remark: alice vmess
    - user: bob
      uuid: 22222222-2222-4222-8222-222222222222
      remark: bob vmess
```

### shadowsocks users

shadowsocks 可以继续使用顶层 `method/password/user/remark` 表达单用户，也可以使用 `users` 表达多用户。

- 传统 SS 多用户：inbound 顶层 `method/password` 仍要配置；`users[].method` 可覆盖单个用户的 method，未配置时继承 inbound method。
- SS2022 多用户：inbound 顶层 `method` 必须是 SS2022 method，顶层 `password` 是 ServerPassword；`users[].password` 是 UserPassword；订阅侧密码会生成 `ServerPassword:UserPassword`。
- SS2022 users 不允许配置 `users[].method` 或 `users[].cipher`。
- shadowsocks 多用户不使用 inbound 顶层 `user/remark`，必须写在 `users[]` 中。
- 同一 inbound 内 `users[].user`、最终 email 和最终订阅 tag 不能重复。

支持的 method 全集：

- SS2022：`2022-blake3-aes-128-gcm`、`2022-blake3-aes-256-gcm`、`2022-blake3-chacha20-poly1305`
- 传统 SS：`aes-256-gcm`、`aes-128-gcm`、`chacha20-poly1305`、`chacha20-ietf-poly1305`、`xchacha20-poly1305`、`xchacha20-ietf-poly1305`、`none`、`plain`

```yaml
- name: ss2022
  protocol: shadowsocks
  listen: 0.0.0.0
  port: 4302
  method: 2022-blake3-aes-256-gcm
  password: server-key
  udp: true
  sub: true
  users:
    - user: alice
      password: alice-key
      email: alice@example.com
      remark: alice ss2022
    - user: bob
      password: bob-key
      remark: bob ss2022
```

### socks/http 鉴权

socks5 和 http 类型支持鉴权：

```yaml
auth:
  type: password
  username: demo
  password: demo-password
```

也支持本地调试用无鉴权：

```yaml
auth:
  type: noauth
```

安全约束：

- `listen` 不是 `127.0.0.1` 或 `::1` 时，socks/http 不允许 `auth.type: noauth`，除非命令显式传入危险确认参数。
- `sub: true` 的 socks/http 如果对公网暴露，必须有鉴权。
- 密码直接写在 `password` 字段中，生成器按协议需要原样写入运行配置或订阅输出。

### outbound type

xrelay 的 `outbound.type` 支持：

| type | 含义 | 首期状态 |
| --- | --- | --- |
| `clash` | 指向某个 mihomo 本地 socks 监听端口；mixed listener 预留到 P1 | P0 |
| `socks5` | 指向外部 socks5 代理，支持 username/password | P0 |
| `http` | 指向外部 http 代理，支持 username/password | P0 |
| `direct` | Xray freedom outbound | P0 |

`type: clash` 使用 `ref`，例如：

```yaml
outbound:
  type: clash
  ref: usa1.clash.socks
```

ref 三段含义：

```text
<stack>.clash.socks
```

- 第一段 `usa1`：目标 stack 名称。
- 第二段 `clash`：目标组件类型。
- 第三段 `socks`：目标 listener 类型，当前只支持唯一 socks listener。

这样 xrelay 不需要重复填写 clash 的 socks 端口；端口只在目标 stack 的 `clash.listeners` 中声明一次。

## 5. clash 配置

### mode

默认使用：

```yaml
mode: Rule
```

支持值：

- `Rule`：默认值，按规则分流，适合长期运行。
- `Global`：所有流量交给 `GLOBAL` 代理组，适合临时测试。
- `Direct`：全部直连，适合排障。

P0 中只生成 `listeners.socks`，并且最多允许一个条目。`listeners.mixed` 作为 P1 预留字段，P0 校验层如果遇到该字段应报错并提示暂不支持，不能静默忽略或生成 `mixed-port`。

### rules

`rules.profile` 选择内置规则模板，`rules.final` 指定默认 `MATCH` 规则的目标组：

```yaml
rules:
  profile: default
  final: AllProxy
  extra:
    - DOMAIN-SUFFIX,example.com,AllProxy
```

默认 `final: AllProxy`。校验层必须确保 `final` 指向已存在 proxy group、proxy 或内置策略；使用默认值时，每个 clash 配置都必须定义 `AllProxy` 组。

## 6. xrelay-socks5 引用

`type: xrelay-socks5` 用在 clash 的 upstream/proxy 定义中，表示生成一个 mihomo socks5 proxy，目标是某个 xrelay inbound。

```yaml
upstreams:
  - name: usa1-local
    type: xrelay-socks5
    ref: usa1.relay
```

ref 两段含义：

```text
<stack>.<inbound_name>
```

- 第一段 `usa1`：目标 stack 名称。
- 第二段 `relay`：目标 stack 中 `xrelay.inbounds[].name` 字段。

`relay` 不是固定字面量，它由用户在目标 stack 的 `xrelay.inbounds[].name` 中定义。
`type: xrelay-socks5` 已经声明目标必须是 xrelay 的 socks5 inbound，因此校验层会根据 `ref` 找到目标 inbound 后确认 `protocol: socks5`。

`upstreams[].name` 有用。它会成为 mihomo `proxies[].name`，也会被 `proxy-groups[].proxies` 引用。比如 `usa1-local`、`usa2-local` 就是 auto 组里的节点名。

## 7. auto 场景

用户已有多组 stack：

- `usa1`：`xrelay -> clash`，xrelay 暴露 socks5 端口 `p1`。
- `usa2`：`xrelay -> clash`，xrelay 暴露 socks5 端口 `p2`。

新增 `auto.yaml`：

- `auto.xrelay -> auto.clash`。
- `auto.clash` 的下游不直接写外部节点，而是通过 `xrelay-socks5` 引用 `usa1` 和 `usa2`。
- `auto.clash` 的组可以使用 `url-test` 或 `load-balance`。
- P0 auto 只支持 `type: xrelay-socks5`。如果未来需要 http 下游，再新增 `type: xrelay-http`，不要复用 `xrelay-socks5` 的语义。

示例见 [auto stack 示例](../tests/fixtures/example-project/stacks/auto.yaml)。

## 8. 订阅生成

订阅生成只使用 xrelay inbound：

```text
compiled xrelay inbounds -> sub index -> /sub/:user
```

不会读取 clash 的：

- upstream 节点
- proxy-groups
- rules
- mode
- controller

原因：订阅面向客户端，客户端要连接的是 xrelay 暴露的端口；clash 是服务端内部上游选择器。

## 9. 默认模板

`add <name>` 必须支持从默认模板生成 `/opt/proxystack/stacks/<name>.yaml`。默认模板应保守：

- clash 只监听 `127.0.0.1` 的 socks 端口。
- xrelay 默认只生成安全协议示例。
- socks/http inbound 默认不公开或 `sub: false`。
- 凭据字段使用明文占位值，例如 `password: change-me`、`uuid: ...`。

模板生成后必须打开编辑器，用户保存后执行 `validate`；端口冲突、ref 错误和危险公开监听都在校验阶段暴露。
