# CLI 与服务管理

## 1. 命令分组

默认配置文件是 `/opt/proxystack/config.yaml`。所有命令支持 `-c/--config` 指定其他全局配置文件。

```text
proxystack-agent
  init
  setup
  add
  config [name]
  list
  remove
  clone
  check
  start
  stop
  restart
  status
  logs
  ipinfo
  enable
  disable
  doctor
  validate
  render
  install
  update
  service
  sub
  version

proxystack-sub
  version
  import
  serve
```

短命令别名：

```text
ps-agent = proxystack-agent
ps-sub = proxystack-sub
```

常用命令面向日常管理；高级命令保留给排障、自动化和精细控制。

## 2. 文件布局

```text
/opt/proxystack/
  .venv/
  config.yaml
  stacks/
    usa1.yaml
    usa2.yaml
    auto.yaml
  runtime/
  publish/
  downloads/
  sub/
    config.yaml
    inputs/
```

- `config.yaml`：全局配置和默认值；agent 运行期不写，只有 `init` 和 `edit` 这类配置管理命令可以写。
- `stacks/<name>.yaml`：单个 stack 配置，包含该 stack 的 xrelay 和 clash。
- `runtime/`：manifest、生成文件和运行状态。
- `publish/`：订阅发布包。
- `downloads/`：mihomo、xray-core、geo 数据下载缓存。
- `sub/`：本地非 Docker 订阅服务数据目录，由 `proxystack-sub` 写入。

systemd unit 文件仍需要安装到系统目录，这是 systemd 的要求；unit 内容应指向 `/opt/proxystack` 内的配置、虚拟环境和生成文件。

目录写入边界：agent 可写 `runtime/`、`publish/`、`downloads/` 和 `stacks/`；sub 只写 `sub/inputs/`，并读取 `sub/config.yaml`。agent 不直接写 `sub/inputs/`。

## 3. 日常命令

```bash
proxystack-agent init
proxystack-agent setup
proxystack-agent config
proxystack-agent add usa1
proxystack-agent config usa1
proxystack-agent list
proxystack-agent clone usa1 usa2
proxystack-agent export
proxystack-agent import proxystack-backup.zip
proxystack-agent check
proxystack-agent start
proxystack-agent start usa1
proxystack-agent stop usa1
proxystack-agent restart usa1
proxystack-agent status
proxystack-agent logs usa1 --follow
proxystack-agent ipinfo usa1
proxystack-agent sub export
proxystack-agent sub export usa1
proxystack-agent doctor
```

命令语义：

- `init`：创建 `/opt/proxystack` 目录结构、默认 `config.yaml` 和初始 `sub/config.yaml`；优先以 `examples/config.yaml` 为模板并改写 `base_dir`、`external_host`，模板缺失时使用内置默认值；已存在文件默认不覆盖。
- `setup`：按顺序执行幂等初始化、`install all` 和 `service install`，适合首次安装后补齐运行依赖和 systemd unit。
- `config`：安全编辑 `/opt/proxystack/config.yaml`；等价于 `edit` 不带 stack 名称，但语义更明确。
- `add <name>`：创建 `/opt/proxystack/stacks/<name>.yaml`，默认使用 `pair` 模板，不覆盖已有 stack。
- `edit`：编辑 `/opt/proxystack/config.yaml`。
- `edit <name>`：编辑 `/opt/proxystack/stacks/<name>.yaml`。
- `list`：列出 stack 文件、enabled 状态、角色、生成文件状态、运行状态、xrelay `user/protocol:port` 和 clash 主要端口；默认不做系统端口占用检查，需要严格检查时使用 `--check-system-ports`。
- `remove <name>`：删除 `stacks/<name>.yaml`；`--purge` 会同时清理 manifest 中该 stack 对应的生成文件。
- `clone <source> <target>`：复制已有 stack 文件为新 stack，并改写顶层 `name` 和自身 ref。
- `export`：导出 agent 原生配置备份包，默认输出到 `/opt/proxystack/publish/proxystack-backup.zip`。
- `import <backup.zip>`：导入 agent 原生配置备份包，默认拒绝覆盖既有 `config.yaml` 或同名 stack。
- `check [target]`：校验配置并展示生成变更预览，不写文件、不操作服务。
- `start [target]`：先检查目标服务需要的 `mihomo`/`xray` 是否已安装且可执行，再生成配置并写 manifest；配置有变化时重启受影响服务，并启动目标范围内未变化的服务；`start sub` 只启动 `proxystack-sub.service`。
- `stop [target]`：通过 systemd 停止目标范围内服务，不删除配置和生成文件。
- `restart [target]`：先检查目标服务需要的 `mihomo`/`xray` 是否已安装且可执行，再生成配置并写 manifest，然后通过 systemd 重启目标范围内服务；`restart sub` 不读取 stack。
- `status [target]`：通过 systemd 查询目标范围内服务状态。
- `logs [target]`：通过 `journalctl` 查看目标范围内服务日志；`logs <stack> -f` 会在一次 `journalctl` 调用中同时订阅该 stack 的 mihomo 和 xray unit。
- `ipinfo <stack>`：通过该 stack 的 mihomo socks listener 查询出口 IPv4/IPv6 和地域信息；默认按 IPv4/IPv6 使用不同来源，过滤已知不适合该 family 的来源；需要系统已安装 `curl`。
- `enable [target]`：通过 systemd 设置目标范围内服务开机自启。
- `disable [target]`：通过 systemd 取消目标范围内服务开机自启。
- `sub export [stack]`：生成订阅发布包；缺省导出全部 stack，指定 stack 时只导出该 stack。
- `doctor`：检查目录权限、二进制版本、systemd unit、端口占用和配置引用。

## 4. 作用域规则

不传目标或传 `all` 时，`check/start/stop/restart/status/logs/enable/disable` 作用于全部 enabled stack。传目标时只作用于指定范围：

```bash
proxystack-agent start              # 全部 enabled stack
proxystack-agent start usa1         # usa1 的 xray + clash
proxystack-agent start xrelay/usa1  # 只操作 usa1 的 Xray
proxystack-agent start clash/usa1   # 只操作 usa1 的 mihomo
proxystack-agent start sub          # 只操作本地订阅服务
```

`sub` 只代表本机部署的 `proxystack-sub.service`。远端 Docker 部署的订阅服务由 `proxystack-sub` 容器命令或 Docker 管理。本机 `sub` 服务只使用 `/opt/proxystack/sub`，不读取全局 `config.yaml` 和 `stacks/`。

Task09 P0 已接入真实 systemd runner；测试通过 fake runner 和 fake unit_dir 隔离真实 `systemctl`、`journalctl` 和 `/etc/systemd/system`。`service log --follow/-f` 直接流式输出 journal。订阅服务命令是 `proxystack-sub import/serve`。

服务生命周期命令默认跳过系统端口占用检查，避免在服务已经运行并占用自身监听端口时阻断 `status/restart/start` 等操作；配置结构、ref 和重复端口仍会校验。`start sub` 不读取或改写 stack 文件，也不会创建 `runtime/generated`。

## 5. add/edit/clone/remove

```bash
proxystack-agent add usa1
proxystack-agent add usa2
proxystack-agent add auto --template auto-url-test
proxystack-agent add auto --template auto-url-test --members usa1,usa2
proxystack-agent add auto-balance --template load-balance
proxystack-agent add usa2 --from-file ./usa2.yaml
proxystack-agent add usa3 --no-edit
proxystack-agent add fixed --keep-template-ports
proxystack-agent config usa1
proxystack-agent clone usa1 usa2
proxystack-agent clone usa1 usa2 --allocate-ports
proxystack-agent remove usa2
```

模板：

- `pair`：普通 `xrelay -> clash` stack，默认模板。
- `auto-url-test`：auto stack，使用 mihomo `url-test`。
- `load-balance`：auto stack，使用 mihomo `load-balance`。

`add --from-file` 要求输入文件是单个 stack 配置，包含 `name`、`xrelay` 和 `clash`。写入前必须校验文件名和 `name` 一致。

`add` 创建 stack 后默认会打开编辑器并在保存后校验；自动化脚本可使用 `--no-edit` 跳过编辑。独立的 `config` 命令用于编辑全局 `config.yaml`；`edit <name>` 用于再次编辑已有 stack，`edit` 不带名称时仍兼容编辑全局 `config.yaml`。

`add` 默认会基于 `config.yaml` 的 `port_ranges` 自动分配 xrelay inbound、xrelay API、clash socks 和 clash controller 端口，避免连续新增 stack 时撞上模板固定端口。需要保留模板端口时使用 `--keep-template-ports`；此时端口仍必须合法、唯一且未被系统占用。

`add` 使用内置模板时会把 xrelay vmess inbound 的模板占位 UUID 自动替换为随机 UUID；`--from-file` 会保留输入文件中的 UUID。

`clone --allocate-ports` 会基于相同端口池重新分配克隆目标的端口。自动分配只选择当前配置未使用且系统未占用的端口；无法分配时命令失败并提示用户修改端口池。手写端口可以在端口池之外，但仍必须合法、唯一且未被系统占用。

`add auto --members usa1,usa2` 会根据成员 stack 的 socks5 inbound 自动生成 `xrelay-socks5` upstream refs。未指定 `--members` 时，模板只生成禁用草稿和占位 ref，用户需要手动编辑成员 ref 后再启用。

`clone` 复制规则：

- 必须保证 `<target>` 不存在。
- 复制 `stacks/<source>.yaml` 到 `stacks/<target>.yaml`。
- 顶层 `name` 改为 `<target>`。
- ref 第一段等于 `<source>` 且指向自身资源时，自动改为 `<target>`；指向其他 stack 的 ref 保持不变。
- 当前 stack 内的明文凭据默认保持不变；用户需要新密码时可编辑生成后的 stack 文件。
- 默认不自动改端口；如果原端口会导致全局校验失败，命令拒绝写入目标文件。使用 `--allocate-ports` 时按端口池重新分配本 stack 内端口，用户仍需执行 `check/start`。

`remove` 默认不删除生成文件，只删除或归档 stack 配置。需要清理生成文件时使用 `--purge`。

## 6. validate/check/start

```bash
proxystack-agent validate
proxystack-agent validate usa1
proxystack-agent check
proxystack-agent check usa1
proxystack-agent start
proxystack-agent start usa1
```

- `validate`：校验 `config.yaml`、所有 stack 文件、端口、ref、rules、mode、安全约束和明文字段格式。
- `check`：执行完整编译，对比 manifest，展示将生成/修改/删除的文件和建议重启的服务，不写文件。
- `start`：检查代理核心二进制、生成配置并写 manifest；重启受生成文件变化影响的服务，并启动目标范围内未变化的服务。

顶层不再提供 `plan`、`apply`、`up`、`down` 子命令；日常服务控制使用 `start`、`stop`、`restart`。

`start` 和 `restart` 会在调用 systemd 前检查目标服务需要的代理核心二进制：

- `clash/<name>` 或 stack 中启用的 clash 服务需要 `config.paths.bin/mihomo`。
- `xrelay/<name>` 或 stack 中启用的 xrelay 服务需要 `config.paths.bin/xray`。
- 文件缺失或没有可执行权限时命令失败，并提示先执行 `ps-agent install all` 或按需执行 `ps-agent install mihomo|xray`。

## 7. render

```bash
proxystack-agent render model
proxystack-agent render xrelay usa1
proxystack-agent render clash auto
proxystack-agent render sub
proxystack-agent render sub --input-dir ./inputs
```

- `render model`：输出解析后的完整中间模型，用于检查默认值补齐、ref 解析结果、依赖图和最终 rules，不写入运行目录。
- `render xrelay <name>`：输出指定 stack 的 Xray JSON。
- `render clash <name>`：输出指定 stack 的 mihomo YAML。
- `render sub`：基于当前 enabled stack 生成订阅索引。
- `render sub --input-dir <dir>`：读取已有 inputs 目录并输出合并后的订阅索引。

原生 `export/import` 只用于当前 proxystack agent 配置备份恢复，不支持从旧 `clash`、`xrelay`、`clashsub` 或旧 `proxy-stack` 目录自动导入；这些目录只作为人工参考，不进入实现范围。

## 8. 下载安装

mihomo、xray-core 和 geo 数据的下载安装在功能清单内，由显式命令触发：

```bash
proxystack-agent install mihomo
proxystack-agent install xray
proxystack-agent install geo
proxystack-agent install all

proxystack-agent update mihomo
proxystack-agent update xray
proxystack-agent update geo
proxystack-agent update all
proxystack-agent update self --wheel proxystack-<version>-py3-none-any.whl
proxystack-agent update self "proxystack==<version>"

proxystack-agent version
proxystack-agent version mihomo
proxystack-agent version xray
proxystack-agent version geo
```

P0 候选版行为：

- 单个目标支持 `--version`、`--sha256`、`--source/--url`、`--archive-member` 和 `--config`。
- `all` 只展开为 `mihomo`、`xray` 和 `geo`，不包含 `self`；`all` 使用 `config.install.<target>` 中分别配置的 `source`、`sha256` 和 `archive_member`，避免把同一个源误装到多个目标。
- `mihomo`、`xray` 和 `geo` 的 `source` 支持 `auto`、`github`、`r2` 三个托管源别名；未配置 source 时默认使用 `auto`，按 GitHub Release 优先、Cloudflare R2 回退的顺序下载。
- `geo` 的托管源沿用 `../clash` 的 geoip 规则，默认下载 `MetaCubeX/meta-rules-dat` 的 `geoip.metadb`，安装到 `/opt/proxystack/geo/geoip.metadb`。
- 远端 `http/https` 下载必须提供 sha256；生产下载路径会拒绝本机/私网地址、禁用 HTTP 重定向，并在 DNS 解析到私网地址时失败。
- 托管源别名只允许下载内置的 mihomo/xray/geo 资产；`sha256` 可选，提供时仍会校验下载文件摘要。
- 本地文件也建议提供 sha256。sha256 不匹配时不会替换既有文件；多文件 geo 归档替换失败时会回滚已替换文件。
- mihomo 官方 `.gz` 资产会自动解压后安装为可执行文件。
- 归档源支持 zip/tar，并拒绝绝对路径或 `..` 路径穿越；二进制归档未能唯一识别 `mihomo` 或 `xray` 成员时，需要显式传 `--archive-member`。
- `install/update mihomo|xray` 默认写入 `/opt/proxystack/bin`，代理核心二进制 owner 为 `proxystack:proxystack`，权限为 `0750`。
- `install/update geo` 默认写入 `/opt/proxystack/geo`，geo 数据文件 owner 为 `proxystack:proxystack`，权限为 `0640`。
- `install` 是幂等安装：目标二进制或 geo 数据已存在时会跳过下载和替换；需要强制重新下载时使用 `update`。
- `update self` 只更新 proxystack Python 包，默认不更新 mihomo、xray-core 或 geo 数据。
- `update self` 只调用 `/opt/proxystack/.venv/bin/python -m pip install --upgrade`，支持 `--wheel <file>` 或 package spec；CLI 会校验 `.venv` 可写，不自动提权。
- `install all` 只覆盖 mihomo、xray-core 和 geo 数据，不包含 systemd unit。
- `update all` 默认只更新代理核心和 geo 数据，不包含 `self`，避免无意中升级管理工具本身。
- 不在服务启动时自动下载，避免运行期副作用。
- 更新二进制时，P0 仍只输出服务计划，不真实停止、启动或重启服务；真实 systemd 动作需要用户显式执行 `service` 分组或顶层生命周期命令。

配置示例：

```yaml
install:
  mihomo:
    version: latest
    source: auto
  xray:
    version: v26.3.27
    source: r2
  geo:
    version: latest
    source: auto
```

## 9. systemd 服务管理

```bash
proxystack-agent service install [target]
proxystack-agent service uninstall [target]
proxystack-agent service enable [target]
proxystack-agent service disable [target]
proxystack-agent service start [target]
proxystack-agent service stop [target]
proxystack-agent service restart [target]
proxystack-agent service status [target]
proxystack-agent service log [target] --follow
```

`start/stop/restart/status/logs/enable/disable` 是 `service` 分组的常用包装；顶层 `start` 和 `restart` 会先生成配置。

`service install|uninstall` 写 `/etc/systemd/system/`，必须以 root 或具备等价 systemd 管理权限的用户运行；其他服务生命周期命令权限不足时必须给出明确错误。

systemd unit 安装入口统一为 `service install [target]`，不在 `install` 分组中提供 unit 相关子命令，避免和代理核心下载安装命令混用。

如果 `start`、`restart`、`status`、`logs`、`enable` 或 `disable` 提示 `Unit ... not found`，表示 unit 文件尚未安装，需要先执行 `ps-agent service install [target]`。

目标规则：

- 不传目标或传 `all`：`service install|uninstall` 管理三个 unit 文件；`service start|stop|restart|status|log|enable|disable` 作用于全部 enabled stack 和 `proxystack-sub.service`。
- `usa1`：作用于该 stack 的 xray 和 mihomo 服务实例。
- `xrelay/usa1`：只作用于 `proxystack-xray@usa1.service`。
- `clash/usa1`：只作用于 `proxystack-clash@usa1.service`。
- `sub`：只作用于 `proxystack-sub.service`，不会读取 stack。

`service log` 代理 `journalctl -u <unit> --no-pager -n 100`；多服务 follow 会在一次 `journalctl` 调用中传入多个 `-u`；传 `--follow/-f` 时追加 `-f`。`systemctl` 或 `journalctl` 返回非零时，CLI 会失败并展示 stdout/stderr 摘要，不吞掉权限错误。

systemd 单元：

```text
proxystack-xray@usa1.service
proxystack-clash@usa1.service
proxystack-sub.service
```

unit 内容约束：

- 三个 unit 均使用 `User=proxystack`、`Group=proxystack`、`NoNewPrivileges=true`、`ProtectSystem=strict`、`ProtectHome=true`、`PrivateTmp=true`。
- `proxystack-xray@.service` 只执行 `/opt/proxystack/bin/xray run -config /opt/proxystack/runtime/generated/xray/%i.json`。
- `proxystack-clash@.service` 只执行 `/opt/proxystack/bin/mihomo -f /opt/proxystack/runtime/generated/mihomo/%i.yaml`。
- xray/clash unit 的 `ReadWritePaths` 仅包含 agent runtime 相关目录。
- `proxystack-sub.service` 只执行 `proxystack-sub serve --config <sub_dir>/config.yaml`，`ReadWritePaths` 仅包含 `config.paths.sub`。

## 10. 原生配置备份与恢复

```bash
proxystack-agent export
proxystack-agent export -o /opt/proxystack/publish/proxystack-backup.zip
proxystack-agent import proxystack-backup.zip
proxystack-agent import proxystack-backup.zip -c /opt/proxystack/config.yaml --base-dir /opt/proxystack
proxystack-agent import proxystack-backup.zip --force
```

原生备份包用于 agent 到另一个 agent 的配置迁移。包内只包含：

- `manifest.json`：备份包 schema、版本和文件 sha256。
- `config/config.yaml`：全局配置。
- `stacks/*.yaml`：stack 配置。

备份包不包含 `runtime/`、`runtime/generated/`、`publish/`、`downloads/`、`.venv/`、`bin/`、`geo/` 或 systemd unit。`runtime` 和生成配置都可以由 `check/start/render` 根据 config 和 stacks 重新生成，导入旧 runtime 反而可能携带过期 hash、旧路径或旧机器状态。

导入规则：

- 导入前校验 `backup_schema: proxystack.native-backup`、`backup_version: 1`、zip 成员路径、文件 sha256、config schema、stack schema 和跨 stack 引用。
- `--base-dir` 缺省使用 `-c/--config` 指向的 `config.yaml` 所在目录，并会写回导入后的 `config.yaml`。
- 默认不覆盖已存在的目标 `config.yaml` 或同名 stack；需要覆盖时显式传 `--force`。
- 导入写入的 stacks 目录必须位于目标 `base_dir` 内，避免备份包把文件写到任意系统路径。
- `sub-bundle.zip` 不能用 `proxystack-agent import` 导入；订阅发布包仍使用 `proxystack-sub import`。

## 11. 订阅发布与远端服务

```bash
proxystack-agent sub export
proxystack-agent sub export usa1
proxystack-agent sub export usa1 -o /opt/proxystack/publish/usa1-sub-bundle.zip
proxystack-agent sub validate-inputs --input-dir ./inputs
proxystack-agent render sub --input-dir ./inputs
proxystack-sub import sub-bundle.zip
proxystack-sub import sub-bundle.zip --replace-all
proxystack-sub serve --host 0.0.0.0 --port 3003 --data-dir /opt/proxystack/sub
```

HTTP 路由：

```text
GET /health
GET /sub/:user
GET /premium_sub/:user
GET /surge_sub/:user
```

订阅相关命令区别：

- `sub export`：常用入口，默认生成 `/opt/proxystack/publish/sub-bundle.zip`，包内按 stack 写入 `inputs/<stack>.yaml`。
- `sub export <stack>`：只导出指定 stack，默认生成 `/opt/proxystack/publish/<stack>-sub-bundle.zip`。
- `sub validate-inputs`：只校验 `inputs/` 目录，不生成发布包。
- `render sub`：只输出订阅索引，不写文件；加 `--input-dir` 时输出多 input 合并后的结果。

订阅服务启动时扫描 `<data_dir>/inputs/` 并构建内存索引，请求处理只读取内存索引，不读取 `current/index.json`、全局 `config.yaml` 或 stack 文件。服务运行期间会监控 inputs 目录，Linux 优先使用 inotify，不可用时回退轮询；input 增加、删除、修改或原子替换后会重新加载整个 inputs 目录。`proxystack-sub import` 只校验发布包并增量写入或覆盖同名 input，`--replace-all` 会先清空旧 input。订阅访问 token 来自 ps-sub 配置文件，例如 `/opt/proxystack/sub/config.yaml`：

```yaml
listen: 0.0.0.0:3003
access:
  type: token
  token: "<subscription-token>"
```

`data_dir` 可以写在 ps-sub 配置里；如果省略，默认使用该配置文件所在目录。

本机 systemd 生命周期由 `proxystack-agent service ... sub` 或 `proxystack-agent start sub/status sub/logs sub` 管理；订阅内容变更的主流程是 `sub export + sub import`，运行中的服务会由 watcher 自动 reload。

## 12. mihomo 辅助命令

P1 实现：

```bash
proxystack-agent mihomo groups usa1
proxystack-agent mihomo set usa1 AllProxy server-a
proxystack-agent mihomo ipinfo usa1
```

这些命令依赖 mihomo REST API，失败时不能影响配置生成主流程。
