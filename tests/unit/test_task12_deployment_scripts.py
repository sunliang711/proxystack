"""Task12 部署脚本静态和 dry-run 测试。"""

from __future__ import annotations

import os
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


def write_fake_command(path: Path, body: str) -> None:
    """写入测试用假命令，避免非 dry-run 测试触碰真实系统。"""
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


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
    for script in SCRIPT_PATHS[:2]:
        result = run_script(["bash", str(script), "--help"])

        assert result.returncode == 0, script
        assert "--source" in result.stdout


def test_install_scripts_default_to_repository_source() -> None:
    """验证安装脚本不传安装来源时默认使用当前仓库源码。"""
    agent_result = run_script(
        [
            "bash",
            "scripts/install-agent.sh",
            "--base-dir",
            "/tmp/proxystack-task12-default-agent/opt/proxystack",
            "--bin-dir",
            "/tmp/proxystack-task12-default-agent/usr/local/bin",
            "--dry-run",
        ]
    )
    sub_result = run_script(
        [
            "bash",
            "scripts/install-sub-local.sh",
            "--base-dir",
            "/tmp/proxystack-task12-default-sub/opt/proxystack",
            "--dry-run",
        ]
    )

    assert agent_result.returncode == 0, agent_result.stderr
    assert str(Path.cwd()) in agent_result.stderr
    assert sub_result.returncode == 0, sub_result.stderr
    assert str(Path.cwd()) in sub_result.stderr


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


def test_install_agent_auto_installs_python_venv_dependency_when_supported(tmp_path: Path) -> None:
    """验证 Debian/Ubuntu 上缺少 Python venv 依赖时会自动安装。"""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ready_file = tmp_path / "venv-ready"
    apt_log = tmp_path / "apt.log"
    os_release = tmp_path / "os-release"
    os_release.write_text("ID=debian\n", encoding="utf-8")
    write_fake_command(fake_bin / "getent", "exit 2\n")
    write_fake_command(
        fake_bin / "id",
        "if [[ \"$1\" == \"-u\" && \"$#\" -eq 1 ]]; then echo 0; exit 0; fi\n"
        "if [[ \"$1\" == \"-u\" && \"$2\" == \"proxystack\" ]]; then exit 1; fi\n"
        "if [[ \"$1\" == \"-un\" ]]; then echo root; exit 0; fi\n"
        "exit 1\n",
    )
    write_fake_command(
        fake_bin / "python3",
        "if [[ \"$1\" == \"-c\" ]]; then echo python3.11-venv; exit 0; fi\n"
        "if [[ \"$1\" == \"-m\" && \"$2\" == \"venv\" ]]; then\n"
        "  if [[ -f \"${FAKE_VENV_READY}\" ]]; then mkdir -p \"$3\"; touch \"$3/pyvenv.cfg\"; exit 0; fi\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
    )
    write_fake_command(
        fake_bin / "apt-get",
        "printf '%s\\n' \"$*\" >>\"${FAKE_APT_LOG}\"\n"
        "if [[ \"$1\" == \"install\" ]]; then touch \"${FAKE_VENV_READY}\"; fi\n"
        "exit 0\n",
    )
    for command in ["install", "chown", "groupadd", "useradd", "runuser", "ln"]:
        write_fake_command(fake_bin / command, "exit 0\n")
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_APT_LOG"] = str(apt_log)
    env["FAKE_VENV_READY"] = str(ready_file)
    env["OS_RELEASE_PATH"] = str(os_release)

    result = subprocess.run(
        [
            "bash",
            "scripts/install-agent.sh",
            "--source",
            str(Path.cwd()),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    apt_output = apt_log.read_text(encoding="utf-8")
    assert "update" in apt_output
    assert "install -y python3.11-venv" in apt_output


def test_pip_install_with_fallback_tries_next_index(tmp_path: Path) -> None:
    """验证 pip 安装源失败时会自动尝试下一个 index。"""
    call_log = tmp_path / "pip.log"
    probe = tmp_path / "probe.sh"
    probe.write_text(
        f"""
source scripts/lib/common.sh
run_as_user() {{
	printf '%s\\n' "$*" >>"{call_log}"
	case "$*" in
		*pypi.org*) return 1 ;;
		*) return 0 ;;
	esac
}}
PIP_INDEX_URLS="https://pypi.org/simple https://pypi.tuna.tsinghua.edu.cn/simple"
pip_install_with_fallback proxystack /venv/bin/python proxystack
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    assert result.returncode == 0, result.stderr
    output = call_log.read_text(encoding="utf-8")
    assert "https://pypi.org/simple" in output
    assert "https://pypi.tuna.tsinghua.edu.cn/simple" in output


def test_run_as_user_propagates_runuser_failure(tmp_path: Path) -> None:
    """验证 run_as_user 不吞掉 runuser 的失败返回码。"""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    write_fake_command(fake_bin / "runuser", "exit 7\n")
    probe = tmp_path / "probe.sh"
    probe.write_text(
        f"""
source scripts/lib/common.sh
PATH="{fake_bin}:$PATH"
if run_as_user proxystack /bin/false; then
	exit 99
fi
exit 0
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    assert result.returncode == 0, result.stderr


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
    assert output.index("Container conflict check skipped for dry-run") < output.index("install -d -m 0750")


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


def test_deploy_sub_docker_conflict_fails_before_creating_data_dirs(tmp_path: Path) -> None:
    """验证同名容器冲突会先于目录创建失败。"""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    install_log = tmp_path / "install.log"
    docker_script = fake_bin / "docker"
    install_script = fake_bin / "install"
    docker_script.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >>\"${FAKE_DOCKER_LOG}\"\n"
        "if [[ \"$1 $2\" == \"container inspect\" ]]; then exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    install_script.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >>\"${FAKE_INSTALL_LOG}\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    docker_script.chmod(0o755)
    install_script.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_DOCKER_LOG"] = str(docker_log)
    env["FAKE_INSTALL_LOG"] = str(install_log)

    result = subprocess.run(
        [
            "bash",
            "scripts/deploy-sub-docker.sh",
            "--image",
            "proxystack-sub:latest",
            "--data-dir",
            "/opt/proxystack/sub",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "Container already exists" in result.stderr
    assert docker_log.read_text(encoding="utf-8").strip() == "container inspect proxystack-sub"
    assert not install_log.exists()


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


def test_managed_path_guard_rejects_non_dedicated_paths() -> None:
    """验证托管目录拒绝非 proxystack 专用路径。"""
    for managed_path in ["/root", "/opt", "/Users/example"]:
        result = run_script(
            [
                "bash",
                "scripts/deploy-sub-docker.sh",
                "--image",
                "proxystack-sub:latest",
                "--data-dir",
                managed_path,
                "--dry-run",
            ]
        )

        assert result.returncode != 0, managed_path
        assert "not allowed" in result.stderr


def test_managed_path_guard_allows_dedicated_paths() -> None:
    """验证生产专用目录和 dry-run 临时专用前缀允许通过。"""
    checks = [
        [
            "bash",
            "scripts/install-agent.sh",
            "--source",
            str(Path.cwd()),
            "--base-dir",
            "/opt/proxystack",
            "--dry-run",
        ],
        [
            "bash",
            "scripts/deploy-sub-docker.sh",
            "--image",
            "proxystack-sub:latest",
            "--data-dir",
            "/tmp/proxystack-task12-allowed/sub",
            "--dry-run",
        ],
    ]

    for args in checks:
        result = run_script(args)

        assert result.returncode == 0, result.stderr


def test_install_scripts_reject_root_user_and_group() -> None:
    """验证安装脚本拒绝 root 用户和 root 组。"""
    for script in ["scripts/install-agent.sh", "scripts/install-sub-local.sh"]:
        user_result = run_script(
            [
                "bash",
                script,
                "--source",
                str(Path.cwd()),
                "--user",
                "root",
                "--dry-run",
            ]
        )
        group_result = run_script(
            [
                "bash",
                script,
                "--source",
                str(Path.cwd()),
                "--group",
                "root",
                "--dry-run",
            ]
        )

        assert user_result.returncode != 0, script
        assert "Install user must not be root" in user_result.stderr
        assert group_result.returncode != 0, script
        assert "Install group must not be root" in group_result.stderr


def test_install_scripts_reject_unsafe_user_and_group_names_in_dry_run() -> None:
    """验证安装脚本 dry-run 也拒绝可能注入选项的用户和组名。"""
    cases = [
        (["--user", "-o"], "Install user must not start with '-'"),
        (["--group", "-g"], "Install group must not start with '-'"),
        (["--user=bad:name"], "Install user must not contain ':'"),
        (["--group=bad:name"], "Install group must not contain ':'"),
    ]

    for script in ["scripts/install-agent.sh", "scripts/install-sub-local.sh"]:
        for extra_args, expected_error in cases:
            result = run_script(
                [
                    "bash",
                    script,
                    "--source",
                    str(Path.cwd()),
                    *extra_args,
                    "--dry-run",
                ]
            )

            assert result.returncode != 0, [script, extra_args]
            assert expected_error in result.stderr


def test_install_identity_rejects_non_root_name_with_uid_zero(tmp_path: Path) -> None:
    """验证非 root 名称但 UID 为 0 的已有用户被拒绝。"""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    write_fake_command(
        fake_bin / "getent",
        "if [[ \"$1 $2\" == \"group proxystack\" ]]; then echo 'proxystack:x:10001:'; exit 0; fi\n"
        "if [[ \"$1 $2\" == \"passwd fakeadmin\" ]]; then echo 'fakeadmin:x:0:10001::/opt/proxystack:/usr/sbin/nologin'; exit 0; fi\n"
        "exit 2\n",
    )
    write_fake_command(
        fake_bin / "id",
        "if [[ \"$1\" == \"-u\" && \"$#\" -eq 1 ]]; then echo 0; exit 0; fi\n"
        "if [[ \"$1\" == \"-un\" ]]; then echo root; exit 0; fi\n"
        "exit 1\n",
    )
    for command in ["install", "chown", "groupadd", "useradd", "runuser", "ln", "python3"]:
        write_fake_command(fake_bin / command, "exit 0\n")
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        [
            "bash",
            "scripts/install-agent.sh",
            "--source",
            str(Path.cwd()),
            "--user",
            "fakeadmin",
            "--group",
            "proxystack",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "Install user UID must not be 0" in result.stderr


def test_install_identity_rejects_non_root_name_with_gid_zero(tmp_path: Path) -> None:
    """验证非 root 名称但 GID 为 0 的已有组被拒绝。"""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    write_fake_command(
        fake_bin / "getent",
        "if [[ \"$1 $2\" == \"group fakeroot\" ]]; then echo 'fakeroot:x:0:'; exit 0; fi\n"
        "exit 2\n",
    )
    write_fake_command(
        fake_bin / "id",
        "if [[ \"$1\" == \"-u\" && \"$#\" -eq 1 ]]; then echo 0; exit 0; fi\n"
        "if [[ \"$1\" == \"-un\" ]]; then echo root; exit 0; fi\n"
        "exit 1\n",
    )
    for command in ["install", "chown", "groupadd", "useradd", "runuser", "ln", "python3"]:
        write_fake_command(fake_bin / command, "exit 0\n")
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        [
            "bash",
            "scripts/install-agent.sh",
            "--source",
            str(Path.cwd()),
            "--user",
            "proxystack",
            "--group",
            "fakeroot",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "Install group GID must not be 0" in result.stderr


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
