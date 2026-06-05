# CLI 与服务管理

## 1. 命令分组

默认配置文件是 `/opt/proxystack/config.yaml`。所有命令支持 `-c/--config` 指定其他全局配置文件。

```text
proxystack-agent
  init
  add
  edit
  list
  remove
  clone
  check
  up
  down
  restart
  status
  logs
  enable
  disable
  publish
  doctor
  validate
  plan
  apply
  render
  install
  update
  service
  sub
  mihomo

proxystack-sub
  import
  rebuild
  serve
  routes
  status
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
    inputs/
    bundles/
    current/
```

- `config.yaml`：全局配置和默认值；agent 运行期不写，只有 `init` 和 `edit` 这类配置管理命令可以写。
- `stacks/<name>.yaml`：单个 stack 配置，包含该 stack 的 xrelay 和 clash。
- `runtime/`：manifest、生成文件和运行状态。
- `publish/`：订阅发布包。
- `downloads/`：mihomo、xray-core、geo 数据下载缓存。
- `sub/`：本地非 Docker 订阅服务数据目录，由 `proxystack-sub` 写入。

systemd unit 文件仍需要安装到系统目录，这是 systemd 的要求；unit 内容应指向 `/opt/proxystack` 内的配置、虚拟环境和生成文件。

目录写入边界：agent 可写 `runtime/`、`publish/`、`downloads/` 和 `stacks/`；sub 只写 `sub/inputs/`、`sub/bundles/`、`sub/current/`。agent 不直接写 `sub/current/`。

## 3. 日常命令

```bash
proxystack-agent init
proxystack-agent add usa1
proxystack-agent edit
proxystack-agent edit usa1
proxystack-agent list
proxystack-agent clone usa1 usa2
proxystack-agent check
proxystack-agent up
proxystack-agent up usa1
proxystack-agent down usa1
proxystack-agent restart usa1
proxystack-agent status
proxystack-agent logs usa1 --follow
proxystack-agent publish
proxystack-agent doctor
```

命令语义：

- `init`：创建 `/opt/proxystack` 目录结构、默认 `config.yaml` 和示例 stack；已存在文件默认不覆盖。
- `add <name>`：创建 `/opt/proxystack/stacks/<name>.yaml`，默认使用 `pair` 模板，然后打开编辑器。
- `edit`：编辑 `/opt/proxystack/config.yaml`。
- `edit <name>`：编辑 `/opt/proxystack/stacks/<name>.yaml`。
- `list`：列出 stack 文件、enabled 状态、主要端口和服务状态。
- `remove <name>`：停止并禁用该 stack 的服务，然后删除或归档 `stacks/<name>.yaml`。
- `clone <source> <target>`：复制已有 stack 文件为新 stack，改名后打开编辑器。
- `check [target]`：执行 `validate + plan`，不写文件、不操作服务。
- `up [target]`：执行 `validate + apply`，并启动或重启目标范围内受影响的服务。
- `down [target]`：停止目标范围内的服务，不删除配置和生成文件。
- `restart [target]`：强制重启目标范围内的服务。
- `status [target]`：查看目标范围内的服务状态。
- `logs [target]`：查看目标范围内的服务日志。
- `enable [target]`：设置目标范围内服务开机自启。
- `disable [target]`：取消目标范围内服务开机自启。
- `publish`：生成订阅发布包，默认输出到 `/opt/proxystack/publish/sub-bundle.zip`。
- `doctor`：检查目录权限、二进制版本、systemd unit、端口占用和配置引用。

## 4. 作用域规则

不传目标时，`check/up/down/restart/status/logs/enable/disable` 作用于全部 enabled stack。传目标时只作用于指定范围：

```bash
proxystack-agent up              # 全部 enabled stack
proxystack-agent up usa1         # usa1 的 xray + clash
proxystack-agent up xrelay/usa1  # 只操作 usa1 的 Xray
proxystack-agent up clash/usa1   # 只操作 usa1 的 mihomo
proxystack-agent up sub          # 只操作本地订阅服务
```

`sub` 只代表本机部署的 `proxystack-sub.service`。远端 Docker 部署的订阅服务由 `proxystack-sub` 容器命令或 Docker 管理。本机 `sub` 服务只使用 `/opt/proxystack/sub`，不读取 `config.yaml` 和 `stacks/`。

## 5. add/edit/clone/remove

```bash
proxystack-agent add usa1
proxystack-agent add usa2 --allocate-ports
proxystack-agent add auto --template auto-url-test
proxystack-agent add auto --template auto-url-test --members usa1,usa2
proxystack-agent add auto-balance --template load-balance
proxystack-agent add usa2 --from-file ./usa2.yaml
proxystack-agent edit usa1
proxystack-agent clone usa1 usa2
proxystack-agent clone usa1 usa2 --allocate-ports
proxystack-agent remove usa2
```

模板：

- `pair`：普通 `xrelay -> clash` stack，默认模板。
- `auto-url-test`：auto stack，使用 mihomo `url-test`。
- `load-balance`：auto stack，使用 mihomo `load-balance`。

`add --from-file` 要求输入文件是单个 stack 配置，包含 `name`、`xrelay` 和 `clash`。写入前必须校验文件名和 `name` 一致。

`add --allocate-ports` 和 `clone --allocate-ports` 会基于 `config.yaml` 的 `port_ranges` 自动分配 xrelay inbound、clash socks 和 clash controller 端口。自动分配只选择当前配置未使用且系统未占用的端口；无法分配时命令失败并提示用户修改端口池。手写端口可以在端口池之外，但仍必须合法、唯一且未被系统占用。

`add auto --members usa1,usa2` 会根据成员 stack 的 socks5 inbound 自动生成 `xrelay-socks5` upstream refs。未指定 `--members` 时，模板只生成占位，用户需要手动编辑。

`clone` 复制规则：

- 必须保证 `<target>` 不存在。
- 复制 `stacks/<source>.yaml` 到 `stacks/<target>.yaml`。
- 顶层 `name` 改为 `<target>`。
- ref 第一段等于 `<source>` 且指向自身资源时，自动改为 `<target>`；指向其他 stack 的 ref 保持不变。
- 当前 stack 内的明文凭据默认保持不变；用户需要新密码时可编辑生成后的 stack 文件。
- 默认不自动改端口；使用 `--allocate-ports` 时按端口池重新分配本 stack 内端口，用户仍需执行 `check/up`。

`remove` 默认不删除生成文件，只删除或归档 stack 配置。需要清理生成文件时使用 `--purge`。

## 6. validate/plan/apply

```bash
proxystack-agent validate
proxystack-agent validate usa1
proxystack-agent plan
proxystack-agent plan usa1
proxystack-agent apply
proxystack-agent apply usa1
```

- `validate`：校验 `config.yaml`、所有 stack 文件、端口、ref、rules、mode、安全约束和明文字段格式。
- `plan`：执行完整编译，对比 manifest，展示将生成/修改/删除的文件和建议重启的服务，不写文件。
- `apply`：生成配置并写 manifest，不启动、不停止、不重启服务。

`check` 是 `validate + plan` 的常用包装；`up` 是 `validate + apply + service start/restart changed` 的常用包装。

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

通用 `export/import` 备份恢复推迟到 M5。P0 不支持从旧 `clash`、`xrelay`、`clashsub` 或旧 `proxy-stack` 目录自动导入；这些目录只作为人工参考，不进入实现范围。

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

proxystack-agent version
proxystack-agent version mihomo
proxystack-agent version xray
```

设计要求：

- 支持指定版本：`--version v1.19.0`。
- 支持 sha256 校验：`--sha256 <value>`。
- 支持下载源配置：GitHub Release、镜像源、本地文件。
- `install/update mihomo|xray` 默认写入 `/opt/proxystack/bin`，代理核心二进制 owner 为 `proxystack:proxystack`，权限为 `0750`。
- `install/update geo` 默认写入 `/opt/proxystack/geo`，geo 数据文件 owner 为 `proxystack:proxystack`，权限为 `0640`。
- `update self` 只更新 proxystack Python 包，默认不更新 mihomo、xray-core 或 geo 数据。
- `update self` 只写 `/opt/proxystack/.venv`，应以 `proxystack` 用户或具备同等写权限的管理员身份运行；CLI 不自动提权。
- `install all` 只覆盖 mihomo、xray-core 和 geo 数据，不包含 systemd unit。
- `update all` 默认只更新代理核心和 geo 数据，不包含 `self`，避免无意中升级管理工具本身。
- 不在服务启动时自动下载，避免运行期副作用。
- 更新二进制时，先停止受影响服务，替换成功后再恢复。

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

`enable/disable/up/down/restart/status/logs` 是 `service` 分组的常用包装。

`service install|uninstall` 写 `/etc/systemd/system/`，必须以 root 或具备等价 systemd 管理权限的用户运行；其他服务生命周期命令权限不足时必须给出明确错误。

systemd unit 安装入口统一为 `service install [target]`，不在 `install` 分组中提供 unit 相关子命令，避免和代理核心下载安装命令混用。

systemd 单元：

```text
proxystack-xray@usa1.service
proxystack-clash@usa1.service
proxystack-sub.service
```

## 10. 订阅发布与远端服务

```bash
proxystack-agent publish
proxystack-agent publish --source local -o /opt/proxystack/publish/sub-bundle.zip
proxystack-agent publish --input-dir ./inputs --source merged -o sub-bundle.zip
proxystack-agent publish --input-dir ./inputs --include-stack --source merged -o sub-bundle.zip
proxystack-agent sub export-input --source usa1 -o usa1.yaml
proxystack-agent sub validate-inputs --input-dir ./inputs
proxystack-agent render sub --input-dir ./inputs
proxystack-sub import sub-bundle.zip
proxystack-sub import sub-bundle.zip --no-rebuild
proxystack-sub rebuild
proxystack-sub serve
proxystack-sub routes
proxystack-sub status
```

HTTP 路由：

```text
GET /health
GET /sub/:user
GET /premium_sub/:user
GET /surge_sub/:user
```

订阅相关命令区别：

- `publish`：常用入口，默认生成 `/opt/proxystack/publish/sub-bundle.zip`。
- `sub export-input`：从当前 stack 生成一个 subscription input 文件，适合放进远端或本地的 `inputs/` 目录。
- `publish --input-dir`：把 `--input-dir` 指定目录中的多个 input 打成 `sub-bundle.zip`，适合 inputs 高级模式；默认不包含当前 stack 生成的 input，需要合并当前 stack 时显式传入 `--include-stack`。
- `sub validate-inputs`：只校验 `inputs/` 目录，不生成发布包。
- `render sub`：只输出订阅索引，不写文件；加 `--input-dir` 时输出多 input 合并后的结果。

订阅服务启动时只读取合并后的 `current/index.json`，不直接解析 `config.yaml` 或 stack 文件。`proxystack-sub import` 默认校验发布包、解包 inputs 并自动 rebuild；只有传 `--no-rebuild` 时才需要手动执行 `rebuild`。这样 `up + publish + sub import` 是订阅内容变更的主流程。

## 11. mihomo 辅助命令

P1 实现：

```bash
proxystack-agent mihomo groups usa1
proxystack-agent mihomo set usa1 AllProxy server-a
proxystack-agent mihomo ipinfo usa1
```

这些命令依赖 mihomo REST API，失败时不能影响配置生成主流程。
