"""Task12 部署脚本静态和 dry-run 测试。"""

from __future__ import annotations

from pathlib import Path
import subprocess


SCRIPT_PATHS = [
    Path("scripts/install-agent.sh"),
    Path("scripts/install-sub-local.sh"),
    Path("scripts/deploy-sub-docker.sh"),
    Path("scripts/lib/common.sh"),
]


def run_script(args: list[str]) -> subprocess.CompletedProcess[str]:
    """运行部署脚本并捕获输出，测试只使用 help 或 dry-run。"""
    return subprocess.run(args, check=False, capture_output=True, text=True)


def test_task12_scripts_have_valid_bash_syntax() -> None:
    """验证 Task12 Shell 脚本通过 bash 语法检查。"""
    result = run_script(["bash", "-n", *[str(path) for path in SCRIPT_PATHS]])

    assert result.returncode == 0, result.stderr


def test_task12_entrypoints_have_help_output() -> None:
    """验证三个部署入口都提供 --help 输出。"""
    for script in SCRIPT_PATHS[:3]:
        result = run_script(["bash", str(script), "--help"])

        assert result.returncode == 0, script
        assert "--dry-run" in result.stdout


def test_install_agent_dry_run_stays_inside_bootstrap_boundary() -> None:
    """验证 agent dry-run 只预览 bootstrap 动作，不包含核心下载入口。"""
    result = run_script(
        [
            "bash",
            "scripts/install-agent.sh",
            "--source",
            str(Path.cwd()),
            "--base-dir",
            "/tmp/proxystack-task12-agent/opt/proxystack",
            "--bin-dir",
            "/tmp/proxystack-task12-agent/usr/local/bin",
            "--install-systemd",
            "--dry-run",
        ]
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "DRY-RUN:" in output
    assert "proxystack-agent init" in output
    assert "proxystack-agent service install" in output
    assert "proxystack-agent install all" not in output
    assert "mihomo" not in output
    assert "xray-core" not in output


def test_install_sub_local_dry_run_uses_sub_service_only() -> None:
    """验证本地订阅服务 dry-run 只安装和启动 sub 目标。"""
    result = run_script(
        [
            "bash",
            "scripts/install-sub-local.sh",
            "--source",
            str(Path.cwd()),
            "--base-dir",
            "/tmp/proxystack-task12-sub-local/opt/proxystack",
            "--install-systemd",
            "--start",
            "--dry-run",
        ]
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "proxystack-agent service install sub" in output
    assert "proxystack-agent service start sub" in output
    assert "systemctl" not in output


def test_deploy_sub_docker_dry_run_uses_security_defaults() -> None:
    """验证 Docker dry-run 输出安全默认参数且默认不删除容器。"""
    result = run_script(
        [
            "bash",
            "scripts/deploy-sub-docker.sh",
            "--image",
            "proxystack-sub:latest",
            "--data-dir",
            "/tmp/proxystack-task12-docker/sub",
            "--dry-run",
        ]
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "docker run -d" in output
    assert "--read-only" in output
    assert "--cap-drop ALL" in output
    assert "--user 10001:10001" in output
    assert "--tmpfs" in output
    assert "/tmp:rw" in output
    assert "noexec" in output
    assert "nosuid" in output
    assert "docker rm -f" not in output


def test_deploy_sub_docker_replace_is_explicit() -> None:
    """验证 Docker --replace 才会预览删除同名容器。"""
    result = run_script(
        [
            "bash",
            "scripts/deploy-sub-docker.sh",
            "--image",
            "proxystack-sub:latest",
            "--data-dir",
            "/tmp/proxystack-task12-docker-replace/sub",
            "--replace",
            "--dry-run",
        ]
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "docker rm -f proxystack-sub" in output
    assert "docker run -d" in output


def test_deploy_sub_docker_pull_happens_before_replace() -> None:
    """验证 Docker --pull 在 --replace 删除旧容器前预览执行。"""
    result = run_script(
        [
            "bash",
            "scripts/deploy-sub-docker.sh",
            "--image",
            "proxystack-sub:latest",
            "--data-dir",
            "/tmp/proxystack-task12-docker-pull/sub",
            "--pull",
            "--replace",
            "--dry-run",
        ]
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert output.index("docker pull proxystack-sub:latest") < output.index("docker rm -f proxystack-sub")


def test_managed_path_guard_rejects_dangerous_roots() -> None:
    """验证部署脚本即使 dry-run 也拒绝危险根路径。"""
    checks = [
        ["bash", "scripts/install-agent.sh", "--source", str(Path.cwd()), "--base-dir", "/", "--dry-run"],
        ["bash", "scripts/install-sub-local.sh", "--source", str(Path.cwd()), "--base-dir", "/", "--dry-run"],
        ["bash", "scripts/deploy-sub-docker.sh", "--image", "proxystack-sub:latest", "--data-dir", "/", "--dry-run"],
    ]

    for args in checks:
        result = run_script(args)

        assert result.returncode != 0, args
        assert "not allowed" in result.stderr


def test_bin_dir_guard_rejects_sensitive_system_subdirectories() -> None:
    """验证 console script 链接目录拒绝敏感系统子目录。"""
    result = run_script(
        [
            "bash",
            "scripts/install-agent.sh",
            "--source",
            str(Path.cwd()),
            "--base-dir",
            "/tmp/proxystack-task12-agent-bin/opt/proxystack",
            "--bin-dir",
            "/etc/cron.d",
            "--dry-run",
        ]
    )

    assert result.returncode != 0
    assert "bin directory" in result.stderr


def test_install_agent_does_not_expose_core_install_option() -> None:
    """验证 install-agent 不提供代理核心安装选项或下载命令。"""
    scripts_text = "\n".join(path.read_text(encoding="utf-8") for path in SCRIPT_PATHS)

    assert "--install-core" not in scripts_text
    assert "install-core" not in scripts_text
    assert "curl" not in scripts_text
    assert "wget" not in scripts_text
    assert "proxystack-agent install all" not in scripts_text
    assert "proxystack-agent update all" not in scripts_text
