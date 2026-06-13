"""systemd 服务层测试。"""

from pathlib import Path
from typing import Sequence

import pytest
from pytest import MonkeyPatch

from proxystack.config import load_config
import proxystack.systemd.service as service_module
from proxystack.systemd import CLASH_TEMPLATE_UNIT
from proxystack.systemd import SUB_UNIT
from proxystack.systemd import XRAY_TEMPLATE_UNIT
from proxystack.systemd import CommandResult
from proxystack.systemd import SystemdCommandError
from proxystack.systemd import SystemdManager


class FakeRunner:
    """记录外部命令调用，避免测试调用真实 systemctl/journalctl。"""

    def __init__(self, returncode: int = 0, stdout: str = "ok\n", stderr: str = "") -> None:
        """初始化 fake 命令返回值。"""
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: Sequence[str]) -> CommandResult:
        """记录参数数组并返回预设结果。"""
        self.calls.append(tuple(args))
        return CommandResult(args=tuple(args), returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def test_unit_content_contains_hardening_and_generated_exec_start(tmp_path: Path) -> None:
    """验证 unit 内容包含 hardening、ReadWritePaths 和生成配置路径。"""
    config = write_systemd_config(tmp_path)
    manager = SystemdManager(load_config(config), runner=FakeRunner())
    units = {unit.name: unit.content for unit in manager.build_units()}

    xray_unit = units[XRAY_TEMPLATE_UNIT]
    clash_unit = units[CLASH_TEMPLATE_UNIT]
    sub_unit = units[SUB_UNIT]

    for content in [xray_unit, clash_unit, sub_unit]:
        assert "User=proxystack" in content
        assert "Group=proxystack" in content
        assert "NoNewPrivileges=true" in content
        assert "ProtectSystem=strict" in content
        assert "ProtectHome=true" in content
        assert "PrivateTmp=true" in content

    assert f"ReadWritePaths={tmp_path / 'project' / 'runtime'} {tmp_path / 'project' / 'runtime' / 'generated'}" in xray_unit
    assert f"ExecStart={tmp_path / 'project' / 'bin' / 'xray'} run -config {tmp_path / 'project' / 'runtime' / 'generated' / 'xray' / '%i.json'}" in xray_unit
    assert "config.yaml" not in xray_unit
    assert "stacks" not in xray_unit

    assert f"ReadWritePaths={tmp_path / 'project' / 'runtime'} {tmp_path / 'project' / 'runtime' / 'generated'}" in clash_unit
    assert f"ExecStart={tmp_path / 'project' / 'bin' / 'mihomo'} -d {tmp_path / 'project' / 'runtime' / 'mihomo' / '%i'} -f {tmp_path / 'project' / 'runtime' / 'generated' / 'mihomo' / '%i.yaml'}" in clash_unit
    assert "config.yaml" not in clash_unit
    assert "stacks" not in clash_unit

    assert f"ReadWritePaths={tmp_path / 'project' / 'sub'}" in sub_unit
    assert f"ExecStart={tmp_path / 'project' / '.venv' / 'bin' / 'proxystack-sub'} serve --config {tmp_path / 'project' / 'sub' / 'config.yaml'}" in sub_unit
    assert "stacks" not in sub_unit


def test_install_uninstall_units_use_fake_unit_dir_and_keep_configs(tmp_path: Path) -> None:
    """验证 unit 安装卸载只写删 fake unit_dir，不删除配置和 stacks。"""
    config = write_systemd_config(tmp_path)
    stack_path = config.parent / "stacks" / "usa1.yaml"
    stack_path.parent.mkdir()
    stack_path.write_text("name: usa1\n", encoding="utf-8")
    runner = FakeRunner()
    unit_dir = tmp_path / "systemd"
    manager = SystemdManager(load_config(config), runner=runner, unit_dir=unit_dir)

    install_lines = manager.install_units((XRAY_TEMPLATE_UNIT, SUB_UNIT))
    uninstall_lines = manager.uninstall_units((XRAY_TEMPLATE_UNIT, SUB_UNIT))

    assert "install:" in install_lines[0]
    assert "uninstall:" in uninstall_lines[0]
    assert runner.calls == [("systemctl", "daemon-reload"), ("systemctl", "daemon-reload")]
    assert not (unit_dir / XRAY_TEMPLATE_UNIT).exists()
    assert not (unit_dir / SUB_UNIT).exists()
    assert config.exists()
    assert stack_path.exists()


def test_status_and_log_use_fake_runner(tmp_path: Path) -> None:
    """验证 status/log 通过 fake runner 代理 systemctl 和 journalctl。"""
    config = write_systemd_config(tmp_path)
    runner = FakeRunner(stdout="active\n")
    manager = SystemdManager(load_config(config), runner=runner)

    status_lines = manager.systemctl("status", ("proxystack-xray@usa1.service",))
    log_lines = manager.journalctl(("proxystack-sub.service",), follow=True)

    assert status_lines == ["status: proxystack-xray@usa1.service", "  active"]
    assert log_lines == ["log: proxystack-sub.service", "  active"]
    assert runner.calls == [
        ("systemctl", "status", "proxystack-xray@usa1.service"),
        ("journalctl", "-u", "proxystack-sub.service", "--no-pager", "-n", "100", "-f"),
    ]


def test_status_allows_inactive_systemd_exit_code(tmp_path: Path) -> None:
    """验证 inactive 服务的 systemctl status 输出仍能返回给调用方。"""
    config = write_systemd_config(tmp_path)
    runner = FakeRunner(returncode=3, stdout="inactive\n")
    manager = SystemdManager(load_config(config), runner=runner)

    status_lines = manager.systemctl("status", ("proxystack-xray@usa1.service",))

    assert status_lines == ["status: proxystack-xray@usa1.service", "  inactive"]
    assert runner.calls == [("systemctl", "status", "proxystack-xray@usa1.service")]


def test_follow_log_uses_one_journalctl_for_multiple_units(tmp_path: Path) -> None:
    """验证 follow 多服务时一次 journalctl 订阅多个 unit。"""
    config = write_systemd_config(tmp_path)
    runner = FakeRunner(stdout="active\n")
    manager = SystemdManager(load_config(config), runner=runner)

    log_lines = manager.journalctl(
        (
            "proxystack-xray@usa1.service",
            "proxystack-clash@usa1.service",
        ),
        follow=True,
    )

    assert log_lines == [
        "log: proxystack-xray@usa1.service",
        "log: proxystack-clash@usa1.service",
        "  active",
    ]
    assert runner.calls == [
        (
            "journalctl",
            "-u",
            "proxystack-xray@usa1.service",
            "-u",
            "proxystack-clash@usa1.service",
            "--no-pager",
            "-n",
            "100",
            "-f",
        )
    ]


def test_nonzero_command_raises_clear_summary(tmp_path: Path) -> None:
    """验证 systemctl 非零返回会抛出包含 stdout/stderr 摘要的错误。"""
    config = write_systemd_config(tmp_path)
    runner = FakeRunner(returncode=1, stdout="stdout detail\n", stderr="permission denied\n")
    manager = SystemdManager(load_config(config), runner=runner)

    with pytest.raises(SystemdCommandError, match="permission denied"):
        manager.systemctl("restart", ("proxystack-xray@usa1.service",))


def test_follow_run_command_streams_without_pipe(monkeypatch: MonkeyPatch) -> None:
    """验证 journalctl follow 直接流式输出，不把日志捕获到 PIPE。"""
    captured: dict[str, object] = {}

    def fake_run(args: list[str], check: bool, text: bool, stdout: object = None, stderr: object = None) -> object:
        """记录 subprocess.run 参数，避免执行真实 journalctl。"""
        captured["args"] = args
        captured["check"] = check
        captured["text"] = text
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(service_module.subprocess, "run", fake_run)

    result = service_module.run_command(["journalctl", "-u", "proxystack-sub.service", "-f"])

    assert result.returncode == 0
    assert captured == {
        "args": ["journalctl", "-u", "proxystack-sub.service", "-f"],
        "check": False,
        "text": True,
        "stdout": None,
        "stderr": None,
    }


def write_systemd_config(tmp_path: Path) -> Path:
    """写入 systemd 测试使用的最小全局配置。"""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    config = project_dir / "config.yaml"
    config.write_text(
        f"""
version: 1
base_dir: {project_dir}
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
port_ranges:
  xrelay_inbound: 24000-24999
  clash_socks: 17000-17999
  clash_controller: 19000-19999
""".lstrip(),
        encoding="utf-8",
    )
    return config
