"""配置加载入口测试。"""

from pathlib import Path

from pydantic import ValidationError
import pytest

from proxystack.config import load_config
from proxystack.config import load_config_file
from proxystack.config import load_stack
from proxystack.config import load_stacks
from proxystack.domain import ConfigValidationError
from proxystack.domain.models import PortRange
from proxystack.domain.models import StackSet
from proxystack.domain.validation import validate_stack_set
from proxystack.graph import ServiceNode
from proxystack.graph import build_reference_graph

SS2022_SERVER_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
SS2022_ALICE_KEY = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="
SS2022_BOB_KEY = "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI="


def test_load_config_file_reads_yaml_mapping() -> None:
    """验证 fixture 全局配置可以读取为字典。"""
    config = load_config_file(Path("tests/fixtures/example-project/config.yaml"))

    assert config["version"] == 1
    assert config["base_dir"] == "./tests/fixtures/example-project"


def test_load_config_and_stacks_accept_examples() -> None:
    """验证测试项目 fixture 可以通过强类型模型和跨 stack 校验。"""
    config = load_config(Path("tests/fixtures/example-project/config.yaml"))
    stack_set = load_stacks(config)

    assert stack_set.stack_names == ["auto", "usa1", "usa2"]
    assert stack_set.by_name()["usa1"].clash.mode == "Rule"


def test_load_config_log_levels_keep_legacy_defaults(tmp_path: Path) -> None:
    """验证旧配置不写日志级别时沿用 Xray warning 和 mihomo info。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(valid_config_yaml(tmp_path), encoding="utf-8")

    config = load_config(config_path)

    assert config.defaults.xrelay.loglevel == "warning"
    assert config.defaults.clash.loglevel == "info"


def test_load_project_accepts_custom_log_levels_from_yaml(tmp_path: Path) -> None:
    """验证 YAML 中的全局默认和 stack 级日志级别覆盖都能加载。"""
    stacks_dir = tmp_path / "stacks"
    stacks_dir.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        valid_config_yaml(tmp_path)
        + "defaults:\n"
        + "  xrelay:\n"
        + "    loglevel: error\n"
        + "  clash:\n"
        + "    loglevel: warning\n",
        encoding="utf-8",
    )
    stack_yaml = valid_stack_yaml("edge").replace(
        "xrelay:\n  enabled: true",
        "xrelay:\n  enabled: true\n  loglevel: none",
    ).replace(
        "clash:\n  enabled: true",
        "clash:\n  enabled: true\n  loglevel: silent",
    )
    (stacks_dir / "edge.yaml").write_text(stack_yaml, encoding="utf-8")

    config = load_config(config_path)
    stack_set = load_stacks(config, check_system_ports=False)
    stack = stack_set.by_name()["edge"]

    assert config.defaults.xrelay.loglevel == "error"
    assert config.defaults.clash.loglevel == "warning"
    assert stack.xrelay.loglevel == "none"
    assert stack.clash.loglevel == "silent"


@pytest.mark.parametrize(
    ("defaults_yaml", "message"),
    [
        ("defaults:\n  xrelay:\n    loglevel: verbose\n", "loglevel"),
        ("defaults:\n  clash:\n    loglevel: notice\n", "loglevel"),
    ],
)
def test_load_config_rejects_invalid_default_log_level(
    tmp_path: Path,
    defaults_yaml: str,
    message: str,
) -> None:
    """验证全局默认日志级别只接受各生成器支持的枚举值。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(valid_config_yaml(tmp_path) + defaults_yaml, encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        load_config(config_path)


def test_reference_graph_indexes_examples() -> None:
    """验证测试项目 fixture 能建立 xrelay inbound 和 clash listener 索引。"""
    config = load_config(Path("tests/fixtures/example-project/config.yaml"))
    stack_set = load_stacks(config, check_system_ports=False)

    graph = build_reference_graph(stack_set)
    inbound = graph.index.resolve_xrelay_inbound("usa1.relay")
    listener = graph.index.resolve_clash_listener("usa1.clash.socks")

    assert inbound is not None
    assert inbound.kind == "socks5"
    assert inbound.port == 24001
    assert listener is not None
    assert listener.kind == "socks"
    assert listener.port == 17091


def test_reference_graph_orders_dependencies_before_consumers() -> None:
    """验证 auto clash 排在被引用的边缘 xrelay 之后启动。"""
    config = load_config(Path("tests/fixtures/example-project/config.yaml"))
    stack_set = load_stacks(config, check_system_ports=False)

    graph = build_reference_graph(stack_set)
    order = graph.topological_order()

    assert order.index(ServiceNode(stack="usa1", component="xrelay")) < order.index(
        ServiceNode(stack="auto", component="clash")
    )
    assert order.index(ServiceNode(stack="usa2", component="xrelay")) < order.index(
        ServiceNode(stack="auto", component="clash")
    )


def test_reference_graph_excludes_disabled_stack_from_plan() -> None:
    """验证禁用 stack 不进入 endpoint 索引和 plan 输出。"""
    config = load_config(Path("tests/fixtures/example-project/config.yaml"))
    stack_set = load_stacks(config, check_system_ports=False)
    stacks = []
    for stack in stack_set.stacks:
        if stack.name == "auto":
            stack = stack.model_copy(deep=True)
            stack.enabled = False
        stacks.append(stack)

    graph = build_reference_graph(StackSet(config=config, stacks=stacks))
    plan = graph.build_plan()

    assert graph.index.resolve_xrelay_inbound("auto.relay") is None
    assert all(node.stack != "auto" for node in plan.operation_order)


def test_load_config_file_rejects_non_mapping(tmp_path: Path) -> None:
    """验证配置文件顶层不是映射时会失败。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("- invalid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Config file must be a mapping"):
        load_config_file(config_path)


def test_load_config_file_reports_missing_path(tmp_path: Path) -> None:
    """验证配置文件不存在时返回带路径的友好错误。"""
    config_path = tmp_path / "missing.yaml"

    with pytest.raises(ValueError, match="Config file could not be read"):
        load_config_file(config_path)


def test_load_stack_reports_missing_path(tmp_path: Path) -> None:
    """验证 stack 文件不存在时返回带路径的友好错误。"""
    stack_path = tmp_path / "missing.yaml"

    with pytest.raises(ValueError, match="Stack file could not be read"):
        load_stack(stack_path)


def test_load_config_file_reports_invalid_yaml(tmp_path: Path) -> None:
    """验证 YAML 解析失败时返回带路径的友好错误。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("version: [\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Config file contains invalid YAML"):
        load_config_file(config_path)


def test_load_stack_rejects_file_name_mismatch(tmp_path: Path) -> None:
    """验证 stack 文件名必须与 name 字段一致。"""
    stack_path = tmp_path / "wrong.yaml"
    stack_path.write_text(valid_stack_yaml("right"), encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="stack name must match file name"):
        load_stack(stack_path)


def test_load_stack_rejects_invalid_mode(tmp_path: Path) -> None:
    """验证非法 clash mode 会失败。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(valid_stack_yaml("edge").replace("mode: Rule", "mode: Bad"), encoding="utf-8")

    with pytest.raises(ValidationError, match="mode"):
        load_stack(stack_path)


@pytest.mark.parametrize(
    ("target", "replacement"),
    [
        ("xrelay:\n  enabled: true", "xrelay:\n  enabled: true\n  loglevel: verbose"),
        ("clash:\n  enabled: true", "clash:\n  enabled: true\n  loglevel: notice"),
    ],
)
def test_load_stack_rejects_invalid_stack_log_level(tmp_path: Path, target: str, replacement: str) -> None:
    """验证 stack 级日志级别只接受对应生成器支持的枚举值。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(valid_stack_yaml("edge").replace(target, replacement), encoding="utf-8")

    with pytest.raises(ValidationError, match="loglevel"):
        load_stack(stack_path)


def test_load_stack_rejects_duplicate_inbound_name(tmp_path: Path) -> None:
    """验证同一 stack 内重复 inbound name 会失败。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "  inbounds:\n",
            "  inbounds:\n"
            "    - name: relay\n"
            "      protocol: socks5\n"
            "      listen: 127.0.0.1\n"
            "      port: 24003\n"
            "      auth:\n"
            "        type: noauth\n"
            "      sub: false\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="duplicate inbound name"):
        load_stack(stack_path)


def test_load_stack_rejects_out_of_range_port(tmp_path: Path) -> None:
    """验证端口越界会失败。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(valid_stack_yaml("edge").replace("port: 24001", "port: 70000"), encoding="utf-8")

    with pytest.raises(ValidationError, match="less than or equal to 65535"):
        load_stack(stack_path)


def test_load_stack_rejects_missing_vmess_users(tmp_path: Path) -> None:
    """验证 vmess inbound 缺少 users 会失败。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      users:\n"
            "        - user: alice\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n"
            "          remark: edge vmess\n",
            "",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="users is required for vmess inbound"):
        load_stack(stack_path)


def test_load_stack_rejects_vmess_users_missing_network(tmp_path: Path) -> None:
    """验证 vmess users 多用户结构仍必须提供 network。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace("      network: raw\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="network is required for vmess inbound"):
        load_stack(stack_path)


def test_load_stack_accepts_vmess_users(tmp_path: Path) -> None:
    """验证 vmess inbound 可以使用 users 多用户结构。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      users:\n"
            "        - user: alice\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n"
            "          remark: edge vmess\n",
            "      users:\n"
            "        - user: alice\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n"
            "          remark: alice vmess\n"
            "        - user: bob\n"
            "          uuid: 22222222-2222-4222-8222-222222222222\n"
            "          remark: bob vmess\n",
        ),
        encoding="utf-8",
    )

    stack = load_stack(stack_path)

    inbound = stack.xrelay.inbounds[1]
    assert [vmess_user.user for vmess_user in inbound.users] == ["alice", "bob"]
    assert inbound.users[0].remark == "alice vmess"


def test_load_stack_rejects_vmess_users_invalid_uuid(tmp_path: Path) -> None:
    """验证 vmess users 中每个 UUID 都必须合法。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "          uuid: 11111111-1111-4111-8111-111111111111\n",
            "          uuid: bad-uuid\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="uuid must be a valid UUID"):
        load_stack(stack_path)


def test_load_stack_rejects_vmess_users_duplicate_user(tmp_path: Path) -> None:
    """验证同一 vmess inbound 内 users.user 不能重复。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      users:\n"
            "        - user: alice\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n"
            "          remark: edge vmess\n",
            "      users:\n"
            "        - user: alice\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n"
            "        - user: alice\n"
            "          uuid: 22222222-2222-4222-8222-222222222222\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="duplicate vmess user: alice"):
        load_stack(stack_path)


def test_load_stack_rejects_vmess_users_duplicate_uuid(tmp_path: Path) -> None:
    """验证同一 vmess inbound 内 users.uuid 不能重复。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      users:\n"
            "        - user: alice\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n"
            "          remark: edge vmess\n",
            "      users:\n"
            "        - user: alice\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n"
            "        - user: bob\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="duplicate vmess uuid: 11111111-1111-4111-8111-111111111111"):
        load_stack(stack_path)


def test_load_stack_rejects_vmess_users_duplicate_tag(tmp_path: Path) -> None:
    """验证同一 vmess inbound 内 users.tag 不能重复。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      users:\n"
            "        - user: alice\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n"
            "          remark: edge vmess\n",
            "      users:\n"
            "        - user: alice\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n"
            "          tag: shared-vmess\n"
            "        - user: bob\n"
            "          uuid: 22222222-2222-4222-8222-222222222222\n"
            "          tag: shared-vmess\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="duplicate vmess user tag: shared-vmess"):
        load_stack(stack_path)


def test_load_stack_rejects_vmess_users_generated_tag_collision(tmp_path: Path) -> None:
    """验证 vmess users 的最终订阅 tag 不能与显式 tag 冲突。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      users:\n"
            "        - user: alice\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n"
            "          remark: edge vmess\n",
            "      tag: shared-vmess\n"
            "      users:\n"
            "        - user: alice\n"
            "          uuid: 11111111-1111-4111-8111-111111111111\n"
            "        - user: bob\n"
            "          uuid: 22222222-2222-4222-8222-222222222222\n"
            "          tag: shared-vmess:alice\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="duplicate vmess user tag: shared-vmess:alice"):
        load_stack(stack_path)


def test_load_stack_rejects_vmess_top_level_uuid(tmp_path: Path) -> None:
    """验证 vmess inbound 不再支持顶层 uuid。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      network: raw\n",
            "      network: raw\n"
            "      uuid: 22222222-2222-4222-8222-222222222222\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="uuid is not supported for vmess inbound; use users instead"):
        load_stack(stack_path)


def test_load_stack_rejects_vmess_top_level_user_and_remark(tmp_path: Path) -> None:
    """验证 vmess inbound 的 user 和 remark 必须写在 users 中。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      sub: true\n",
            "      sub: true\n"
            "      user: alice\n"
            "      remark: edge vmess\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="user and remark must be configured under vmess users"):
        load_stack(stack_path)


def test_load_stack_accepts_shadowsocks_users(tmp_path: Path) -> None:
    """验证 shadowsocks inbound 可以使用 users 多用户结构。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      sub: false\n    - name: vmess\n",
            "      sub: false\n"
            "    - name: ss\n"
            "      protocol: shadowsocks\n"
            "      listen: 0.0.0.0\n"
            "      port: 24002\n"
            "      method: aes-256-gcm\n"
            "      password: server-pass\n"
            "      sub: true\n"
            "      users:\n"
            "        - user: alice\n"
            "          password: alice-pass\n"
            "          method: aes-128-gcm\n"
            "          email: alice@example.com\n"
            "        - user: bob\n"
            "          password: bob-pass\n"
            "    - name: vmess\n",
        ),
        encoding="utf-8",
    )

    stack = load_stack(stack_path)

    inbound = stack.xrelay.inbounds[1]
    assert [shadowsocks_user.user for shadowsocks_user in inbound.users] == ["alice", "bob"]
    assert inbound.users[0].email == "alice@example.com"


def test_load_stack_accepts_shadowsocks_2022_users(tmp_path: Path) -> None:
    """验证 SS2022 inbound 可以使用 users 多用户结构。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      sub: false\n    - name: vmess\n",
            "      sub: false\n"
            "    - name: ss2022\n"
            "      protocol: shadowsocks\n"
            "      listen: 0.0.0.0\n"
            "      port: 24002\n"
            "      method: 2022-blake3-aes-256-gcm\n"
            f"      password: {SS2022_SERVER_KEY}\n"
            "      sub: true\n"
            "      users:\n"
            "        - user: alice\n"
            f"          password: {SS2022_ALICE_KEY}\n"
            "        - user: bob\n"
            f"          password: {SS2022_BOB_KEY}\n"
            "    - name: vmess\n",
        ),
        encoding="utf-8",
    )

    stack = load_stack(stack_path)

    inbound = stack.xrelay.inbounds[1]
    assert [shadowsocks_user.password for shadowsocks_user in inbound.users] == [SS2022_ALICE_KEY, SS2022_BOB_KEY]


def test_load_stack_rejects_shadowsocks_2022_user_method(tmp_path: Path) -> None:
    """验证 SS2022 多用户不能为单个用户单独设置 method。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      sub: false\n    - name: vmess\n",
            "      sub: false\n"
            "    - name: ss2022\n"
            "      protocol: shadowsocks\n"
            "      listen: 0.0.0.0\n"
            "      port: 24002\n"
            "      method: 2022-blake3-aes-256-gcm\n"
            f"      password: {SS2022_SERVER_KEY}\n"
            "      sub: true\n"
            "      users:\n"
            "        - user: alice\n"
            f"          password: {SS2022_ALICE_KEY}\n"
            "          method: aes-256-gcm\n"
            "    - name: vmess\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="shadowsocks 2022 users must not set method or cipher"):
        load_stack(stack_path)


def test_load_stack_rejects_shadowsocks_user_missing_password(tmp_path: Path) -> None:
    """验证 shadowsocks users 中每个用户都必须配置 password。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      sub: false\n    - name: vmess\n",
            "      sub: false\n"
            "    - name: ss\n"
            "      protocol: shadowsocks\n"
            "      listen: 0.0.0.0\n"
            "      port: 24002\n"
            "      method: aes-256-gcm\n"
            "      password: server-pass\n"
            "      sub: true\n"
            "      users:\n"
            "        - user: alice\n"
            "    - name: vmess\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="password is required for shadowsocks user"):
        load_stack(stack_path)


def test_load_stack_rejects_socks_users_even_when_empty(tmp_path: Path) -> None:
    """验证 socks/http inbound 不能显式配置 users 字段。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace(
            "      sub: false\n    - name: vmess\n",
            "      sub: false\n"
            "      users: []\n"
            "    - name: vmess\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="users is only supported for vmess or shadowsocks inbound"):
        load_stack(stack_path)


def test_load_stack_accepts_short_xrelay_socks5_ref(tmp_path: Path) -> None:
    """验证 xrelay-socks5 使用 `<stack>.<inbound_name>` 简写 ref。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(stack_with_xrelay_socks5_ref("edge", "edge.relay"), encoding="utf-8")

    stack = load_stack(stack_path)

    assert stack.clash.upstreams[0].ref == "edge.relay"


def test_load_stack_rejects_verbose_xrelay_socks5_ref(tmp_path: Path) -> None:
    """验证 xrelay-socks5 不再接受旧的四段 ref。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(stack_with_xrelay_socks5_ref("edge", "edge.xrelay.socks5.relay"), encoding="utf-8")

    with pytest.raises(ValidationError, match="2 dot-separated segments"):
        load_stack(stack_path)


def test_validate_rejects_public_noauth_socks(tmp_path: Path) -> None:
    """验证非回环 socks/http noauth 默认会失败。"""
    project_dir = write_project(
        tmp_path,
        valid_stack_yaml("edge")
        .replace("listen: 127.0.0.1\n      port: 24001", "listen: 0.0.0.0\n      port: 24001")
        .replace("      auth:\n        type: noauth\n      sub: false", "      auth:\n        type: noauth\n      sub: false"),
    )
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="public socks/http inbound requires password auth"):
        load_stacks(config, check_system_ports=False)


def test_validate_rejects_duplicate_listen_port(tmp_path: Path) -> None:
    """验证本地监听端口全局重复会失败。"""
    project_dir = write_project(
        tmp_path,
        valid_stack_yaml("edge").replace("port: 17091", "port: 24001"),
    )
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="duplicate listen port 24001"):
        load_stacks(config, check_system_ports=False)


def test_validate_rejects_duplicate_xray_api_listen_port(tmp_path: Path) -> None:
    """验证 Xray API 监听端口会参与全局端口冲突校验。"""
    project_dir = write_project(
        tmp_path,
        valid_stack_yaml("edge").replace(
            "xrelay:\n  enabled: true",
            "xrelay:\n  enabled: true\n  api:\n    enabled: true\n    listen: 127.0.0.1:24001",
        ),
    )
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="duplicate listen port 24001"):
        load_stacks(config, check_system_ports=False)


def test_validate_rejects_duplicate_stack_name() -> None:
    """验证跨文件重复 stack name 会失败。"""
    config = load_config(Path("tests/fixtures/example-project/config.yaml"))
    stack = load_stack(Path("tests/fixtures/example-project/stacks/usa1.yaml"))
    stack_set = StackSet(config=config, stacks=[stack, stack.model_copy(deep=True)])

    with pytest.raises(ConfigValidationError, match="duplicate stack name"):
        validate_stack_set(stack_set, check_system_ports=False)


def test_validate_rejects_missing_clash_listener_ref(tmp_path: Path) -> None:
    """验证 xrelay outbound 指向不存在的 clash listener 会失败。"""
    project_dir = write_project(
        tmp_path,
        valid_stack_yaml("edge").replace("edge.clash.socks", "missing.clash.socks"),
    )
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="clash listener ref does not exist"):
        load_stacks(config, check_system_ports=False)


def test_load_stack_rejects_verbose_xrelay_clash_ref(tmp_path: Path) -> None:
    """验证 xrelay clash outbound 不再接受旧的四段 listener ref。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace("edge.clash.socks", "edge.clash.socks.local"),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="3 dot-separated segments"):
        load_stack(stack_path)


def test_validate_rejects_wrong_xrelay_outbound_component(tmp_path: Path) -> None:
    """验证 xrelay outbound type 为 clash 时不能指向其他组件。"""
    project_dir = write_project(
        tmp_path,
        valid_stack_yaml("edge").replace("edge.clash.socks", "edge.xrelay.socks"),
    )
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="must target clash component"):
        load_stacks(config, check_system_ports=False)


def test_validate_rejects_wrong_xrelay_outbound_listener_kind(tmp_path: Path) -> None:
    """验证 xrelay outbound type 为 clash 时必须指向 socks listener。"""
    project_dir = write_project(
        tmp_path,
        valid_stack_yaml("edge").replace("edge.clash.socks", "edge.clash.mixed"),
    )
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="must target socks listener"):
        load_stacks(config, check_system_ports=False)


def test_validate_rejects_enabled_source_to_disabled_clash_target(tmp_path: Path) -> None:
    """验证启用 xrelay 引用禁用 clash 目标会失败。"""
    project_dir = write_project(
        tmp_path,
        valid_stack_yaml("edge").replace("clash:\n  enabled: true", "clash:\n  enabled: false"),
    )
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="clash listener ref does not exist"):
        load_stacks(config, check_system_ports=False)


def test_validate_rejects_enabled_source_to_disabled_xrelay_target(tmp_path: Path) -> None:
    """验证启用 clash 引用禁用 xrelay 目标会失败。"""
    project_dir = write_project_stacks(
        tmp_path,
        {
            "auto": stack_with_xrelay_socks5_ref("auto", "edge.relay"),
            "edge": valid_stack_yaml("edge")
            .replace("xrelay:\n  enabled: true", "xrelay:\n  enabled: false")
            .replace("port: 24001", "port: 24002")
            .replace("port: 24101", "port: 24102")
            .replace("port: 17091", "port: 17092")
            .replace("listen: 127.0.0.1:19091", "listen: 127.0.0.1:19092"),
        },
    )
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="xrelay inbound ref does not exist"):
        load_stacks(config, check_system_ports=False)


def test_validate_rejects_enabled_source_to_disabled_stack_target(tmp_path: Path) -> None:
    """验证启用组件引用禁用 stack 中的目标会失败。"""
    project_dir = write_project_stacks(
        tmp_path,
        {
            "auto": stack_with_xrelay_socks5_ref("auto", "edge.relay"),
            "edge": valid_stack_yaml("edge")
            .replace("enabled: true\nrole: edge", "enabled: false\nrole: edge")
            .replace("port: 24001", "port: 24002")
            .replace("port: 24101", "port: 24102")
            .replace("port: 17091", "port: 17092")
            .replace("listen: 127.0.0.1:19091", "listen: 127.0.0.1:19092"),
        },
    )
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="xrelay inbound ref does not exist"):
        load_stacks(config, check_system_ports=False)


def test_validate_skips_disabled_xrelay_source_ref(tmp_path: Path) -> None:
    """验证禁用 xrelay 组件的 outbound ref 不参与依赖解析。"""
    project_dir = write_project(
        tmp_path,
        valid_stack_yaml("edge")
        .replace("xrelay:\n  enabled: true", "xrelay:\n  enabled: false")
        .replace("edge.clash.socks", "missing.clash.socks"),
    )
    config = load_config(project_dir / "config.yaml")

    stack_set = load_stacks(config, check_system_ports=False)
    graph = build_reference_graph(stack_set)

    assert ServiceNode(stack="edge", component="xrelay") not in graph.nodes


def test_validate_skips_disabled_clash_source_ref(tmp_path: Path) -> None:
    """验证禁用 clash 组件的 upstream ref 不参与依赖解析。"""
    project_dir = write_project(
        tmp_path,
        stack_with_xrelay_socks5_ref("edge", "missing.relay")
        .replace("xrelay:\n  enabled: true", "xrelay:\n  enabled: false")
        .replace("clash:\n  enabled: true", "clash:\n  enabled: false"),
    )
    config = load_config(project_dir / "config.yaml")

    stack_set = load_stacks(config, check_system_ports=False)
    graph = build_reference_graph(stack_set)

    assert graph.nodes == frozenset()


def test_validate_rejects_missing_xrelay_socks5_ref(tmp_path: Path) -> None:
    """验证 clash xrelay-socks5 upstream 指向不存在的 inbound 会失败。"""
    project_dir = write_project(tmp_path, stack_with_xrelay_socks5_ref("edge", "missing.relay"))
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="xrelay inbound ref does not exist"):
        load_stacks(config, check_system_ports=False)


def test_validate_rejects_xrelay_socks5_protocol_mismatch(tmp_path: Path) -> None:
    """验证 xrelay-socks5 upstream 只能指向 socks5 inbound。"""
    project_dir = write_project(tmp_path, stack_with_xrelay_socks5_ref("edge", "edge.vmess"))
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="must target socks5 inbound"):
        load_stacks(config, check_system_ports=False)


def test_validate_rejects_dependency_cycle(tmp_path: Path) -> None:
    """验证 xrelay 与 clash 互相依赖时会报告循环依赖。"""
    project_dir = write_project(tmp_path, stack_with_xrelay_socks5_ref("edge", "edge.relay"))
    config = load_config(project_dir / "config.yaml")

    with pytest.raises(ConfigValidationError, match="dependency cycle detected"):
        load_stacks(config, check_system_ports=False)


def test_port_range_allocates_stably() -> None:
    """验证端口池按从小到大的顺序稳定分配空闲端口。"""
    port_range = PortRange.model_validate("24000-24003")

    assert port_range.allocate({24000, 24002}, count=2) == [24001, 24003]


def test_config_requires_xray_api_range(tmp_path: Path) -> None:
    """验证全局端口池必须显式配置 Xray API 端口范围。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        valid_config_yaml(tmp_path).replace("  xray_api_range: 10001-10999\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="xray_api_range"):
        load_config(config_path)


def test_config_requires_clash_http_range(tmp_path: Path) -> None:
    """验证全局端口池必须显式配置 clash HTTP 端口范围。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        valid_config_yaml(tmp_path).replace("  clash_http: 7201-7301\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="clash_http"):
        load_config(config_path)


def test_config_rejects_removed_subscription_remark_policy(tmp_path: Path) -> None:
    """验证旧订阅命名策略配置不再被接受。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        valid_config_yaml(tmp_path).replace("  source: local\n", "  source: local\n  remark_policy: prefix-source\n"),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="remark_policy"):
        load_config(config_path)


def write_project(tmp_path: Path, stack_yaml: str) -> Path:
    """写入一个最小配置项目，供加载流程测试使用。"""
    return write_project_stacks(tmp_path, {"edge": stack_yaml})


def write_project_stacks(tmp_path: Path, stack_yamls: dict[str, str]) -> Path:
    """写入多个 stack 文件，供跨 stack 引用测试使用。"""
    stacks_dir = tmp_path / "stacks"
    stacks_dir.mkdir()
    (tmp_path / "config.yaml").write_text(valid_config_yaml(tmp_path), encoding="utf-8")
    for stack_name, stack_yaml in stack_yamls.items():
        (stacks_dir / f"{stack_name}.yaml").write_text(stack_yaml, encoding="utf-8")
    return tmp_path


def valid_config_yaml(base_dir: Path) -> str:
    """生成测试用全局配置 YAML。"""
    return f"""version: 1
base_dir: {base_dir}
paths:
  stacks: stacks
external_host: proxy.example.com
subscription:
  source: local
port_ranges:
  xrelay_inbound: 24000-24999
  clash_socks: 7001-7101
  clash_http: 7201-7301
  xray_api_range: 10001-10999
  clash_controller: 19000-19999
"""


def valid_stack_yaml(name: str) -> str:
    """生成测试用合法 stack YAML。"""
    return f"""name: {name}
enabled: true
role: edge
labels: [test]
xrelay:
  enabled: true
  outbound:
    type: clash
    ref: {name}.clash.socks
  inbounds:
    - name: relay
      protocol: socks5
      listen: 127.0.0.1
      port: 24001
      auth:
        type: noauth
      sub: false
    - name: vmess
      protocol: vmess
      listen: 0.0.0.0
      port: 24101
      network: raw
      sub: true
      users:
        - user: alice
          uuid: 11111111-1111-4111-8111-111111111111
          remark: edge vmess
clash:
  enabled: true
  mode: Rule
  controller:
    listen: 127.0.0.1:19091
    secret: demo-secret
  listeners:
    socks:
      - name: local
        listen: 127.0.0.1
        port: 17091
  upstreams:
    - name: server-a
      type: raw
      config:
        type: vmess
        server: server-a.example.com
        port: 443
        uuid: aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa
        network: ws
  groups:
    - name: AllProxy
      type: select
      proxies: [server-a, DIRECT]
  rules:
    profile: default
"""


def stack_with_xrelay_socks5_ref(name: str, ref: str) -> str:
    """生成包含 xrelay-socks5 upstream 的测试 stack YAML。"""
    return valid_stack_yaml(name).replace(
        "  upstreams:\n",
        "  upstreams:\n"
        "    - name: edge-local\n"
        "      type: xrelay-socks5\n"
        f"      ref: {ref}\n",
    ).replace(
        "proxies: [server-a, DIRECT]",
        "proxies: [server-a, edge-local, DIRECT]",
    )
