# 配置生成规则

## 1. 总体原则

`proxystack-agent start` 的配置生成输入只有 `/opt/proxystack/config.yaml` 和 `/opt/proxystack/stacks/*.yaml`，输出包括：

- Xray JSON：`/opt/proxystack/runtime/generated/xray/<stack>.json`
- mihomo YAML：`/opt/proxystack/runtime/generated/mihomo/<stack>.yaml`
- 本地订阅输入：`/opt/proxystack/runtime/generated/sub/inputs/<source>.yaml`
- 本地订阅索引：`/opt/proxystack/runtime/generated/sub/index.json`
- manifest：`/opt/proxystack/runtime/manifest.json`

订阅发布包不由 `start` 隐式生成，需显式执行 `proxystack-agent sub export`，默认输出 `/opt/proxystack/publish/sub-bundle.zip`。

生成器必须满足：

- 同一份 config 和 stack 文件多次生成结果稳定。
- 未变化的生成文件不改写，避免无意义重启服务。
- 生成前先执行完整校验。
- `sub` 只影响订阅 input/index 和发布包，不影响 Xray inbound 是否生成。
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

用户显式配置 `tag` 时使用用户值；否则自动生成。tag 用于 Xray inbound 标识；vmess 和 shadowsocks 多用户订阅节点可以用 `users[].tag` 覆盖。

vmess 规则：

- 必须提供 `network`。
- 必须提供非空 `users`；单用户也写成一条 `users` 记录。
- 不支持顶层 `uuid`，顶层 `user` 和 `remark` 也不用于 vmess。
- `users` 结构使用 `users[].user`、`users[].uuid`、`users[].remark`、可选 `users[].tag` 和可选 `users[].email`；`users` 只能用于 vmess。
- 同一 inbound 内 `users[].user`、`users[].uuid`、最终 email 和最终订阅 tag 不能重复。
- 多用户 vmess 生成一个 Xray inbound，`settings.clients` 中每个用户生成一个 client，包含 `id`、`alterId: 0` 和用于用户统计的 `email`。

shadowsocks 规则：

- 必须提供 `method` 或 `cipher`，生成到 Xray `settings.method`。
- 必须提供 `password`，单用户时作为客户端密码；多用户时仍写入 Xray `settings.password`。
- `users` 非空时启用多用户，生成到 Xray `settings.users[]`。
- 传统 SS 多用户允许 `users[].method` 或 `users[].cipher` 覆盖单个用户 method，未配置时继承 inbound method。
- SS2022 多用户不允许配置 `users[].method` 或 `users[].cipher`，统一使用 inbound method。
- SS2022 的 inbound `password` 和 `users[].password` 必须是 base64 PSK；`2022-blake3-aes-128-gcm` 使用 16 字节 key，`2022-blake3-aes-256-gcm` 和 `2022-blake3-chacha20-poly1305` 使用 32 字节 key。
- SS2022 订阅节点密码使用 `ServerPassword:UserPassword`，其中 ServerPassword 来自 inbound `password`，UserPassword 来自 `users[].password`。
- 支持 method：`2022-blake3-aes-128-gcm`、`2022-blake3-aes-256-gcm`、`2022-blake3-chacha20-poly1305`、`aes-256-gcm`、`aes-128-gcm`、`chacha20-poly1305`、`chacha20-ietf-poly1305`、`xchacha20-poly1305`、`xchacha20-ietf-poly1305`、`none`、`plain`。

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

生成的 Xray outbound `tag` 固定为 `egress-{stack}`，例如 `egress-usa1`，便于日志和 stats 中按 stack 区分出口。

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

订阅 input/index 只来自启用的 xrelay inbound：

```text
stacks/*.yaml xrelay.inbounds[] where sub == true
```

订阅字段来源：

- `server`：默认使用 `config.yaml` 中的 `external_host`，允许 inbound 覆盖。
- `port`：xrelay inbound 的 `port`。
- `user`：普通单用户 inbound 使用 inbound 的 `user`；vmess 和 shadowsocks 多用户使用 `users[].user`。
- `tag`：普通单用户 inbound 优先使用 inbound 显式 `tag`，否则生成 `<protocol>:<port>:<inbound.name>`；多用户优先使用 `users[].tag`，否则生成 `<inbound tag>:<users[].user>`。
- `remark`：最终订阅节点展示名由 `subscription.remark_policy` 生成。默认 `prefix-source` 会输出 `{source}-{remark}`；显式 `remark` 缺失时 `{remark}` 使用 `<protocol>:<port>:<user>`，例如 `usa1-vmess:24101:alice`。
- `region`：可选国家/地区简称，只校验两位大写字母格式，不限制固定国家列表，例如 `US`、`HK`、`JP`。普通单用户节点来自 inbound；vmess 和 shadowsocks 多用户节点优先使用 `users[].region`，未配置时继承 inbound 的 `region`。
- `subscription.remark_policy: preserve` 会保留旧规则：普通单用户 inbound 优先 `remark`，其次 `tag`，最后 `<stack>-<inbound.name>`；多用户优先 `users[].remark`，其次 `users[].tag`，最后 `<stack>-<inbound.name>-<users[].user>`。
- `subscription.remark_policy: template` 使用 `subscription.remark_template`，支持 `{source}`、`{inbound}`、`{protocol}`、`{port}`、`{user}`、`{remark}`。
- 协议参数：来自 inbound 本身。

不会读取：

- `clash.upstreams`
- `clash.groups`
- `clash.rules`
- `clash.mode`
- `clash.controller`

HTTP 路由：

- `/sub/:user`：普通 Clash。
- `/premium_sub/:user`：Premium Clash。
- `/surge_sub/:user`：Surge。

Clash/Premium Clash 订阅输出可直接导入客户端的完整配置，包含基础监听、DNS、tun、`proxies`、默认 `proxy-groups` 和默认 `rules`。Premium Clash 默认模板的 `proxy-groups` 与 Surge 默认 `[Proxy Group]` 的组名和数量保持一致，并使用 Mihomo/Clash Premium 的 `icon` 字段承载 Surge 对应的 `icon-url`；业务组、`icon`、`rule-providers` 和 `rules` 都直接写在 `premium-clash.yaml.j2` 中，方便手动修改。Premium Clash 的 `rule-providers` 使用 R2 上的 Clash YAML 规则源，路径从 Surge 的 `/surge/*.list` 对应转换为 `/clash/*.yaml`。Surge 订阅输出 `[General]`、`[Replica]`、`[Proxy]`、`[Proxy Group]` 和 `[Rule]` 段；HTTP `/surge_sub/:user` 响应会在第一行输出 `#!MANAGED-CONFIG ... interval=86400 strict=true`，让 Surge 自动刷新托管配置。默认 `[Proxy Group]` 会包含带 emoji 和 `icon-url` 的常用地区组、实际出现的其他两位地区组和 `OtherRegion`，地区优先来自 `nodes[].region`，缺失时从 `remark` 前缀解析 `US-xxx`、`[US] xxx` 或 `HK_01` 这类格式。默认模板直接列出节点，不再生成 `MySub`、`policy-path` 或 `include-other-group`。

三类订阅配置均由 Jinja2 模板渲染。模板查找顺序为：

1. `ps-sub config.yaml` 中 `templates_dir/sub/<template>`。
2. `ps-sub config.yaml` 中 `templates_dir/<template>`。
3. `<data_dir>/templates/sub/<template>`。
4. 包内默认模板 `src/proxystack/templates/sub/<template>`。

默认模板文件名：

- `clash.yaml.j2`
- `premium-clash.yaml.j2`
- `surge.conf.j2`

公共模板上下文包含 `user`、`generated_at`、`sources`、`nodes`、`proxies`、`proxy_names`、`proxy_groups`、`clash_rules`、`surge_proxy_lines`、`surge_region_groups`、`surge_rules`、`test_url`、`surge_skip_proxy`、`surge_proxylist_icon_url` 和 `surge_auto_icon_url`。Surge HTTP 渲染会额外注入 `managed_config_url`、`managed_config_interval` 和 `managed_config_strict`。模板可使用 `yaml_block` filter 渲染 YAML 片段。

订阅访问控制：

- agent 全局配置不再包含订阅服务 access；本地 `render sub` 预览默认输出 `access.type: none`。
- `proxystack-sub serve` 的 HTTP 鉴权只读取 ps-sub 配置文件中的 `access` 字段，默认配置来自 `src/proxystack/templates/sub-config.yaml`。
- `access.type: token` 时，HTTP 路由必须校验 `token` query 参数或等价的反向代理鉴权头。
- `access.type: none` 只允许本地监听或明确的公网风险确认。
- token 只用于访问订阅 HTTP 服务，不写入订阅节点。
- `managed_config.enabled: true` 时，`/surge_sub/:user` 会把当前请求 URL 写入 `#!MANAGED-CONFIG`；如果服务在反向代理后面，建议配置 `managed_config.public_base_url` 为公网前缀，例如 `https://www.rustez.cc/api/sub`。当请求带 `token` query 参数时，托管 URL 会保留该 token，确保 Surge 自动更新不会 401。

用户不存在或没有订阅节点时返回 `404` 和统一 JSON 错误结构。

## 6. 订阅输入和多文件合并

Subscription input 是 agent 和 sub 共享的格式。`proxystack-sub` 支持类似 `clashsub` 的 inputs 目录，`proxystack-agent` 也可以直接读取同一目录来校验和预览合并结果：

```text
<data_dir>/
  config.yaml
  inputs/
    usa1.yaml
    usa2.yaml
    auto.yaml
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
    region: US
    auth:
      type: password
      username: usa1
      password: "<client-credential>"
```

订阅 input 中允许出现客户端连接所需凭据，例如 vmess uuid、shadowsocks password、socks/http username/password。它不包含完整 stack、clash upstream、proxy-groups、rules、mode 或 mihomo controller 配置。

合并规则：

- `proxystack-sub serve` 启动时扫描 `<data_dir>/inputs/*.yaml`、`*.yml`、`*.json` 并构建内存索引。
- `proxystack-agent render sub --input-dir <dir>` 可以输出合并后的订阅索引。
- 只合并通过 schema 校验的输入文件。
- 按文件名排序后合并，保证结果稳定。
- 按 `nodes[].user` 分组生成订阅。
- `nodes[].id` 必须全局唯一；重复 id 默认报错。
- 启动阶段单个输入文件校验失败时服务启动失败；运行阶段 reload 失败时保留上一份可用内存索引。
- 服务运行期间监控 inputs 目录，Linux 优先使用 inotify，不可用时回退轮询；`.yaml`、`.yml`、`.json` input 文件增加、删除、保存完成或原子替换后会重新扫描整个 inputs 目录，并输出 watcher 触发和 reload 成败日志；临时文件和属性变化不会触发 reload。
- access token 从 `<data_dir>/config.yaml` 的 `access` 字段读取，不写入发布包，也不写入 index 文件。
- 可选 `templates_dir` 指向本地模板根目录；未配置时可直接在 `<data_dir>/templates/sub/` 放置同名模板覆盖包内默认模板。
- input 文件必须是 `input_schema: proxystack.subscription-input`、`input_version: 1`；缺少 `input_schema` 的 v1 文件按兼容输入读取，其他 schema 或版本会失败。

本地 agent 使用统一导出命令生成订阅发布包：

```bash
proxystack-agent sub export
proxystack-agent sub export usa1
proxystack-agent sub export usa1 --summary
```

`sub export` 缺省导出全部 stack，包内按 stack 写入 `inputs/<stack>.yaml`；指定 stack 时只导出该 stack，并默认写到 `/opt/proxystack/publish/<stack>-sub-bundle.zip`。`--summary` 或 `--dry-run` 只输出将写入发布包的 input、node、user 数量和最终订阅节点展示名，不写 zip。

agent 仍可以只读消费已有 inputs 目录用于校验或预览：

```bash
proxystack-agent sub validate-inputs --input-dir ./inputs
proxystack-agent render sub --input-dir ./inputs
```

## 7. 订阅发布包

本地 `proxystack-agent sub export` 将订阅 input 和 manifest 打包为远端可导入的发布包：

```text
sub-bundle.zip
  manifest.json
  inputs/
    <stack>.yaml
```

发布包只允许包含 `manifest.json` 和 `inputs/*.yaml|*.yml|*.json`，导入时会拒绝绝对路径、反斜杠、`..` 和其他未知成员。

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
    "type": "none"
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
- manifest 中的 `access` 保留为 schema 字段，但当前 `write_bundle` 固定写入 `none`，`proxystack-sub import` 不用它配置订阅服务 token。
- 不包含订阅服务 access token；token 只在 ps-sub 配置文件中配置。
- manifest 必须是 `bundle_schema: proxystack.sub-bundle`、`bundle_version: 1`；缺少 `bundle_schema` 的 v1 发布包按兼容输入读取，原生备份包等其他 schema 会被拒绝。

`proxystack-sub import sub-bundle.zip` 校验 manifest 和 hash 后，把 bundle 内的 inputs 增量解包到 `<data_dir>/inputs/`；同名 input 会被原子替换，其它 input 会保留，适合多个 agent/stack 发布包连续导入。导入成功会输出 source、input、node、user、写入/覆盖和 `--replace-all` 删除信息。需要清空旧 inputs 后全量替换时使用 `--replace-all`。`proxystack-sub serve` 从内存索引响应请求，运行中的服务会在 inputs 变化后自动 reload。

`proxystack-sub serve` 启动时会输出 data_dir、input_dir、listen、access 类型、模板来源、input/source/node/user 统计；reload 成功时输出 input/source/node/user 统计，reload 失败时只输出错误类型并保留上一份可用内存索引。

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
- runtime 派生状态不进入原生配置备份包；`export/import` 只迁移 `config.yaml` 和 `stacks/*.yaml`。
