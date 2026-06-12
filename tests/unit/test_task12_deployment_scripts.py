"""Task12 部署脚本静态和 dry-run 测试。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


SCRIPT_PATHS = [
    Path("scripts/install-agent.sh"),
    Path("scripts/install-sub-local.sh"),
    Path("scripts/uninstall-local.sh"),
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
    """验证部署入口都提供 --help 输出。"""
    for script in SCRIPT_PATHS[:4]:
        result = run_script(["bash", str(script), "--help"])

        assert result.returncode == 0, script
        assert "--dry-run" in result.stdout
    for script in SCRIPT_PATHS[:2]:
        result = run_script(["bash", str(script), "--help"])

        assert result.returncode == 0, script
        assert "--source" in result.stdout
    result = run_script(["bash", "scripts/uninstall-local.sh", "--help"])

    assert result.returncode == 0
    assert "--target" in result.stdout


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
    assert "Next steps:" in output
    assert "ps-agent setup" in output
    assert "ps-agent start usa1" in output
    assert "print next steps" not in output
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
    assert "ps-sub" in output
    assert "systemctl" not in output


def test_uninstall_local_dry_run_keeps_data_by_default() -> None:
    """验证本地卸载 dry-run 只预览服务和 unit 清理，默认保留数据。"""
    result = run_script(
        [
            "bash",
            "scripts/uninstall-local.sh",
            "--target",
            "all",
            "--base-dir",
            "/tmp/proxystack-task12-uninstall/opt/proxystack",
            "--bin-dir",
            "/tmp/proxystack-task12-uninstall/usr/local/bin",
            "--dry-run",
        ]
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "systemctl stop" in output
    assert "proxystack-xray@\\*.service" in output
    assert "proxystack-sub.service" in output
    assert "systemctl daemon-reload" in output
    assert "Data purge skipped" in output
    assert "rm -rf /tmp/proxystack-task12-uninstall/opt/proxystack" not in output


def test_uninstall_local_rejects_partial_purge_data() -> None:
    """验证卸载脚本不允许对共享 base_dir 做局部数据清理。"""
    result = run_script(
        [
            "bash",
            "scripts/uninstall-local.sh",
            "--target",
            "sub",
            "--base-dir",
            "/tmp/proxystack-task12-uninstall-sub/opt/proxystack",
            "--purge-data",
            "--dry-run",
        ]
    )

    assert result.returncode != 0
    assert "--purge-data is only allowed with --target all" in result.stderr


def test_python_venv_dependency_auto_installs_when_supported(tmp_path: Path) -> None:
    """验证 Debian/Ubuntu 上缺少 Python venv 依赖时会自动安装。"""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ready_file = tmp_path / "venv-ready"
    apt_log = tmp_path / "apt.log"
    os_release = tmp_path / "os-release"
    probe = tmp_path / "probe.sh"
    os_release.write_text("ID=debian\n", encoding="utf-8")
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
    probe.write_text(
        """
source scripts/lib/common.sh
ensure_python_venv_available python3
""".lstrip(),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_APT_LOG"] = str(apt_log)
    env["FAKE_VENV_READY"] = str(ready_file)
    env["OS_RELEASE_PATH"] = str(os_release)

    result = subprocess.run(
        ["bash", str(probe)],
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
run_stream_as_user() {{
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


def test_step_fails_when_internal_run_fails_before_success(tmp_path: Path) -> None:
    """验证 step 内部首个 run 失败不会被后续成功命令吞掉。"""
    probe = tmp_path / "probe.sh"
    probe.write_text(
        """
source scripts/lib/common.sh
failing_then_success() {
	run bash -c 'printf "short failure\\n" >&2; exit 7'
	run true
}
step "probe failure" failing_then_success
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    assert result.returncode == 7
    assert "probe failure .. failed: command failed with exit code 7" in result.stderr
    assert "short failure" in result.stderr
    assert "Full output:" not in result.stderr
    assert "probe failure .. done" not in result.stderr


def test_step_failure_cleans_internal_state_files(tmp_path: Path) -> None:
    """验证 step 失败不会遗留内部状态临时文件。"""
    probe = tmp_path / "probe.sh"
    before = {path.name for path in Path("/tmp").glob("proxystack-step*")}
    probe.write_text(
        """
source scripts/lib/common.sh
step "probe cleanup" run bash -c 'printf "short failure\\n" >&2; exit 6'
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    after = {path.name for path in Path("/tmp").glob("proxystack-step*")}
    assert result.returncode == 6
    assert "probe cleanup .. failed:" in result.stderr
    assert after == before


def test_run_stream_prints_progress_output(tmp_path: Path) -> None:
    """验证下载类命令可通过 run_stream 实时输出进度。"""
    probe = tmp_path / "probe.sh"
    probe.write_text(
        """
source scripts/lib/common.sh
step "stream visible output" run_stream bash -c 'printf "stream progress\\n"'
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    assert result.returncode == 0, result.stderr
    assert "stream progress" in result.stderr
    assert "stream visible output .. done" in result.stderr


def test_ensure_pip_available_skips_existing_pip(tmp_path: Path) -> None:
    """验证 pip 模块已存在时不会执行 ensurepip。"""
    call_log = tmp_path / "pip-check.log"
    probe = tmp_path / "probe.sh"
    probe.write_text(
        f"""
source scripts/lib/common.sh
run_as_user() {{
	printf '%s\\n' "$*" >>"{call_log}"
	return 0
}}
ensure_pip_available proxystack /venv/bin/python
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    assert result.returncode == 0, result.stderr
    output = call_log.read_text(encoding="utf-8")
    assert "find_spec" in output
    assert "ensurepip" not in output
    assert result.stderr == ""


def test_ensure_pip_available_installs_missing_pip(tmp_path: Path) -> None:
    """验证 pip 模块缺失时才调用 ensurepip。"""
    call_log = tmp_path / "pip-check.log"
    probe = tmp_path / "probe.sh"
    probe.write_text(
        f"""
source scripts/lib/common.sh
run_as_user() {{
	printf '%s\\n' "$*" >>"{call_log}"
	case "$*" in
		*find_spec*) return 1 ;;
		*ensurepip*) return 0 ;;
	esac
	return 1
}}
ensure_pip_available proxystack /venv/bin/python
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    assert result.returncode == 0, result.stderr
    output = call_log.read_text(encoding="utf-8")
    assert "find_spec" in output
    assert "-m ensurepip --upgrade" in output


def test_source_tree_fingerprint_ignores_build_outputs(tmp_path: Path) -> None:
    """验证源码指纹忽略构建输出，但会感知源码内容变化。"""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "pyproject.toml").write_text("[project]\nname = \"demo\"\n", encoding="utf-8")
    (source_dir / "pkg.py").write_text("VALUE = 1\n", encoding="utf-8")
    probe = tmp_path / "probe.sh"
    probe.write_text(
        f"""
source scripts/lib/common.sh
first="$(source_tree_fingerprint "{source_dir}")"
mkdir -p "{source_dir}/build"
printf '%s\\n' ignored >"{source_dir}/build/output.txt"
second="$(source_tree_fingerprint "{source_dir}")"
printf '%s\\n' 'VALUE = 2' >"{source_dir}/pkg.py"
third="$(source_tree_fingerprint "{source_dir}")"
printf '%s\\n%s\\n%s\\n' "$first" "$second" "$third"
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    assert result.returncode == 0, result.stderr
    first, second, third = result.stdout.splitlines()
    assert first == second
    assert third != first


def test_python_package_current_requires_matching_stamp_and_commands(tmp_path: Path) -> None:
    """验证 Python 包幂等判断同时检查源码 stamp 和 console scripts。"""
    stamp = tmp_path / "source.sha256"
    bin_dir = tmp_path / "bin"
    agent_bin = bin_dir / "proxystack-agent"
    sub_bin = bin_dir / "proxystack-sub"
    bin_dir.mkdir()
    stamp.write_text("abc123\n", encoding="utf-8")
    agent_bin.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    sub_bin.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    agent_bin.chmod(0o755)
    sub_bin.chmod(0o755)
    probe = tmp_path / "probe.sh"
    probe.write_text(
        f"""
source scripts/lib/common.sh
python_package_current "{stamp}" abc123 "{agent_bin}" "{sub_bin}"
if python_package_current "{stamp}" changed "{agent_bin}" "{sub_bin}"; then
	exit 10
fi
rm -f "{sub_bin}"
if python_package_current "{stamp}" abc123 "{agent_bin}" "{sub_bin}"; then
	exit 11
fi
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    assert result.returncode == 0, result.stderr


def test_ensure_dir_skips_existing_directory(tmp_path: Path) -> None:
    """验证 ensure_dir 对已符合要求的目录输出 SKIP，不重复执行 install。"""
    existing_dir = tmp_path / "existing"
    existing_dir.mkdir()
    existing_dir.chmod(0o750)
    probe = tmp_path / "probe.sh"
    probe.write_text(
        f"""
source scripts/lib/common.sh
ensure_dir "{existing_dir}" 0750 "" none
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_ensure_symlink_skips_existing_link(tmp_path: Path) -> None:
    """验证 ensure_symlink 对已正确的链接输出 SKIP，不重复 ln。"""
    target = tmp_path / "target"
    link = tmp_path / "link"
    target.write_text("ok\n", encoding="utf-8")
    link.symlink_to(target)
    probe = tmp_path / "probe.sh"
    probe.write_text(
        f"""
source scripts/lib/common.sh
ensure_symlink "{target}" "{link}" none
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_stage_python_source_propagates_failure_when_captured(tmp_path: Path) -> None:
    """验证源码 stage 即使在命令替换中调用，也会传播 tar 失败。"""
    source_dir = tmp_path / "source"
    staging_dir = tmp_path / "stage"
    source_dir.mkdir()
    (source_dir / "pyproject.toml").write_text("[project]\nname = \"demo\"\n", encoding="utf-8")
    probe = tmp_path / "probe.sh"
    probe.write_text(
        f"""
source scripts/lib/common.sh
guard_managed_path() {{
	return 0
}}
ensure_dir() {{
	mkdir -p "$1"
}}
run() {{
	if [[ "$1" == "tar" && "$*" == *" -cf "* ]]; then
		return 9
	fi
	"$@"
}}
if staged="$(stage_python_source "{source_dir}" "{staging_dir}" proxystack:proxystack)"; then
	printf '%s\\n' "$staged"
	exit 10
fi
exit 0
""".lstrip(),
        encoding="utf-8",
    )

    result = run_script(["bash", str(probe)])

    assert result.returncode == 0, result.stderr


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
    assert "Sub config check skipped for dry-run" in output
    assert "proxystack-sub serve --config /data/config.yaml" in output
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


def test_deploy_sub_docker_requires_sub_config_before_run() -> None:
    """验证 Docker 部署脚本在启动容器前检查 ps-sub 配置。"""
    script = Path("scripts/deploy-sub-docker.sh").read_text(encoding="utf-8")

    assert '[[ ! -f "${DATA_DIR}/config.yaml" ]]' in script
    assert "Sub config does not exist" in script
    assert script.index("step \"check ps-sub config\"") < script.index("step \"start Docker container\"")


def test_managed_path_guard_rejects_dangerous_roots() -> None:
    """验证部署脚本即使 dry-run 也拒绝危险根路径。"""
    checks = [
        ["bash", "scripts/install-agent.sh", "--source", str(Path.cwd()), "--base-dir", "/", "--dry-run"],
        ["bash", "scripts/install-sub-local.sh", "--source", str(Path.cwd()), "--base-dir", "/", "--dry-run"],
        ["bash", "scripts/uninstall-local.sh", "--base-dir", "/", "--dry-run"],
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
