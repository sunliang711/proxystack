"""Task11 Docker 部署安全配置测试。"""

from pathlib import Path

from ruamel.yaml import YAML


def test_docker_compose_sub_service_uses_security_hardening() -> None:
    """验证订阅服务 Compose 示例包含 P0 要求的安全配置。"""
    compose = YAML(typ="safe").load(Path("docker-compose.sub.yml").read_text(encoding="utf-8"))
    service = compose["services"]["proxystack-sub"]

    assert service["user"] == "10001:10001"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "/opt/proxystack/sub:/data" in service["volumes"]
    assert service["healthcheck"]["test"][0] == "CMD"
    assert service["command"] == [
        "proxystack-sub",
        "serve",
        "--config",
        "/data/config.yaml",
    ]


def test_dockerfile_sub_runtime_defaults_are_non_root_and_persistent() -> None:
    """验证 Dockerfile.sub 默认非 root 运行并声明 /data 持久化目录。"""
    dockerfile = Path("Dockerfile.sub").read_text(encoding="utf-8")

    assert "USER 10001:10001" in dockerfile
    assert 'VOLUME ["/data"]' in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'CMD ["proxystack-sub", "serve", "--config", "/data/config.yaml"]' in dockerfile


def test_agent_sub_directory_boundary_and_lock_paths_are_documented() -> None:
    """验证 agent/sub 写入边界和锁隔离路径在部署文档中保持分离。"""
    cli_doc = Path("docs/cli.md").read_text(encoding="utf-8")
    deployment_doc = Path("docs/deployment.md").read_text(encoding="utf-8")

    assert "agent 不直接写 `sub/inputs/`" in cli_doc
    assert "sub 只写 `sub/inputs/`，并读取 `sub/config.yaml`" in cli_doc
    assert "`/opt/proxystack/runtime/agent.lock`" in deployment_doc
    assert "`/opt/proxystack/sub/sub.lock`" in deployment_doc
