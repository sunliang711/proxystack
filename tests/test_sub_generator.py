"""订阅生成器测试。"""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from ruamel.yaml import YAML
from typer.testing import CliRunner

from proxystack.cli.agent import app as agent_app
from proxystack.cli.sub import rebuild_data_dir
from proxystack.config import load_config
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.generator.sub import SubscriptionGeneratorError
from proxystack.generator.sub import extract_bundle_inputs
from proxystack.generator.sub import index_to_json
from proxystack.generator.sub import input_to_yaml
from proxystack.generator.sub import load_index_file
from proxystack.generator.sub import merge_input_files
from proxystack.generator.sub import render_stack_input
from proxystack.generator.sub import write_bundle

runner = CliRunner()


def test_render_stack_input_filters_sub_true_and_protocol_fields() -> None:
    """验证只导出 sub:true 节点，并保留各协议客户端参数。"""
    subscription_input = render_stack_input(make_stack_set(), "local")
    nodes = {node.id: node for node in subscription_input.nodes}

    assert list(nodes) == ["edge:vmess", "edge:ss", "edge:socks", "edge:http"]
    assert nodes["edge:vmess"].uuid == "22222222-2222-4222-8222-222222222222"
    assert nodes["edge:vmess"].network == "raw"
    assert nodes["edge:ss"].method == "chacha20-ietf-poly1305"
    assert nodes["edge:ss"].cipher == "chacha20-ietf-poly1305"
    assert nodes["edge:ss"].password == "ss-pass"
    assert nodes["edge:socks"].auth is not None
    assert nodes["edge:socks"].auth.username == "sock-user"
    assert nodes["edge:http"].auth is not None
    assert nodes["edge:http"].auth.password == "http-pass"
    assert "edge:hidden" not in nodes


def test_render_stack_input_uses_external_host_and_inbound_override() -> None:
    """验证 server 默认使用 external_host，且允许 inbound.server 覆盖。"""
    subscription_input = render_stack_input(make_stack_set(), "local")
    nodes = {node.id: node for node in subscription_input.nodes}

    assert nodes["edge:vmess"].server == "proxy.example.com"
    assert nodes["edge:ss"].server == "ss.example.com"


def test_render_stack_input_does_not_include_clash_config() -> None:
    """验证订阅 input 不包含 clash upstream/group/rules/mode/controller 信息。"""
    rendered_input = input_to_yaml(render_stack_input(make_stack_set(), "local"))

    assert "upstreams" not in rendered_input
    assert "proxy-groups" not in rendered_input
    assert "rules" not in rendered_input
    assert "controller" not in rendered_input
    assert "mode" not in rendered_input


def test_merge_input_files_rejects_duplicate_node_id(tmp_path: Path) -> None:
    """验证多个 input 中重复 node.id 默认失败并输出冲突信息。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_input(input_dir / "a.yaml", "a", "same:id", "alice")
    write_input(input_dir / "b.yaml", "b", "same:id", "bob")

    with pytest.raises(SubscriptionGeneratorError, match="duplicate node id: same:id"):
        merge_input_files(input_dir)


def test_merge_input_files_sorts_by_filename(tmp_path: Path) -> None:
    """验证 inputs 按文件名稳定合并。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_input(input_dir / "b.yaml", "b", "b:id", "bob")
    write_input(input_dir / "a.yaml", "a", "a:id", "alice")

    index = merge_input_files(input_dir)

    assert [node.id for node in index.nodes] == ["a:id", "b:id"]
    assert index.sources == ["a", "b"]


def test_agent_and_sub_merge_logic_are_consistent(tmp_path: Path) -> None:
    """验证 agent 和 sub 复用同一套 inputs 合并逻辑。"""
    data_dir = tmp_path / "sub"
    input_dir = data_dir / "inputs"
    input_dir.mkdir(parents=True)
    write_input(input_dir / "a.yaml", "a", "a:id", "alice")
    write_input(input_dir / "b.json", "b", "b:id", "alice", as_json=True)

    agent_index = merge_input_files(input_dir)
    index_path = rebuild_data_dir(data_dir)
    sub_index = load_index_file(index_path)

    assert index_to_json(agent_index) != ""
    assert [node.id for node in sub_index.nodes] == [node.id for node in agent_index.nodes]
    assert sub_index.users.keys() == agent_index.users.keys()


def test_publish_input_dir_excludes_stack_by_default(tmp_path: Path) -> None:
    """验证 publish --input-dir 默认只打包 input-dir，不包含当前 stack。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_input(input_dir / "manual.yaml", "manual", "manual:id", "alice")
    output = tmp_path / "bundle.zip"

    result = runner.invoke(
        agent_app,
        [
            "publish",
            "--input-dir",
            str(input_dir),
            "--source",
            "merged",
            "-o",
            str(output),
            "-c",
            "examples/config.yaml",
        ],
    )

    assert result.exit_code == 0
    with ZipFile(output) as zip_file:
        assert sorted(zip_file.namelist()) == ["inputs/manual.yaml", "manifest.json"]
        manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
    assert manifest["access"]["type"] == "token"
    assert manifest["access"]["token"] == "demo-subscription-token"


def test_publish_input_dir_rejects_missing_explicit_config(tmp_path: Path) -> None:
    """验证显式传入不存在的 config 时不会静默降级为无鉴权发布包。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_input(input_dir / "manual.yaml", "manual", "manual:id", "alice")
    output = tmp_path / "bundle.zip"

    result = runner.invoke(
        agent_app,
        [
            "publish",
            "--input-dir",
            str(input_dir),
            "--source",
            "merged",
            "-o",
            str(output),
            "-c",
            str(tmp_path / "missing-config.yaml"),
        ],
    )

    assert result.exit_code == 1
    assert "config file does not exist" in result.output


def test_publish_include_stack_adds_stack_input(tmp_path: Path) -> None:
    """验证 publish --input-dir --include-stack 才会把当前 stack input 合入 bundle。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_input(input_dir / "manual.yaml", "manual", "manual:id", "alice")
    output = tmp_path / "bundle.zip"

    result = runner.invoke(
        agent_app,
        [
            "publish",
            "--input-dir",
            str(input_dir),
            "--include-stack",
            "--source",
            "stack",
            "-o",
            str(output),
            "-c",
            "examples/config.yaml",
            "--skip-system-ports",
        ],
    )

    assert result.exit_code == 0
    with ZipFile(output) as zip_file:
        assert "inputs/manual.yaml" in zip_file.namelist()
        assert "inputs/stack.yaml" in zip_file.namelist()


def test_write_bundle_rejects_unsafe_input_name(tmp_path: Path) -> None:
    """验证发布包写入阶段拒绝带路径片段的 input 名称。"""
    with pytest.raises(SubscriptionGeneratorError, match="unsafe bundle input file"):
        write_bundle(tmp_path / "bundle.zip", "bad", [("../bad.yaml", b"bad")])


def test_extract_bundle_rejects_unsafe_member_path(tmp_path: Path) -> None:
    """验证导入发布包时拒绝 zip 路径穿越。"""
    bundle = tmp_path / "unsafe.zip"
    with ZipFile(bundle, "w") as zip_file:
        zip_file.writestr("manifest.json", json.dumps({"bundle_version": 1, "source": "bad", "generated_at": "now", "inputs_sha256": {}}))
        zip_file.writestr("../bad.yaml", "bad")

    with pytest.raises(SubscriptionGeneratorError, match="unsafe bundle path"):
        extract_bundle_inputs(bundle, tmp_path / "sub")


def test_extract_bundle_rejects_hash_mismatch(tmp_path: Path) -> None:
    """验证导入发布包时校验 input sha256。"""
    bundle = tmp_path / "bad-hash.zip"
    with ZipFile(bundle, "w") as zip_file:
        zip_file.writestr(
            "manifest.json",
            json.dumps(
                {
                    "bundle_version": 1,
                    "source": "bad",
                    "generated_at": "now",
                    "inputs_sha256": {"manual.yaml": "0" * 64},
                }
            ),
        )
        zip_file.writestr("inputs/manual.yaml", input_to_yaml(render_stack_input(make_stack_set(), "manual")))

    with pytest.raises(SubscriptionGeneratorError, match="input hash mismatch"):
        extract_bundle_inputs(bundle, tmp_path / "sub")


def test_extract_bundle_rejects_unsupported_input_extension(tmp_path: Path) -> None:
    """验证导入发布包时拒绝 manifest 中不支持的 input 扩展名。"""
    bundle = tmp_path / "bad-extension.zip"
    content = input_to_yaml(render_stack_input(make_stack_set(), "manual")).encode("utf-8")
    with ZipFile(bundle, "w") as zip_file:
        zip_file.writestr(
            "manifest.json",
            json.dumps(
                {
                    "bundle_version": 1,
                    "source": "bad",
                    "generated_at": "now",
                    "inputs_sha256": {"manual.txt": __import__("hashlib").sha256(content).hexdigest()},
                }
            ),
        )
        zip_file.writestr("inputs/manual.txt", content)

    with pytest.raises(SubscriptionGeneratorError, match="unsafe bundle input file"):
        extract_bundle_inputs(bundle, tmp_path / "sub")


def test_extract_bundle_rejects_invalid_bundle_version(tmp_path: Path) -> None:
    """验证导入发布包时拒绝不支持的 bundle_version。"""
    bundle = tmp_path / "bad-version.zip"
    content = input_to_yaml(render_stack_input(make_stack_set(), "manual")).encode("utf-8")
    with ZipFile(bundle, "w") as zip_file:
        zip_file.writestr(
            "manifest.json",
            json.dumps(
                {
                    "bundle_version": 2,
                    "source": "bad",
                    "generated_at": "now",
                    "inputs_sha256": {"manual.yaml": __import__("hashlib").sha256(content).hexdigest()},
                }
            ),
        )
        zip_file.writestr("inputs/manual.yaml", content)

    with pytest.raises(SubscriptionGeneratorError, match="bundle manifest schema is invalid"):
        extract_bundle_inputs(bundle, tmp_path / "sub")


def test_extract_bundle_rejects_corrupt_zip(tmp_path: Path) -> None:
    """验证导入损坏 zip 时返回订阅生成错误。"""
    bundle = tmp_path / "corrupt.zip"
    bundle.write_bytes(b"not a zip")

    with pytest.raises(SubscriptionGeneratorError, match="invalid subscription bundle zip"):
        extract_bundle_inputs(bundle, tmp_path / "sub")


def write_input(path: Path, source: str, node_id: str, user: str, *, as_json: bool = False) -> None:
    """写入测试用订阅 input。"""
    content = {
        "input_version": 1,
        "source": source,
        "generated_at": "2026-06-05T12:00:00+08:00",
        "nodes": [
            {
                "id": node_id,
                "user": user,
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
    if as_json:
        path.write_text(__import__("json").dumps(content), encoding="utf-8")
        return
    yaml = YAML()
    with path.open("w", encoding="utf-8") as input_file:
        yaml.dump(content, input_file)


def make_stack_set() -> StackSet:
    """生成覆盖订阅协议和 server 覆盖规则的 StackSet。"""
    return StackSet(config=load_config(Path("examples/config.yaml")), stacks=[make_stack()])


def make_stack() -> Stack:
    """生成测试用 stack 模型。"""
    return Stack.model_validate(
        {
            "name": "edge",
            "enabled": True,
            "role": "edge",
            "labels": ["test"],
            "xrelay": {
                "enabled": True,
                "outbound": {"type": "direct"},
                "inbounds": [
                    {
                        "name": "vmess",
                        "protocol": "vmess",
                        "listen": "0.0.0.0",
                        "port": 24001,
                        "uuid": "22222222-2222-4222-8222-222222222222",
                        "network": "raw",
                        "user": "alice",
                        "sub": True,
                    },
                    {
                        "name": "ss",
                        "protocol": "shadowsocks",
                        "listen": "0.0.0.0",
                        "port": 24002,
                        "method": "chacha20-ietf-poly1305",
                        "password": "ss-pass",
                        "server": "ss.example.com",
                        "user": "alice",
                        "sub": True,
                    },
                    {
                        "name": "socks",
                        "protocol": "socks5",
                        "listen": "0.0.0.0",
                        "port": 24003,
                        "auth": {
                            "type": "password",
                            "username": "sock-user",
                            "password": "sock-pass",
                        },
                        "user": "bob",
                        "sub": True,
                    },
                    {
                        "name": "http",
                        "protocol": "http",
                        "listen": "0.0.0.0",
                        "port": 24004,
                        "auth": {
                            "type": "password",
                            "username": "http-user",
                            "password": "http-pass",
                        },
                        "user": "bob",
                        "sub": True,
                    },
                    {
                        "name": "hidden",
                        "protocol": "socks5",
                        "listen": "127.0.0.1",
                        "port": 24005,
                        "auth": {"type": "noauth"},
                        "user": "alice",
                        "sub": False,
                    },
                ],
            },
            "clash": {
                "enabled": True,
                "mode": "Rule",
                "controller": {
                    "listen": "127.0.0.1:19001",
                    "secret": "demo-secret",
                },
                "listeners": {
                    "socks": [
                        {
                            "name": "local",
                            "listen": "127.0.0.1",
                            "port": 17001,
                        }
                    ],
                },
                "upstreams": [
                    {
                        "name": "server-a",
                        "type": "raw",
                        "config": {
                            "type": "shadowsocks",
                            "server": "server-a.example.com",
                            "port": 8388,
                            "cipher": "aes-256-gcm",
                            "password": "raw-pass",
                        },
                    }
                ],
                "groups": [
                    {
                        "name": "AllProxy",
                        "type": "select",
                        "proxies": ["server-a", "DIRECT"],
                    }
                ],
                "rules": {
                    "profile": "default",
                },
            },
        }
    )
