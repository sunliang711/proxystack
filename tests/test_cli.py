"""CLI 骨架测试。"""

import json
import os
from pathlib import Path
import shutil
import socket
import sys
from zipfile import ZipFile

from ruamel.yaml import YAML
from typer.testing import CliRunner

from proxystack.cli.agent import app as agent_app
from proxystack.cli.sub import app as sub_app

runner = CliRunner()


def test_agent_help_is_available() -> None:
    """验证 proxystack-agent 帮助可以正常输出。"""
    result = runner.invoke(agent_app, ["--help"])

    assert result.exit_code == 0
    assert "proxystack-agent" in result.output


def test_agent_lifecycle_command_help_is_available() -> None:
    """验证生命周期命令都提供 help 输出。"""
    commands = [
        ["init"],
        ["add"],
        ["edit"],
        ["list"],
        ["remove"],
        ["clone"],
        ["check"],
        ["up"],
        ["down"],
        ["restart"],
        ["status"],
        ["logs"],
        ["enable"],
        ["disable"],
        ["publish"],
        ["doctor"],
        ["validate"],
        ["plan"],
        ["apply"],
        ["render"],
        ["render", "model"],
        ["render", "xrelay"],
        ["render", "clash"],
        ["render", "sub"],
    ]

    for command in commands:
        result = runner.invoke(agent_app, [*command, "--help"])

        assert result.exit_code == 0, command


def test_agent_version_is_available() -> None:
    """验证 proxystack-agent 版本命令可以正常输出。"""
    result = runner.invoke(agent_app, ["version"])

    assert result.exit_code == 0
    assert "proxystack-agent" in result.output


def test_agent_validate_examples() -> None:
    """验证 proxystack-agent validate 可以校验示例配置。"""
    result = runner.invoke(agent_app, ["validate", "-c", "examples/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    assert "配置校验通过" in result.output


def test_agent_plan_examples() -> None:
    """验证 proxystack-agent plan 可以展示依赖和顺序。"""
    result = runner.invoke(agent_app, ["plan", "-c", "examples/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    assert "文件变更" in result.output
    assert "依赖服务" in result.output
    assert "建议操作顺序" in result.output
    assert "auto.clash" in result.output
    assert "proxystack-xray@usa1.service" in result.output


def test_agent_render_xrelay_example() -> None:
    """验证 proxystack-agent render xrelay 可以输出 Xray JSON。"""
    result = runner.invoke(agent_app, ["render", "xrelay", "usa1", "-c", "examples/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    rendered_config = json.loads(result.output)
    assert rendered_config["outbounds"][0]["settings"]["servers"][0]["port"] == 17091


def test_agent_render_clash_example() -> None:
    """验证 proxystack-agent render clash 可以输出 mihomo YAML。"""
    result = runner.invoke(agent_app, ["render", "clash", "auto", "-c", "examples/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    rendered_config = YAML(typ="safe").load(result.output)
    assert [proxy["name"] for proxy in rendered_config["proxies"]] == ["usa1-local", "usa2-local"]
    assert rendered_config["proxy-groups"][0]["type"] == "url-test"


def test_agent_render_sub_example() -> None:
    """验证 proxystack-agent render sub 可以输出订阅索引。"""
    result = runner.invoke(agent_app, ["render", "sub", "-c", "examples/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    rendered_index = json.loads(result.output)
    assert "alice" in rendered_index["users"]
    assert "upstreams" not in result.output
    assert rendered_index["access"]["type"] == "token"


def test_agent_render_model_example() -> None:
    """验证 proxystack-agent render model 可以输出解析后的模型 JSON。"""
    result = runner.invoke(agent_app, ["render", "model", "usa1", "-c", "examples/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    rendered_model = json.loads(result.output)
    assert [stack["name"] for stack in rendered_model["stacks"]] == ["usa1"]


def test_agent_init_creates_config_and_directories(tmp_path: Path) -> None:
    """验证 init 创建默认配置和生命周期目录。"""
    project_dir = tmp_path / "project"
    config = project_dir / "config.yaml"

    result = runner.invoke(
        agent_app,
        ["init", "-c", str(config), "--base-dir", str(project_dir), "--external-host", "proxy.test"],
    )

    assert result.exit_code == 0
    assert config.exists()
    for relative_path in [
        "stacks",
        "runtime",
        "runtime/generated",
        "publish",
        "downloads",
        "sub",
        "sub/inputs",
        "sub/bundles",
        "sub/current",
    ]:
        assert (project_dir / relative_path).is_dir()


def test_agent_add_uses_template_and_refuses_overwrite(tmp_path: Path) -> None:
    """验证 add 使用模板创建 stack，且不会覆盖已有 stack。"""
    config = init_cli_project(tmp_path)

    result = runner.invoke(agent_app, ["add", "new1", "-c", str(config)])
    duplicate = runner.invoke(agent_app, ["add", "new1", "-c", str(config)])

    assert result.exit_code == 0
    stack_data = YAML(typ="safe").load((config.parent / "stacks" / "new1.yaml").read_text(encoding="utf-8"))
    assert stack_data["name"] == "new1"
    assert stack_data["xrelay"]["outbound"]["ref"] == "new1.clash.socks.local"
    assert duplicate.exit_code == 1


def test_agent_clone_allocates_new_ports(tmp_path: Path) -> None:
    """验证 clone --allocate-ports 会为目标 stack 重分配监听端口。"""
    config = copy_example_project(tmp_path)

    result = runner.invoke(agent_app, ["clone", "usa1", "usa3", "--allocate-ports", "-c", str(config)])

    assert result.exit_code == 0
    cloned_stack = YAML(typ="safe").load((config.parent / "stacks" / "usa3.yaml").read_text(encoding="utf-8"))
    source_stack = YAML(typ="safe").load((config.parent / "stacks" / "usa1.yaml").read_text(encoding="utf-8"))
    assert cloned_stack["name"] == "usa3"
    assert cloned_stack["xrelay"]["outbound"]["ref"] == "usa3.clash.socks.local"
    assert cloned_stack["xrelay"]["inbounds"][0]["port"] != source_stack["xrelay"]["inbounds"][0]["port"]
    assert cloned_stack["clash"]["listeners"]["socks"][0]["port"] != source_stack["clash"]["listeners"]["socks"][0]["port"]


def test_agent_clone_default_refuses_invalid_duplicate_ports(tmp_path: Path) -> None:
    """验证 clone 默认不写入会破坏全局校验的重复端口配置。"""
    config = copy_example_project(tmp_path)

    result = runner.invoke(agent_app, ["clone", "usa1", "usa3", "-c", str(config)])

    assert result.exit_code == 1
    assert "duplicate listen port" in result.output
    assert not (config.parent / "stacks" / "usa3.yaml").exists()


def test_agent_add_members_requires_existing_refs(tmp_path: Path) -> None:
    """验证 add --members 在写入前校验成员 ref 存在。"""
    config = init_cli_project(tmp_path)

    result = runner.invoke(agent_app, ["add", "auto", "--template", "auto-url-test", "--members", "missing", "-c", str(config)])

    assert result.exit_code == 1
    assert "ref does not exist" in result.output
    assert not (config.parent / "stacks" / "auto.yaml").exists()


def test_agent_plan_does_not_write_runtime_files(tmp_path: Path) -> None:
    """验证 plan 只展示文件变化，不写入运行目录文件。"""
    config = copy_example_project(tmp_path)
    generated_dir = config.parent / "runtime" / "generated"

    result = runner.invoke(agent_app, ["plan", "-c", str(config), "--skip-system-ports"])

    assert result.exit_code == 0
    assert "文件变更" in result.output
    assert not generated_dir.exists()


def test_agent_apply_is_idempotent(tmp_path: Path) -> None:
    """验证 apply 第二次执行不会改写未变化文件。"""
    config = copy_example_project(tmp_path)
    manifest = config.parent / "runtime" / "generated" / "manifest.json"

    first = runner.invoke(agent_app, ["apply", "-c", str(config), "--skip-system-ports"])
    os.utime(manifest, (1000, 1000))
    second = runner.invoke(agent_app, ["apply", "-c", str(config), "--skip-system-ports"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "apply 完成：0 个文件变化" in second.output
    assert manifest.stat().st_mtime_ns == 1_000_000_000_000


def test_agent_up_applies_and_reports_changed_target_services(tmp_path: Path) -> None:
    """验证 up 写入生成文件，并只报告目标范围内受影响服务。"""
    config = copy_example_project(tmp_path)

    first = runner.invoke(agent_app, ["up", "xrelay/usa1", "-c", str(config), "--skip-system-ports"])
    second = runner.invoke(agent_app, ["up", "xrelay/usa1", "-c", str(config), "--skip-system-ports"])

    assert first.exit_code == 0
    assert "restart: proxystack-xray@usa1.service" in first.output
    assert "proxystack-clash@usa1.service" not in first.output
    assert (config.parent / "runtime" / "generated" / "xray" / "usa1.json").exists()
    assert second.exit_code == 0
    assert "restart: no services selected" in second.output


def test_agent_service_target_selection() -> None:
    """验证服务 adapter 支持组件和 sub 目标选择。"""
    status_result = runner.invoke(agent_app, ["status", "clash/usa1", "-c", "examples/config.yaml", "--skip-system-ports"])
    logs_result = runner.invoke(agent_app, ["logs", "sub", "--follow", "-c", "examples/config.yaml", "--skip-system-ports"])

    assert status_result.exit_code == 0
    assert "status: proxystack-clash@usa1.service" in status_result.output
    assert "proxystack-xray@usa1.service" not in status_result.output
    assert logs_result.exit_code == 0
    assert "logs --follow: proxystack-sub.service" in logs_result.output


def test_agent_service_commands_skip_system_port_occupancy_by_default() -> None:
    """验证服务命令默认不会因服务自身端口已占用而失败。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            sock.bind(("0.0.0.0", 24001))
            sock.listen()
        except OSError:
            pass
        result = runner.invoke(agent_app, ["status", "usa1", "-c", "examples/config.yaml"])
    finally:
        sock.close()

    assert result.exit_code == 0
    assert "status: proxystack-xray@usa1.service" in result.output


def test_agent_edit_rejects_invalid_stack_before_replacing(tmp_path: Path) -> None:
    """验证 edit 保存前会做全局校验，失败时不替换原 stack。"""
    config = copy_example_project(tmp_path)
    stack_path = config.parent / "stacks" / "usa1.yaml"
    original_text = stack_path.read_text(encoding="utf-8")
    editor = tmp_path / "bad_editor.py"
    editor.write_text(
        """
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
path.write_text(text.replace("usa1.clash.socks.local", "missing.clash.socks.local"), encoding="utf-8")
""".lstrip(),
        encoding="utf-8",
    )

    result = runner.invoke(agent_app, ["edit", "usa1", "--editor", f"{sys.executable} {editor}", "-c", str(config)])

    assert result.exit_code == 1
    assert "ref does not exist" in result.output
    assert stack_path.read_text(encoding="utf-8") == original_text


def test_agent_remove_purge_deletes_generated_files(tmp_path: Path) -> None:
    """验证 remove --purge 删除 stack 文件和 manifest 中对应生成文件。"""
    config = copy_example_project(tmp_path)
    apply_result = runner.invoke(agent_app, ["apply", "usa1", "-c", str(config), "--skip-system-ports"])

    result = runner.invoke(agent_app, ["remove", "usa1", "--purge", "-c", str(config)])

    assert apply_result.exit_code == 0
    assert result.exit_code == 0
    assert not (config.parent / "stacks" / "usa1.yaml").exists()
    assert not (config.parent / "runtime" / "generated" / "xray" / "usa1.json").exists()
    assert not (config.parent / "runtime" / "generated" / "mihomo" / "usa1.yaml").exists()
    manifest = json.loads((config.parent / "runtime" / "generated" / "manifest.json").read_text(encoding="utf-8"))
    assert "xray/usa1.json" not in manifest["files"]
    assert "mihomo/usa1.yaml" not in manifest["files"]


def test_agent_check_edit_check_only_and_doctor(tmp_path: Path) -> None:
    """验证 check、edit --check-only 和 doctor 的基础输出。"""
    config = copy_example_project(tmp_path)

    check_result = runner.invoke(agent_app, ["check", "usa1", "-c", str(config), "--skip-system-ports"])
    edit_result = runner.invoke(agent_app, ["edit", "usa1", "--check-only", "-c", str(config)])
    doctor_result = runner.invoke(agent_app, ["doctor", "-c", str(config)])

    assert check_result.exit_code == 0
    assert "配置校验通过" in check_result.output
    assert edit_result.exit_code == 0
    assert "编辑校验通过" in edit_result.output
    assert doctor_result.exit_code == 0
    assert "Directories:" in doctor_result.output
    assert "Binaries:" in doctor_result.output
    assert "Systemd units:" in doctor_result.output
    assert "Ports:" in doctor_result.output


def test_agent_sub_export_input(tmp_path: Path) -> None:
    """验证 proxystack-agent sub export-input 可以写出 input YAML。"""
    output = tmp_path / "local.yaml"

    result = runner.invoke(
        agent_app,
        ["sub", "export-input", "--source", "local", "-o", str(output), "-c", "examples/config.yaml", "--skip-system-ports"],
    )

    assert result.exit_code == 0
    exported_input = YAML(typ="safe").load(output.read_text(encoding="utf-8"))
    assert exported_input["source"] == "local"
    assert exported_input["nodes"][0]["id"] == "auto:relay"


def test_agent_sub_validate_inputs(tmp_path: Path) -> None:
    """验证 proxystack-agent sub validate-inputs 可以校验 inputs 目录。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_cli_input(input_dir / "manual.yaml")

    result = runner.invoke(agent_app, ["sub", "validate-inputs", "--input-dir", str(input_dir)])

    assert result.exit_code == 0
    assert "订阅 inputs 校验通过" in result.output


def test_agent_publish_example(tmp_path: Path) -> None:
    """验证 proxystack-agent publish 可以生成订阅发布包。"""
    output = tmp_path / "sub-bundle.zip"

    result = runner.invoke(
        agent_app,
        ["publish", "--source", "local", "-o", str(output), "-c", "examples/config.yaml", "--skip-system-ports"],
    )

    assert result.exit_code == 0
    with ZipFile(output) as zip_file:
        assert sorted(zip_file.namelist()) == ["inputs/local.yaml", "manifest.json"]
        manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
    assert manifest["bundle_version"] == 1
    assert "local.yaml" in manifest["inputs_sha256"]


def test_sub_help_is_available() -> None:
    """验证 proxystack-sub 帮助可以正常输出。"""
    result = runner.invoke(sub_app, ["--help"])

    assert result.exit_code == 0
    assert "proxystack-sub" in result.output


def test_sub_version_is_available() -> None:
    """验证 proxystack-sub 版本命令可以正常输出。"""
    result = runner.invoke(sub_app, ["version"])

    assert result.exit_code == 0
    assert "proxystack-sub" in result.output


def test_sub_import_rebuilds_bundle(tmp_path: Path) -> None:
    """验证 proxystack-sub import 默认解包 inputs 并 rebuild 当前索引。"""
    bundle = tmp_path / "sub-bundle.zip"
    data_dir = tmp_path / "sub"
    publish_result = runner.invoke(
        agent_app,
        ["publish", "--source", "local", "-o", str(bundle), "-c", "examples/config.yaml", "--skip-system-ports"],
    )
    assert publish_result.exit_code == 0

    result = runner.invoke(sub_app, ["import", str(bundle), "--data-dir", str(data_dir)])

    assert result.exit_code == 0
    rendered_index = json.loads((data_dir / "current" / "index.json").read_text(encoding="utf-8"))
    assert "alice" in rendered_index["users"]
    assert rendered_index["access"]["token"] == "demo-subscription-token"


def test_sub_import_replaces_old_inputs(tmp_path: Path) -> None:
    """验证连续导入发布包时旧 input 不会残留到 current/index.json。"""
    old_input_dir = tmp_path / "old-inputs"
    new_input_dir = tmp_path / "new-inputs"
    old_input_dir.mkdir()
    new_input_dir.mkdir()
    write_cli_input(old_input_dir / "old.yaml", source="old", node_id="old:id")
    write_cli_input(new_input_dir / "new.yaml", source="new", node_id="new:id")
    old_bundle = tmp_path / "old.zip"
    new_bundle = tmp_path / "new.zip"
    data_dir = tmp_path / "sub"

    old_publish = runner.invoke(agent_app, ["publish", "--input-dir", str(old_input_dir), "--source", "old", "-o", str(old_bundle)])
    new_publish = runner.invoke(agent_app, ["publish", "--input-dir", str(new_input_dir), "--source", "new", "-o", str(new_bundle)])
    assert old_publish.exit_code == 0
    assert new_publish.exit_code == 0

    old_import = runner.invoke(sub_app, ["import", str(old_bundle), "--data-dir", str(data_dir)])
    new_import = runner.invoke(sub_app, ["import", str(new_bundle), "--data-dir", str(data_dir)])

    assert old_import.exit_code == 0
    assert new_import.exit_code == 0
    rendered_index = json.loads((data_dir / "current" / "index.json").read_text(encoding="utf-8"))
    assert [node["id"] for node in rendered_index["nodes"]] == ["new:id"]
    assert sorted(path.name for path in (data_dir / "inputs").iterdir()) == ["new.yaml"]


def test_sub_rebuild_reads_inputs(tmp_path: Path) -> None:
    """验证 proxystack-sub rebuild 扫描 data_dir/inputs 并写 current/index.json。"""
    data_dir = tmp_path / "sub"
    input_dir = data_dir / "inputs"
    input_dir.mkdir(parents=True)
    write_cli_input(input_dir / "manual.yaml")

    result = runner.invoke(sub_app, ["rebuild", "--data-dir", str(data_dir)])

    assert result.exit_code == 0
    rendered_index = json.loads((data_dir / "current" / "index.json").read_text(encoding="utf-8"))
    assert rendered_index["nodes"][0]["id"] == "manual:id"


def write_cli_input(path: Path, source: str = "manual", node_id: str = "manual:id") -> None:
    """写入 CLI 测试使用的最小订阅 input。"""
    content = {
        "input_version": 1,
        "source": source,
        "generated_at": "2026-06-05T12:00:00+08:00",
        "nodes": [
            {
                "id": node_id,
                "user": "alice",
                "protocol": "socks5",
                "server": "proxy.example.com",
                "port": 24001,
                "tag": f"socks5:24001:{node_id}",
                "remark": node_id,
                "auth": {
                    "type": "password",
                    "username": "user",
                    "password": "pass",
                },
            }
        ],
    }
    yaml = YAML()
    with path.open("w", encoding="utf-8") as input_file:
        yaml.dump(content, input_file)


def init_cli_project(tmp_path: Path) -> Path:
    """初始化一个空的 CLI 测试项目，并返回 config.yaml 路径。"""
    project_dir = tmp_path / "project"
    config = project_dir / "config.yaml"
    result = runner.invoke(agent_app, ["init", "-c", str(config), "--base-dir", str(project_dir)])
    assert result.exit_code == 0
    return config


def copy_example_project(tmp_path: Path) -> Path:
    """复制 examples 项目到临时目录，并把 base_dir 改为临时目录。"""
    project_dir = tmp_path / "project"
    stacks_dir = project_dir / "stacks"
    stacks_dir.mkdir(parents=True)
    for source_path in Path("examples/stacks").glob("*.yaml"):
        shutil.copy2(source_path, stacks_dir / source_path.name)

    yaml = YAML(typ="safe")
    config_data = yaml.load(Path("examples/config.yaml").read_text(encoding="utf-8"))
    config_data["base_dir"] = str(project_dir)
    config = project_dir / "config.yaml"
    writer = YAML()
    with config.open("w", encoding="utf-8") as config_file:
        writer.dump(config_data, config_file)
    return config
