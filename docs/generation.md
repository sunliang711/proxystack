# 配置生成规则

## 1. 总体原则

`proxystack-agent start` 的配置生成输入只有 `/opt/proxystack/config.yaml` 和 `/opt/proxystack/stacks/*.yaml`，输出包括：

- Xray JSON：`/opt/proxystack/runtime/generated/xray/<stack>.json`
- mihomo YAML：`/opt/proxystack/runtime/generated/clash/<stack>.yaml`
- 订阅索引：`/opt/proxystack/runtime/generated/sub/index.json`
- 订阅输入：`/opt/proxystack/runtime/generated/sub/inputs/<source>.yaml`
- 订阅发布包：`/opt/proxystack/publish/sub-bundle.zip`
- manifest：`/opt/proxystack/runtime/manifest.json`

生成器必须满足：

- 同一份 config 和 stack 文件多次生成结果稳定。
- 未变化的生成文件不改写，避免无意义重启服务。
- 生成前先执行完整校验。
- `sub` 只影响订阅索引，不影响 Xray inbound 是否生成。
- clash 信息不进入订阅索引。
- 订阅服务只消费订阅输入/发布包，不读取 stack 或 clash 配置。

## 2. Xray 生成

每个 enabled stack 的 `xrelay` 生成一个 Xray JSON。

### api、stats 和 policy

默认生成 `api`、`stats`、`policy`。`api.enabled: true` 时生成 Xray 简化 API 配置：

```json
{
  "api": {
    "tag": "api",
    "listen": "127.0.0.1:10085",
    "services": ["StatsService"]
  }
}
```

API listen 必须是 loopback 地址，避免把 Xray API 暴露到公网。

当 `stats.enabled: true` 时生成：

```json
{
  "stats": {},
  "policy": {
    "levels": {
      "0": {
        "statsUserUplink": true,
        "statsUserDownlink": true
      }
    },
    "system": {
      "statsInboundUplink": true,
      "statsInboundDownlink": true,
      "statsOutboundUplink": true,
      "statsOutboundDownlink": true
    }
  }
}
```

如果用户显式配置 `policy.levels` 或 `policy.system` 中的统计字段，生成器使用显式配置覆盖 Stats 默认值。

### inbounds

支持协议：

- `vmess`
- `shadowsocks`
- `socks5`
- `http`

通用 tag 规则：

```text
<protocol>:<port>:<name>
```

用户显式配置 `tag` 时使用用户值；否则自动生成。tag 用于 Xray inbound 标识；vmess 订阅节点可以用 `users[].tag` 覆盖。

vmess 规则：

- 必须提供 `network`。
- 必须提供非空 `users`；单用户也写成一条 `users` 记录。
- 不支持顶层 `uuid`，顶层 `user` 和 `remark` 也不用于 vmess。
- `users` 结构使用 `users[].user`、`users[].uuid`、`users[].remark` 和可选 `users[].tag`；`users` 只能用于 vmess。
- 同一 inbound 内 `users[].user`、`users[].uuid` 和最终订阅 tag 不能重复。
- 多用户 vmess 生成一个 Xray inbound，`settings.clients` 中每个用户生成一个 client，包含 `id`、`alterId: 0` 和用于用户统计的 `email`。

socks5/http 规则：

- 支持 `auth.type: noauth` 和 `auth.type: password`。
- 非回环监听的 noauth 配置默认校验失败。
- `sub: true` 且协议为 socks5/http 时，订阅生成必须带上用户名密码。

### outbound

xrelay outbound 生成 Xray `outbounds`：

- `type: clash`：解析 `ref` 到对应 clash socks listener，生成 `protocol: socks` 出站。mixed listener 预留到 P1。
- `type: socks5`：生成 Xray socks outbound。
- `type: http`：生成 Xray http outbound。
- `type: direct`：生成 freedom outbound。

`type: clash` 示例：

```yaml
xrelay:
  outbound:
    type: clash
    ref: usa1.clash.socks
```

生成时解析到：

```json
{
  "protocol": "socks",
  "settings": {
    "servers": [
      {
        "address": "127.0.0.1",
        "port": 17091
      }
    ]
  }
}
```

## 3. mihomo 生成

每个 enabled stack 的 `clash` 生成一个 mihomo YAML。

`proxystack-agent render clash <stack>` 可只读输出指定 stack 的最终 mihomo YAML，不写入 runtime、manifest 或 systemd 配置。

### 基础字段

默认：

```yaml
allow-lan: false
bind-address: 127.0.0.1
mode: Rule
log-level: info
ipv6: true
external-controller: 127.0.0.1:19091
```

P0 只支持一个 socks listener。配置中 socks listener 多于一个时，校验层必须报错，生成器不能静默选择第一个：

```yaml
socks-port: 17091
```

`listeners.mixed` 和 `mixed-port` 预留到 P1。P0 如果遇到 mixed listener，应在校验阶段报错并提示暂不支持。如未来需要多个 mihomo listener，再扩展到 mihomo 的高级 listeners 配置。

### upstreams -> proxies

`type: raw` 原样生成到 mihomo `proxies`，其中 `uuid`、`password` 等凭据字段直接使用 YAML 中的明文值。

`type: xrelay-socks5` 通过 ref 解析到目标 xrelay socks5 inbound。P0 不支持 `xrelay-http`，需要 http 下游时作为 P1 新类型扩展：

```yaml
upstreams:
  - name: usa1-local
    type: xrelay-socks5
    ref: usa1.relay
```

生成：

```yaml
proxies:
  - name: usa1-local
    type: socks5
    server: 127.0.0.1
    port: 24001
    username: usa1
    password: <inbound-password>
    udp: true
```

如果目标 inbound 的 `listen` 是 `0.0.0.0`，mihomo 仍应优先使用 `127.0.0.1` 连接本机端口。

### groups -> proxy-groups

支持 mihomo 常用组：

- `select`
- `url-test`
- `load-balance`
- `fallback`

auto 场景使用：

```yaml
proxy-groups:
  - name: AutoProxy
    type: url-test
    proxies: [usa1-local, usa2-local]
    url: http://www.gstatic.com/generate_204
    interval: 120
  - name: BalanceProxy
    type: load-balance
    proxies: [usa1-local, usa2-local]
    url: http://www.gstatic.com/generate_204
    interval: 120
    strategy: consistent-hashing
```

校验要求：

- `proxy-groups[].proxies[]` 必须引用已存在的 proxy、proxy group 或内置策略 `DIRECT`、`REJECT`。
- `url-test` 和 `load-balance` 必须配置 `url` 和 `interval`。
- `load-balance.strategy` 默认 `consistent-hashing`。

## 4. rules 生成

默认 `mode: Rule`。生成的 mihomo rules 由 `rules.profile` 和 `rules.extra` 组合：

```yaml
rules:
  profile: default
  final: AllProxy
  extra:
    - DOMAIN-SUFFIX,example.com,AllProxy
```

P0 内置 `default` profile。最后一条 `MATCH` 的目标来自 `rules.final`，默认是 `AllProxy`：

```yaml
rules:
  - DOMAIN-SUFFIX,local,DIRECT
  - DOMAIN,localhost,DIRECT
  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve
  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve
  - IP-CIDR,100.64.0.0/10,DIRECT,no-resolve
  - GEOIP,CN,DIRECT
  - MATCH,<rules.final>
```

实际生成顺序为：`rules.extra`、default profile 内置规则、`MATCH,<rules.final>`。这样用户显式规则优先匹配，最终兜底规则始终可见。

规则目标允许：

- `DIRECT`
- `REJECT`
- 已存在 proxy name
- 已存在 proxy group name

校验层必须确保 `rules.final` 和 `rules.extra` 中的规则目标都存在。使用默认 `rules.final: AllProxy` 时，当前 clash 必须定义 `AllProxy` 组。

`check` 和 `render clash <name>` 必须能展示最终 rules，避免规则隐藏在模板中不可见。

## 5. 订阅生成

订阅索引只来自启用的 xrelay inbound：

```text
stacks/*.yaml xrelay.inbounds[] where sub == true
```

订阅字段来源：

- `server`：默认使用 `config.yaml` 中的 `external_host`，允许 inbound 覆盖。
- `port`：xrelay inbound 的 `port`。
- `user`：非 vmess 使用 inbound 的 `user`；vmess 使用 `users[].user`。
- `tag`：非 vmess 优先使用 inbound 显式 `tag`，否则生成 `<protocol>:<port>:<inbound.name>`；vmess 优先使用 `users[].tag`，否则生成 `<inbound tag>:<users[].user>`。
- `remark`：非 vmess 优先 `remark`，其次 `tag`，最后 `<stack>-<inbound.name>`；vmess 优先 `users[].remark`，其次 `users[].tag`，最后 `<stack>-<inbound.name>-<users[].user>`。
- 协议参数：来自 inbound 本身。

不会读取：

- `clash.upstreams`
- `clash.groups`
- `clash.rules`
- `clash.mode`
- `clash.controller`

HTTP 路由：

- `/sub/:user`：普通 Clash。
- `/premium_sub/:user`：Premium Clash。P0 与普通 Clash 使用同一 YAML 输出，但渲染入口保持独立。
- `/surge_sub/:user`：Surge。

P0 的 Clash/Premium Clash 订阅只输出客户端节点列表 `proxies`，不生成 proxy-groups、rules、mode 或 controller。Surge 订阅只输出 `[Proxy]` 段。

订阅访问控制：

- `subscription.access.type: token` 时，HTTP 路由必须校验 `token` query 参数或等价的反向代理鉴权头。
- `subscription.access.type: none` 只允许本地监听或明确的公网风险确认。
- token 只用于访问订阅 HTTP 服务，不写入订阅节点。

用户不存在或没有订阅节点时返回 `404` 和统一 JSON 错误结构。

## 6. 订阅输入和多文件合并

Subscription input 是 agent 和 sub 共享的格式。`proxystack-sub` 支持类似 `clashsub` 的 inputs 目录，`proxystack-agent` 也可以直接读取同一目录来校验、合并和导出发布包：

```text
<data_dir>/
  inputs/
    usa1.yaml
    usa2.yaml
    auto.yaml
  current/
    index.json
```

每个 input 文件只包含订阅节点和来源元数据，不包含完整 stack：

```yaml
input_schema: proxystack.subscription-input
input_version: 1
source: usa1
generated_at: "2026-06-05T12:00:00+08:00"
nodes:
  - id: usa1:relay
    user: alice
    protocol: socks5
    server: proxy.example.com
    port: 24001
    tag: socks5:24001:relay
    remark: usa1 relay socks
    auth:
      type: password
      username: usa1
      password: "<client-credential>"
```

订阅 input 中允许出现客户端连接所需凭据，例如 vmess uuid、shadowsocks password、socks/http username/password。它不包含完整 stack、clash upstream、proxy-groups、rules、mode 或 mihomo controller 配置。

合并规则：

- `proxystack-sub rebuild` 扫描 `<data_dir>/inputs/*.yaml`、`*.yml`、`*.json`。
- `proxystack-agent publish --input-dir <dir>` 使用同一套扫描与合并规则。
- `proxystack-agent render sub --input-dir <dir>` 可以输出合并后的订阅索引。
- 只合并通过 schema 校验的输入文件。
- 按文件名排序后合并，保证结果稳定。
- 按 `nodes[].user` 分组生成订阅。
- `nodes[].id` 必须全局唯一；重复 id 默认报错。
- 单个输入文件校验失败时，默认整个 rebuild 失败，避免发布半新半旧订阅。
- rebuild 成功后原子写入 `<data_dir>/current/index.json`。
- `current/index.json` 包含 `index_version: 1`、`generated_at`、`sources`、`nodes`、按 user 分组的 `users`，以及供 HTTP 服务读取的 `access`。
- input 文件必须是 `input_schema: proxystack.subscription-input`、`input_version: 1`；缺少 `input_schema` 的 v1 文件按兼容输入读取，其他 schema 或版本会失败。

本地 agent 默认会从当前 stack 生成一个 input 文件，也可以打包成 bundle：

```bash
proxystack-agent sub export-input --source usa1 -o usa1.yaml
proxystack-agent publish --source usa1 -o sub-bundle.zip
```

agent 也可以直接消费已有 inputs 目录：

```bash
proxystack-agent sub validate-inputs --input-dir ./inputs
proxystack-agent render sub --input-dir ./inputs
proxystack-agent publish --input-dir ./inputs --source merged -o sub-bundle.zip
```

当 `--input-dir` 存在时，`publish` 默认只使用该目录里的输入文件；如需同时包含当前 stack 生成的输入，可增加 `--include-stack`。`--include-stack` 会先生成当前 stack 的临时 input，再与 `--input-dir` 中的文件按同一套规则合并。

## 7. 订阅发布包

本地 `proxystack-agent publish` 将订阅 input 和 manifest 打包为远端可导入的发布包：

```text
sub-bundle.zip
  manifest.json
  inputs/
    <source>.yaml
```

P0 使用内置渲染器，不需要模板目录。P0 发布包只允许包含 `manifest.json` 和 `inputs/*.yaml|*.yml|*.json`，导入时会拒绝绝对路径、反斜杠、`..` 和其他未知成员。

`manifest.json` 示例：

```json
{
  "bundle_schema": "proxystack.sub-bundle",
  "bundle_version": 1,
  "source": "usa1",
  "generated_at": "2026-06-05T12:00:00+08:00",
  "inputs_sha256": {
    "usa1.yaml": "..."
  },
  "template_version": "builtin-v1",
  "access": {
    "type": "token",
    "token": "<subscription-token>"
  }
}
```

发布包安全边界：

- 包含客户端订阅所需节点信息。
- 包含客户端连接所需凭据，例如 vmess uuid、shadowsocks password、socks/http auth。
- 不包含完整 stack。
- 不包含 clash upstream、proxy-groups、rules、mode。
- 不包含 mihomo controller 配置。
- 不包含本地运行目录和 systemd 信息。
- manifest 必须是 `bundle_schema: proxystack.sub-bundle`、`bundle_version: 1`；缺少 `bundle_schema` 的 v1 发布包按兼容输入读取，原生备份包等其他 schema 会被拒绝。

`proxystack-sub import sub-bundle.zip` 校验 manifest 和 hash 后，把 bundle 内的 inputs 解包到 `<data_dir>/inputs/`，默认执行 rebuild 并原子切换 `current` 指针；只有传入 `--no-rebuild` 时才跳过 rebuild。`proxystack-sub serve` 只读取 `current/index.json` 和模板。

本地部署默认数据目录是 `/opt/proxystack/sub`。Docker 部署默认数据目录是容器内 `/data`，需要由宿主机 volume 持久化。

## 8. manifest

每次 `start` 写入 manifest：

```json
{
  "config_hash": "...",
  "stack_hashes": {
    "usa1": "...",
    "usa2": "..."
  },
  "generated_at": "2026-06-05T12:00:00+08:00",
  "files": [
    {
      "path": "/opt/proxystack/runtime/generated/xray/usa1.json",
      "sha256": "...",
      "service": "proxystack-xray@usa1.service"
    }
  ]
}
```

manifest 用于：

- 判断哪些服务需要重启。
- `status` 展示当前生成版本。
- 保留上一版生成文件快照，为 P1 显式 rollback 命令提供数据。
- 为 M5 原生配置备份设计提供运行状态参考；P0/P1 不实现通用配置备份恢复。
