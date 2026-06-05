# 开发进度

## 当前状态

- [x] 汇总需求和架构方向
- [x] 确认 `sub` 为唯一订阅暴露开关
- [x] 确认 auto 场景支持 `url-test` 和 `load-balance`
- [x] 确认 mihomo/xray 下载安装纳入功能清单
- [x] 确认 systemd 服务管理子命令纳入功能清单
- [x] 确认本地文件统一放在 `/opt/proxystack`
- [x] 确认全局配置使用 `config.yaml`，每个 stack 使用独立 `stacks/<name>.yaml`
- [x] 初始化 Python 项目
- [x] 实现配置模型和校验
- [x] 实现引用解析和依赖图
- [x] 实现 Xray 配置生成器和 `render xrelay`
- [x] 扩展 Xray API、Stats、Policy 生成
- [ ] 实现配置生成器
- [ ] 实现 CLI 和 systemd 管理
- [ ] 实现订阅发布包、多输入合并和订阅服务本地/Docker部署
- [ ] 建立测试矩阵和端到端验证

## 里程碑

| 阶段 | 范围 | 状态 |
| --- | --- | --- |
| M0 | 项目文档、配置规范、任务拆分 | 已完成 |
| M1 | Python 项目骨架、stack schema、validate/render 基础能力 | 进行中 |
| M2 | Xray/mihomo/sub 生成器、golden tests | 进行中 |
| M3 | apply、manifest、systemd 管理 | 未开始 |
| M4 | install/update、部署脚本、订阅发布包、多输入合并、订阅服务本地/Docker 部署和测试矩阵 | 未开始 |
| M5 | mihomo API、原生备份导入导出和发布增强 | 未开始 |

## 交付记录

- [Task 04 交付记录：Xray 配置生成器](delivery/2026-06-05-16-40-32-feature-python-xray-generator.md)
- [Task 04 扩展交付记录：Xray API、Stats、Policy](delivery/2026-06-05-17-01-47-feature-python-xray-api-stats-policy.md)

## 任务列表

- [task-01-project-bootstrap.md](tasks/task-01-project-bootstrap.md)
- [task-02-config-schema-validation.md](tasks/task-02-config-schema-validation.md)
- [task-03-reference-graph.md](tasks/task-03-reference-graph.md)
- [task-04-xray-generator.md](tasks/task-04-xray-generator.md)
- [task-05-mihomo-generator.md](tasks/task-05-mihomo-generator.md)
- [task-06-subscription-generator-server.md](tasks/task-06-subscription-generator-server.md)
- [task-07-cli-lifecycle.md](tasks/task-07-cli-lifecycle.md)
- [task-08-install-update.md](tasks/task-08-install-update.md)
- [task-09-systemd-manager.md](tasks/task-09-systemd-manager.md)
- [task-10-import-export-release.md](tasks/task-10-import-export-release.md)
- [task-11-test-matrix.md](tasks/task-11-test-matrix.md)
- [task-12-deployment-scripts.md](tasks/task-12-deployment-scripts.md)
