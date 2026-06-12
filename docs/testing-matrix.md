# P0 测试矩阵

本文档记录 P0 自动化测试和手工验收边界。自动化测试必须能在无 root、无 systemd、无真实代理核心二进制、无真实网络下载的环境中运行。

## 自动化覆盖

| 范围 | 覆盖文件 | 关键断言 |
| --- | --- | --- |
| 配置加载和非法配置 | `tests/test_config_loader.py`、`tests/unit/test_task11_config_matrix.py` | 示例配置、端口冲突、ref 缺失、循环依赖、危险 noauth、必填字段缺失 |
| CLI 生命周期 | `tests/test_cli.py`、`tests/unit/test_task11_cli_matrix.py` | help、validate/check/start 边界、add/clone 端口分配、fake systemd |
| 下载安装 | `tests/test_install.py` | fake downloader、本地文件、hash、私网 URL、归档路径穿越、self update fake runner |
| Xray golden | `tests/test_xray_generator.py`、`tests/golden/xray/` | JSON 输出 exact compare |
| mihomo golden | `tests/test_mihomo_generator.py`、`tests/golden/mihomo/` | YAML 输出 exact compare |
| subscription golden | `tests/unit/test_task11_subscription_golden.py`、`tests/golden/test_subscription_golden.py`、`tests/golden/sub/` | input、index、Clash、Premium Clash、Surge 输出 exact compare |
| 订阅发布包 | `tests/test_sub_generator.py`、`tests/test_cli.py` | input 合并、bundle hash/schema、import 默认增量写入、`--replace-all` |
| HTTP 订阅服务 | `tests/test_subserver.py` | 内存索引、watcher reload、token、错误 token、无用户、三类订阅格式 |
| systemd | `tests/test_systemd.py`、`tests/test_cli.py` | fake runner、fake unit_dir、unit hardening、journalctl follow |
| Docker Compose | `tests/unit/test_task11_docker_deployment.py`、`tests/test_cli.py` | 非 root、只读 rootfs、`cap_drop: ALL`、`/data` volume、healthcheck |
| P0 e2e | `tests/e2e/test_task11_main_flow.py` | `init -> add -> validate -> check -> start -> sub export -> sub import -> serve` |

## Golden 更新约定

- golden 测试只做 exact compare，不提供自动更新模式。
- 需要更新快照时，必须手工确认业务语义变化，再更新对应 `tests/golden/**` 文件。
- 普通格式化命令不得改写 golden 快照。

## 隔离策略

- systemd、journalctl 和服务生命周期通过 fake runner 隔离。
- 下载器、pip self update 和外部命令通过 fake runner 或本地临时文件隔离。
- `proxystack-sub serve` 测试 monkeypatch `uvicorn.run`，不启动真实监听。
- Docker P0 只做配置结构验证；镜像 build/run 放入手工验收。

## 手工验收

Docker 和 systemd 在部分 CI 环境不可用，P0 手工验收命令如下：

```bash
make test PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
docker compose -f docker-compose.sub.yml config
docker build -f Dockerfile.sub -t proxystack-sub:latest .
```

如果执行 Docker run，需要提前确保宿主机 `/opt/proxystack/sub` 的 owner 与容器用户 `10001:10001` 匹配。
