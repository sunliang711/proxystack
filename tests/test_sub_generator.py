"""订阅生成器测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
from ruamel.yaml import YAML
from typer.testing import CliRunner

from proxystack.cli.agent import app as agent_app
from proxystack.config import load_config
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.generator.sub import BundleManifest
from proxystack.generator.sub import SubscriptionNode
from proxystack.generator.sub import SubscriptionGeneratorError
from proxystack.generator.sub import SubscriptionInput
from proxystack.generator.sub import build_index
from proxystack.generator.sub import extract_bundle_inputs
from proxystack.generator.sub import input_to_yaml
from proxystack.generator.sub import merge_input_files
from proxystack.generator.sub import render_clash_subscription
from proxystack.generator.sub import render_stack_input
from proxystack.generator.sub import render_surge_subscription
from proxystack.generator.sub import write_bundle
from proxystack.subserver import SubscriptionState

runner = CliRunner()


def test_render_stack_input_filters_sub_true_and_protocol_fields() -> None:
    """验证只导出 sub:true 节点，并保留各协议客户端参数。"""
    subscription_input = render_stack_input(make_stack_set(), "local")
    nodes = {node.id: node for node in subscription_input.nodes}

    assert list(nodes) == ["edge:vmess:alice", "edge:ss", "edge:socks", "edge:http"]
    assert nodes["edge:vmess:alice"].uuid == "22222222-2222-4222-8222-222222222222"
    assert nodes["edge:vmess:alice"].network == "raw"
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

    assert nodes["edge:vmess:alice"].server == "proxy.example.com"
    assert nodes["edge:ss"].server == "ss.example.com"


def test_render_stack_input_expands_vmess_users() -> None:
    """验证 vmess users 会展开为多个订阅节点。"""
    stack_set = StackSet(
        config=load_config(Path("examples/config.yaml")),
        stacks=[
            make_stack(
                [
                    {
                        "name": "vmess",
                        "protocol": "vmess",
                        "listen": "0.0.0.0",
                        "port": 24001,
                        "network": "raw",
                        "tag": "shared-vmess",
                        "sub": True,
                        "users": [
                            {
                                "user": "alice",
                                "uuid": "11111111-1111-4111-8111-111111111111",
                                "remark": "alice vmess",
                                "tag": "alice-vmess",
                            },
                            {
                                "user": "bob",
                                "uuid": "22222222-2222-4222-8222-222222222222",
                                "remark": "bob vmess",
                            },
                        ],
                    }
                ]
            )
        ],
    )

    subscription_input = render_stack_input(stack_set, "local")
    nodes = {node.id: node for node in subscription_input.nodes}

    assert list(nodes) == ["edge:vmess:alice", "edge:vmess:bob"]
    assert nodes["edge:vmess:alice"].user == "alice"
    assert nodes["edge:vmess:alice"].uuid == "11111111-1111-4111-8111-111111111111"
    assert nodes["edge:vmess:alice"].remark == "alice vmess"
    assert nodes["edge:vmess:alice"].tag == "alice-vmess"
    assert nodes["edge:vmess:bob"].user == "bob"
    assert nodes["edge:vmess:bob"].uuid == "22222222-2222-4222-8222-222222222222"
    assert nodes["edge:vmess:bob"].remark == "bob vmess"
    assert nodes["edge:vmess:bob"].tag == "shared-vmess:bob"


def test_render_stack_input_expands_shadowsocks_users() -> None:
    """验证传统 shadowsocks users 会展开为多个订阅节点。"""
    stack_set = StackSet(
        config=load_config(Path("examples/config.yaml")),
        stacks=[
            make_stack(
                [
                    {
                        "name": "ss",
                        "protocol": "shadowsocks",
                        "listen": "0.0.0.0",
                        "port": 24001,
                        "method": "aes-256-gcm",
                        "password": "server-pass",
                        "tag": "shared-ss",
                        "sub": True,
                        "users": [
                            {
                                "user": "alice",
                                "password": "alice-pass",
                                "method": "aes-128-gcm",
                                "remark": "alice ss",
                            },
                            {
                                "user": "bob",
                                "password": "bob-pass",
                            },
                        ],
                    }
                ]
            )
        ],
    )

    subscription_input = render_stack_input(stack_set, "local")
    nodes = {node.id: node for node in subscription_input.nodes}

    assert list(nodes) == ["edge:ss:alice", "edge:ss:bob"]
    assert nodes["edge:ss:alice"].user == "alice"
    assert nodes["edge:ss:alice"].method == "aes-128-gcm"
    assert nodes["edge:ss:alice"].password == "alice-pass"
    assert nodes["edge:ss:alice"].remark == "alice ss"
    assert nodes["edge:ss:bob"].method == "aes-256-gcm"
    assert nodes["edge:ss:bob"].password == "bob-pass"
    assert nodes["edge:ss:bob"].tag == "shared-ss:bob"


def test_render_stack_input_expands_shadowsocks_2022_users() -> None:
    """验证 SS2022 users 订阅节点会使用 ServerPassword:UserPassword。"""
    stack_set = StackSet(
        config=load_config(Path("examples/config.yaml")),
        stacks=[
            make_stack(
                [
                    {
                        "name": "ss2022",
                        "protocol": "shadowsocks",
                        "listen": "0.0.0.0",
                        "port": 24001,
                        "method": "2022-blake3-aes-256-gcm",
                        "password": "server-key",
                        "sub": True,
                        "users": [
                            {
                                "user": "alice",
                                "password": "alice-key",
                            },
                            {
                                "user": "bob",
                                "password": "bob-key",
                            },
                        ],
                    }
                ]
            )
        ],
    )

    subscription_input = render_stack_input(stack_set, "local")
    nodes = {node.id: node for node in subscription_input.nodes}

    assert list(nodes) == ["edge:ss2022:alice", "edge:ss2022:bob"]
    assert nodes["edge:ss2022:alice"].method == "2022-blake3-aes-256-gcm"
    assert nodes["edge:ss2022:alice"].password == "server-key:alice-key"
    assert nodes["edge:ss2022:bob"].password == "server-key:bob-key"


def test_render_stack_input_does_not_include_clash_config() -> None:
    """验证订阅 input 不包含 clash upstream/group/rules/mode/controller 信息。"""
    rendered_input = input_to_yaml(render_stack_input(make_stack_set(), "local"))

    assert "upstreams" not in rendered_input
    assert "proxy-groups" not in rendered_input
    assert "rules" not in rendered_input
    assert "controller" not in rendered_input
    assert "mode" not in rendered_input


def test_subscription_renderers_emit_full_configs_and_surge_auth_syntax() -> None:
    """验证订阅输出包含完整配置段，并使用 Surge 官方鉴权语法。"""
    nodes = [
        SubscriptionNode(
            id="manual:vmess",
            user="alice",
            protocol="vmess",
            server="proxy.example.com",
            port=24001,
            tag="vmess:24001:manual",
            remark="Alice VMess",
            uuid="11111111-1111-4111-8111-111111111111",
            network="raw",
        ),
        SubscriptionNode(
            id="manual:ss",
            user="alice",
            protocol="shadowsocks",
            server="proxy.example.com",
            port=24002,
            tag="ss:24002:manual",
            remark="Alice SS",
            cipher="chacha20-ietf-poly1305",
            password="ss-pass",
        ),
        SubscriptionNode(
            id="manual:socks",
            user="alice",
            protocol="socks5",
            server="proxy.example.com",
            port=24003,
            tag="socks5:24003:manual",
            remark="Alice Socks",
            udp=True,
            auth={"type": "password", "username": "sock-user", "password": "sock-pass"},
        ),
        SubscriptionNode(
            id="manual:http",
            user="alice",
            protocol="http",
            server="proxy.example.com",
            port=24004,
            tag="http:24004:manual",
            remark="Alice HTTP",
            auth={"type": "password", "username": "http-user", "password": "http-pass"},
        ),
    ]
    index = build_index(nodes, ["manual"])

    clash = YAML(typ="safe").load(render_clash_subscription(index, "alice"))
    proxy_names = ["Alice VMess", "Alice SS", "Alice Socks", "Alice HTTP"]
    assert clash["mode"] == "Rule"
    assert [proxy["name"] for proxy in clash["proxies"]] == proxy_names
    assert clash["proxy-groups"][0]["proxies"] == ["auto", "loadbalance", *proxy_names, "DIRECT"]
    assert clash["rules"][-1] == "MATCH,Final"

    surge = render_surge_subscription(index, "alice")
    assert "[General]" in surge
    assert "[Proxy Group]" in surge
    assert "[Rule]" in surge
    assert (
        "Alice VMess = vmess, proxy.example.com, 24001, "
        "username=11111111-1111-4111-8111-111111111111, network=raw, vmess-aead=true"
    ) in surge
    assert "Alice Socks = socks5, proxy.example.com, 24003, sock-user, sock-pass, udp-relay=true" in surge
    assert "Alice HTTP = http, proxy.example.com, 24004, http-user, http-pass" in surge
    assert "Alice Socks = socks5, proxy.example.com, 24003, username=" not in surge


def test_subscription_renderer_uses_data_dir_template_override(tmp_path: Path) -> None:
    """验证订阅渲染会读取 data_dir 下的本地模板覆盖。"""
    template_dir = tmp_path / "templates" / "sub"
    template_dir.mkdir(parents=True)
    (template_dir / "clash.yaml.j2").write_text(
        "mode: LocalTemplate\nproxies:\n{{ proxies | yaml_block }}",
        encoding="utf-8",
    )
    index = build_index(
        [
            SubscriptionNode(
                id="manual:socks",
                user="alice",
                protocol="socks5",
                server="proxy.example.com",
                port=24003,
                tag="socks5:24003:manual",
                remark="Alice Socks",
            )
        ],
        ["manual"],
    )

    rendered = render_clash_subscription(index, "alice", data_dir=tmp_path)

    assert "mode: LocalTemplate" in rendered
    assert "Alice Socks" in rendered
    assert "proxy-groups:" not in rendered


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
    state = SubscriptionState(data_dir, access=agent_index.access)
    state.load()
    sub_index = state.snapshot()

    assert [node.id for node in sub_index.nodes] == [node.id for node in agent_index.nodes]
    assert sub_index.users.keys() == agent_index.users.keys()


def test_input_yaml_contains_schema_metadata() -> None:
    """验证导出的订阅 input 包含 schema 和版本元数据。"""
    rendered_input = YAML(typ="safe").load(input_to_yaml(render_stack_input(make_stack_set(), "local")))

    assert rendered_input["input_schema"] == "proxystack.subscription-input"
    assert rendered_input["input_version"] == 1


def test_input_and_bundle_version_metadata_require_integer_v1() -> None:
    """验证版本元数据必须是整型 v1，避免 bool/float 被宽松接受。"""
    with pytest.raises(ValueError, match="unsupported subscription input version"):
        SubscriptionInput.model_validate({"input_version": True, "source": "bad", "generated_at": "now", "nodes": []})
    with pytest.raises(ValueError, match="unsupported subscription bundle version"):
        BundleManifest.model_validate({"bundle_version": 1.0, "source": "bad", "generated_at": "now", "inputs_sha256": {}})


def test_sub_export_splits_all_stacks_into_inputs(tmp_path: Path) -> None:
    """验证 sub export 默认按 stack 拆分发布包内 input。"""
    output = tmp_path / "bundle.zip"

    result = runner.invoke(
        agent_app,
        ["sub", "export", "-o", str(output), "-c", "examples/config.yaml"],
    )

    assert result.exit_code == 0
    with ZipFile(output) as zip_file:
        assert sorted(zip_file.namelist()) == [
            "inputs/auto.yaml",
            "inputs/usa1.yaml",
            "inputs/usa2.yaml",
            "manifest.json",
        ]
        manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
    assert manifest["bundle_schema"] == "proxystack.sub-bundle"
    assert manifest["access"] == {"type": "none"}


def test_sub_export_stack_writes_single_input(tmp_path: Path) -> None:
    """验证指定 stack 导出时只写该 stack 对应 input。"""
    config = Path("examples/config.yaml")
    output = tmp_path / "bundle.zip"

    result = runner.invoke(
        agent_app,
        ["sub", "export", "usa1", "-o", str(output), "-c", str(config)],
    )

    assert result.exit_code == 0
    with ZipFile(output) as zip_file:
        assert sorted(zip_file.namelist()) == ["inputs/usa1.yaml", "manifest.json"]


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


def test_extract_bundle_rejects_invalid_hash_format(tmp_path: Path) -> None:
    """验证 manifest 中的 input hash 必须是标准 sha256 十六进制。"""
    bundle = tmp_path / "bad-hash-format.zip"
    content = input_to_yaml(render_stack_input(make_stack_set(), "manual")).encode("utf-8")
    with ZipFile(bundle, "w") as zip_file:
        zip_file.writestr(
            "manifest.json",
            json.dumps(
                {
                    "bundle_version": 1,
                    "source": "bad",
                    "generated_at": "now",
                    "inputs_sha256": {"manual.yaml": "not-sha256"},
                }
            ),
        )
        zip_file.writestr("inputs/manual.yaml", content)

    with pytest.raises(SubscriptionGeneratorError, match="bundle manifest schema is invalid"):
        extract_bundle_inputs(bundle, tmp_path / "sub")


def test_extract_bundle_rejects_duplicate_nodes_before_replacing_inputs(tmp_path: Path) -> None:
    """验证坏 bundle 合并失败时不会提前清理旧 inputs。"""
    data_dir = tmp_path / "sub"
    old_bundle = tmp_path / "old.zip"
    bad_bundle = tmp_path / "bad-duplicate.zip"
    old_input = tmp_path / "old.yaml"
    first_input = tmp_path / "first.yaml"
    second_input = tmp_path / "second.yaml"
    write_input(old_input, "old", "old:id", "alice")
    write_input(first_input, "first", "same:id", "alice")
    write_input(second_input, "second", "same:id", "bob")
    write_bundle(old_bundle, "old", [("old.yaml", old_input.read_bytes())])
    write_bundle(
        bad_bundle,
        "bad",
        [
            ("first.yaml", first_input.read_bytes()),
            ("second.yaml", second_input.read_bytes()),
        ],
    )
    extract_bundle_inputs(old_bundle, data_dir)

    with pytest.raises(SubscriptionGeneratorError, match="duplicate node id: same:id"):
        extract_bundle_inputs(bad_bundle, data_dir)

    assert sorted(path.name for path in (data_dir / "inputs").iterdir()) == ["old.yaml"]


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


def test_extract_bundle_rejects_native_backup_schema(tmp_path: Path) -> None:
    """验证订阅导入拒绝后续 M5 原生备份包 schema。"""
    bundle = tmp_path / "backup-like.zip"
    content = input_to_yaml(render_stack_input(make_stack_set(), "manual")).encode("utf-8")
    with ZipFile(bundle, "w") as zip_file:
        zip_file.writestr(
            "manifest.json",
            json.dumps(
                {
                    "bundle_schema": "proxystack.native-backup",
                    "bundle_version": 1,
                    "source": "bad",
                    "generated_at": "now",
                    "inputs_sha256": {"manual.yaml": __import__("hashlib").sha256(content).hexdigest()},
                }
            ),
        )
        zip_file.writestr("inputs/manual.yaml", content)

    with pytest.raises(SubscriptionGeneratorError, match="bundle manifest schema is invalid"):
        extract_bundle_inputs(bundle, tmp_path / "sub")


def test_extract_bundle_rejects_invalid_bundled_input_schema(tmp_path: Path) -> None:
    """验证导入发布包时会校验 input schema，而不是只校验 hash。"""
    bundle = tmp_path / "bad-input-schema.zip"
    content = b'input_schema: proxystack.other\ninput_version: 1\nsource: bad\ngenerated_at: "now"\nnodes: []\n'
    with ZipFile(bundle, "w") as zip_file:
        zip_file.writestr(
            "manifest.json",
            json.dumps(
                {
                    "bundle_version": 1,
                    "source": "bad",
                    "generated_at": "now",
                    "inputs_sha256": {"manual.yaml": __import__("hashlib").sha256(content).hexdigest()},
                }
            ),
        )
        zip_file.writestr("inputs/manual.yaml", content)

    with pytest.raises(SubscriptionGeneratorError, match="invalid bundled subscription input manual.yaml"):
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


def make_stack(inbounds: list[dict[str, Any]] | None = None) -> Stack:
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
                "inbounds": inbounds or [
                    {
                        "name": "vmess",
                        "protocol": "vmess",
                        "listen": "0.0.0.0",
                        "port": 24001,
                        "network": "raw",
                        "sub": True,
                        "users": [
                            {
                                "user": "alice",
                                "uuid": "22222222-2222-4222-8222-222222222222",
                            }
                        ],
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
