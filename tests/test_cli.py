"""CLI 骨架测试。"""

import json
from pathlib import Path
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
