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


def test_load_config_file_reads_yaml_mapping() -> None:
    """验证示例全局配置可以读取为字典。"""
    config = load_config_file(Path("examples/config.yaml"))

    assert config["version"] == 1
    assert config["base_dir"] == "./examples"


def test_load_config_and_stacks_accept_examples() -> None:
    """验证仓库示例配置可以通过强类型模型和跨 stack 校验。"""
    config = load_config(Path("examples/config.yaml"))
    stack_set = load_stacks(config)

    assert stack_set.stack_names == ["auto", "usa1", "usa2"]
    assert stack_set.by_name()["usa1"].clash.mode == "Rule"


def test_load_config_file_rejects_non_mapping(tmp_path: Path) -> None:
    """验证配置文件顶层不是映射时会失败。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("- invalid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Config file must be a mapping"):
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


def test_load_stack_rejects_missing_vmess_uuid(tmp_path: Path) -> None:
    """验证 vmess inbound 缺少 UUID 会失败。"""
    stack_path = tmp_path / "edge.yaml"
    stack_path.write_text(
        valid_stack_yaml("edge").replace("      uuid: 11111111-1111-4111-8111-111111111111\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="uuid is required for vmess inbound"):
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


def test_validate_rejects_duplicate_stack_name() -> None:
    """验证跨文件重复 stack name 会失败。"""
    config = load_config(Path("examples/config.yaml"))
    stack = load_stack(Path("examples/stacks/usa1.yaml"))
    stack_set = StackSet(config=config, stacks=[stack, stack.model_copy(deep=True)])

    with pytest.raises(ConfigValidationError, match="duplicate stack name"):
        validate_stack_set(stack_set, check_system_ports=False)


def test_port_range_allocates_stably() -> None:
    """验证端口池按从小到大的顺序稳定分配空闲端口。"""
    port_range = PortRange.model_validate("24000-24003")

    assert port_range.allocate({24000, 24002}, count=2) == [24001, 24003]


def write_project(tmp_path: Path, stack_yaml: str) -> Path:
    """写入一个最小配置项目，供加载流程测试使用。"""
    stacks_dir = tmp_path / "stacks"
    stacks_dir.mkdir()
    (tmp_path / "config.yaml").write_text(valid_config_yaml(tmp_path), encoding="utf-8")
    (stacks_dir / "edge.yaml").write_text(stack_yaml, encoding="utf-8")
    return tmp_path


def valid_config_yaml(base_dir: Path) -> str:
    """生成测试用全局配置 YAML。"""
    return f"""version: 1
base_dir: {base_dir}
paths:
  stacks: stacks
external_host: proxy.example.com
subscription:
  access:
    type: token
    token: demo-token
port_ranges:
  xrelay_inbound: 24000-24999
  clash_socks: 17000-17999
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
    ref: {name}.clash.socks.local
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
      uuid: 11111111-1111-4111-8111-111111111111
      network: raw
      sub: true
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
