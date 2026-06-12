"""Task11 P0 主流程端到端测试。"""

from pathlib import Path
from typing import Any
from typing import Sequence

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from typer.testing import CliRunner

import proxystack.cli.agent as agent_module
import proxystack.cli.lifecycle as lifecycle_module
import proxystack.cli.sub as sub_module
from proxystack.cli.agent import app as agent_app
from proxystack.cli.sub import app as sub_app
from proxystack.systemd import CommandResult

runner = CliRunner()


class FakeSystemdRunner:
    """记录 systemd 命令，避免端到端测试调用真实 systemctl。"""

    def __init__(self) -> None:
        """初始化调用记录。"""
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: Sequence[str]) -> CommandResult:
        """记录调用并返回成功结果。"""
        self.calls.append(tuple(args))
        return CommandResult(args=tuple(args), returncode=0, stdout="")


def test_init_add_validate_start_sub_export_import_serve_main_flow(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 P0 主流程在 fake systemd/uvicorn 和临时目录中可完整跑通。"""
    config = tmp_path / "project" / "config.yaml"
    fake_systemd = FakeSystemdRunner()
    served: dict[str, Any] = {}
    monkeypatch.setattr(agent_module, "SYSTEMD_RUNNER", fake_systemd)
    monkeypatch.setattr(agent_module, "SYSTEMD_UNIT_DIR_OVERRIDE", tmp_path / "systemd")
    monkeypatch.setattr(lifecycle_module, "is_port_available", lambda _host, _port: True)

    def fake_uvicorn_run(app: object, host: str, port: int) -> None:
        """记录 serve 参数，避免启动真实 HTTP 服务。"""
        served["app"] = app
        served["host"] = host
        served["port"] = port

    monkeypatch.setattr(sub_module.uvicorn, "run", fake_uvicorn_run)

    init_result = runner.invoke(
        agent_app,
        ["init", "-c", str(config), "--base-dir", str(config.parent), "--external-host", "proxy.example.com"],
    )
    add_result = runner.invoke(agent_app, ["add", "edge", "--no-edit", "-c", str(config)])
    validate_result = runner.invoke(agent_app, ["validate", "-c", str(config), "--skip-system-ports"])
    check_result = runner.invoke(agent_app, ["check", "-c", str(config), "--skip-system-ports"])
    generated_dir = config.parent / "runtime" / "generated"
    assert init_result.exit_code == 0
    assert add_result.exit_code == 0
    assert validate_result.exit_code == 0
    assert check_result.exit_code == 0
    assert not any(generated_dir.rglob("*.json"))
    assert not any(generated_dir.rglob("*.yaml"))

    write_fake_proxy_binaries(config.parent)
    start_result = runner.invoke(agent_app, ["start", "xrelay/edge", "-c", str(config)])
    xray_config = generated_dir / "xray" / "edge.json"
    assert start_result.exit_code == 0
    assert xray_config.exists()
    assert not (config.parent / "sub" / "current" / "index.json").exists()
    assert fake_systemd.calls == [("systemctl", "restart", "proxystack-xray@edge.service")]

    export_result = runner.invoke(agent_app, ["sub", "export", "edge", "-c", str(config)])
    bundle = config.parent / "publish" / "edge-sub-bundle.zip"
    import_result = runner.invoke(sub_app, ["import", str(bundle), "--data-dir", str(config.parent / "sub")])
    serve_result = runner.invoke(sub_app, ["serve", "--host", "127.0.0.1", "--port", "3003", "--data-dir", str(config.parent / "sub")])

    assert export_result.exit_code == 0
    assert import_result.exit_code == 0
    assert serve_result.exit_code == 0
    assert served["host"] == "127.0.0.1"
    assert served["port"] == 3003

    client = TestClient(served["app"])
    health = client.get("/health")
    subscription = client.get("/sub/demo", params={"token": "demo-subscription-token"})

    assert health.status_code == 200
    assert subscription.status_code == 200
    assert "example vmess" in subscription.text


def write_fake_proxy_binaries(project_dir: Path) -> None:
    """写入端到端测试用代理核心占位文件，避免调用真实 xray/mihomo。"""
    bin_dir = project_dir / "bin"
    bin_dir.mkdir(exist_ok=True)
    for binary_name in ["mihomo", "xray"]:
        binary_path = bin_dir / binary_name
        binary_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary_path.chmod(0o750)
