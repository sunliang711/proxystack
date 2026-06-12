"""CLI 骨架测试。"""

import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import sys
from types import SimpleNamespace
from typing import Optional
from typing import Sequence
from uuid import UUID
from zipfile import ZipFile

from fastapi.testclient import TestClient
from pytest import LogCaptureFixture
from pytest import MonkeyPatch
from ruamel.yaml import YAML
from typer.testing import CliRunner

import proxystack.cli.agent as agent_module
import proxystack.cli.lifecycle as lifecycle_module
import proxystack.cli.sub as sub_module
import proxystack.domain.validation as validation_module
import proxystack.subserver.config as sub_config_module
from proxystack.cli.agent import app as agent_app
from proxystack.cli.sub import app as sub_app
from proxystack.diagnostics.ipinfo import FamilyResult
from proxystack.diagnostics.ipinfo import IpInfoReport
from proxystack.diagnostics.ipinfo import SourceResult
from proxystack.diagnostics.ipinfo import format_ipinfo_report
from proxystack.generator.sub import merge_input_files
from proxystack.generator.sub import write_bundle
from proxystack.systemd import CommandResult
from scripts.build_package import clean_build_state

runner = CliRunner()


class FakeSystemdRunner:
    """记录 CLI 触发的 systemd 命令，避免调用真实 systemctl。"""

    def __init__(
        self,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        active_services: Optional[set[str]] = None,
    ) -> None:
        """初始化 fake runner 输出。"""
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.active_services = active_services
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: Sequence[str]) -> CommandResult:
        """记录参数数组并返回预设结果。"""
        self.calls.append(tuple(args))
        is_active_query = len(args) == 4 and tuple(args[:3]) == ("systemctl", "is-active", "--quiet")
        if is_active_query and self.active_services is not None:
            returncode = 0 if str(args[3]) in self.active_services else 3
            return CommandResult(args=tuple(args), returncode=returncode, stdout=self.stdout, stderr=self.stderr)
        return CommandResult(args=tuple(args), returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def test_agent_help_is_available() -> None:
    """验证 proxystack-agent 帮助可以正常输出。"""
    result = runner.invoke(agent_app, ["--help"])

    assert result.exit_code == 0
    assert "proxystack-agent" in result.output


def test_agent_help_groups_commands_by_panel() -> None:
    """验证 usage 中 commands 列表按用途分组展示。"""
    result = runner.invoke(agent_app, ["--help"])

    assert result.exit_code == 0
    assert "配置管理" in result.output
    assert "安装更新" in result.output
    assert "校验与渲染" in result.output
    assert "服务控制" in result.output
    assert "订阅发布" in result.output
    assert result.output.index("配置管理") < result.output.index("安装更新")
    assert result.output.index("安装更新") < result.output.index("校验与渲染")


def test_agent_lifecycle_command_help_is_available() -> None:
    """验证生命周期命令都提供 help 输出。"""
    commands = [
        ["init"],
        ["setup"],
        ["add"],
        ["config"],
        ["list"],
        ["remove"],
        ["clone"],
        ["export"],
        ["import"],
        ["check"],
        ["start"],
        ["stop"],
        ["restart"],
        ["status"],
        ["logs"],
        ["ipinfo"],
        ["enable"],
        ["disable"],
        ["doctor"],
        ["validate"],
        ["install"],
        ["update"],
        ["service"],
        ["service", "install"],
        ["service", "uninstall"],
        ["service", "enable"],
        ["service", "disable"],
        ["service", "start"],
        ["service", "stop"],
        ["service", "restart"],
        ["service", "status"],
        ["service", "log"],
        ["sub", "export"],
        ["version"],
        ["render"],
        ["render", "model"],
        ["render", "xrelay"],
        ["render", "clash"],
        ["render", "sub"],
    ]

    for command in commands:
        result = runner.invoke(agent_app, [*command, "--help"])

        assert result.exit_code == 0, command

    for removed_command in ["up", "down", "plan", "apply", "edit"]:
        result = runner.invoke(agent_app, [removed_command, "--help"])

        assert result.exit_code != 0, removed_command


def test_agent_version_is_available() -> None:
    """验证 proxystack-agent 版本命令可以正常输出。"""
    result = runner.invoke(agent_app, ["version"])

    assert result.exit_code == 0
    assert "proxystack-agent" in result.output


def test_agent_ipinfo_outputs_report(monkeypatch: MonkeyPatch) -> None:
    """验证 ipinfo 命令会输出指定 stack 的出口 IP 报告。"""
    calls: list[tuple[Path, str, str, float]] = []
    stream_callbacks: list[bool] = []

    def fake_query_ipinfo(
        config: Path,
        name: str,
        family: str,
        timeout: float,
        line_callback=None,
    ) -> IpInfoReport:
        """记录 CLI 入参并返回固定报告，避免测试访问外网。"""
        calls.append((config, name, family, timeout))
        stream_callbacks.append(line_callback is not None)
        report = IpInfoReport(
            stack_name=name,
            proxy_url="socks5://127.0.0.1:17091",
            families=(
                FamilyResult(
                    family="ipv4",
                    label="IPv4",
                    sources=(
                        SourceResult(
                            url="https://ipinfo.io/json",
                            status="ok",
                            ip="198.51.100.10",
                            region="Tokyo / JP",
                            body="",
                            error="",
                        ),
                    ),
                    ip="198.51.100.10",
                    region="Tokyo / JP",
                ),
            ),
        )
        if line_callback is not None:
            for line in format_ipinfo_report(report):
                line_callback(line)
        return report

    monkeypatch.setattr(agent_module, "query_ipinfo", fake_query_ipinfo)

    result = runner.invoke(agent_app, ["ipinfo", "usa1", "--family", "ipv4", "--timeout", "2", "-c", "tests/fixtures/example-project/config.yaml"])

    assert result.exit_code == 0
    assert "Stack: usa1" in result.output
    assert "Proxy: socks5://127.0.0.1:17091" in result.output
    assert "IP: 198.51.100.10" in result.output
    assert calls == [(Path("tests/fixtures/example-project/config.yaml"), "usa1", "ipv4", 2.0)]
    assert stream_callbacks == [True]


def test_agent_validate_examples() -> None:
    """验证 proxystack-agent validate 可以校验示例配置。"""
    result = runner.invoke(agent_app, ["validate", "-c", "tests/fixtures/example-project/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    assert "配置校验通过" in result.output


def test_agent_validate_missing_config_reports_friendly_error(tmp_path: Path) -> None:
    """验证缺失 config 不会向用户暴露 traceback。"""
    result = runner.invoke(agent_app, ["validate", "-c", str(tmp_path / "missing.yaml"), "--skip-system-ports"])

    assert result.exit_code == 1
    assert "Config file could not be read" in result.output
    assert "Traceback" not in result.output


def test_agent_config_missing_stack_reports_friendly_error(tmp_path: Path) -> None:
    """验证缺失 stack 不会向用户暴露 traceback。"""
    config = copy_example_project(tmp_path)

    result = runner.invoke(agent_app, ["config", "missing", "--check-only", "-c", str(config)])

    assert result.exit_code == 1
    assert "file does not exist" in result.output
    assert "missing.yaml" in result.output
    assert "Traceback" not in result.output


def test_cli_subcommands_do_not_print_generic_progress_messages(tmp_path: Path) -> None:
    """验证普通结果型命令不输出泛化过程提示。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_cli_input(input_dir / "manual.yaml")

    validate_result = runner.invoke(agent_app, ["validate", "-c", "tests/fixtures/example-project/config.yaml", "--skip-system-ports"])
    agent_sub_result = runner.invoke(agent_app, ["sub", "validate-inputs", "--input-dir", str(input_dir)])
    sub_result = runner.invoke(sub_app, ["version"])

    assert validate_result.exit_code == 0
    assert "正在执行" not in validate_result.output
    assert agent_sub_result.exit_code == 0
    assert "正在执行" not in agent_sub_result.output
    assert sub_result.exit_code == 0
    assert "正在执行" not in sub_result.output


def test_agent_check_examples() -> None:
    """验证 proxystack-agent check 可以展示依赖和顺序。"""
    result = runner.invoke(agent_app, ["check", "-c", "tests/fixtures/example-project/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    assert "文件变更" in result.output
    assert "依赖服务" in result.output
    assert "建议操作顺序" in result.output
    assert "auto.clash" in result.output
    assert "proxystack-xray@usa1.service" in result.output


def test_agent_render_xrelay_example() -> None:
    """验证 proxystack-agent render xrelay 可以输出 Xray JSON。"""
    result = runner.invoke(agent_app, ["render", "xrelay", "usa1", "-c", "tests/fixtures/example-project/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    rendered_config = json.loads(result.output)
    assert rendered_config["outbounds"][0]["settings"]["servers"][0]["port"] == 17091


def test_agent_render_clash_example() -> None:
    """验证 proxystack-agent render clash 可以输出 mihomo YAML。"""
    result = runner.invoke(agent_app, ["render", "clash", "auto", "-c", "tests/fixtures/example-project/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    rendered_config = YAML(typ="safe").load(result.output)
    assert [proxy["name"] for proxy in rendered_config["proxies"]] == ["usa1-local", "usa2-local"]
    assert rendered_config["proxy-groups"][0]["type"] == "url-test"


def test_agent_render_sub_example() -> None:
    """验证 proxystack-agent render sub 可以输出订阅索引。"""
    result = runner.invoke(agent_app, ["render", "sub", "-c", "tests/fixtures/example-project/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    rendered_index = json.loads(result.output)
    assert "alice" in rendered_index["users"]
    assert "upstreams" not in result.output
    assert rendered_index["access"]["type"] == "token"


def test_agent_render_model_example() -> None:
    """验证 proxystack-agent render model 可以输出解析后的模型 JSON。"""
    result = runner.invoke(agent_app, ["render", "model", "usa1", "-c", "tests/fixtures/example-project/config.yaml", "--skip-system-ports"])

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
    config_data = YAML(typ="safe").load(config.read_text(encoding="utf-8"))
    xrelay_defaults = config_data["defaults"]["xrelay"]
    assert xrelay_defaults["api"]["enabled"] is True
    assert xrelay_defaults["api"]["services"] == ["StatsService"]
    assert xrelay_defaults["stats"]["enabled"] is True
    assert xrelay_defaults["policy"]["enabled"] is True
    assert xrelay_defaults["policy"]["levels"]["0"]["statsUserUplink"] is True
    assert xrelay_defaults["policy"]["system"]["statsInboundUplink"] is True
    assert config_data["base_dir"] == str(project_dir)
    assert config_data["external_host"] == "proxy.test"
    assert config_data["subscription"]["remark_policy"] == "prefix-source"
    assert config_data["install"]["mihomo"]["source"] == "auto"
    assert config_data["install"]["geo"]["source"] == "auto"
    for relative_path in [
        "stacks",
        "runtime",
        "runtime/generated",
        "publish",
        "downloads",
        "sub",
        "sub/inputs",
    ]:
        assert (project_dir / relative_path).is_dir()
    sub_config = YAML(typ="safe").load((project_dir / "sub" / "config.yaml").read_text(encoding="utf-8"))
    assert sub_config["data_dir"] == str(project_dir / "sub")
    assert sub_config["listen"] == "0.0.0.0:3003"
    assert sub_config["access"]["token"] == "demo-subscription-token"


def test_agent_init_falls_back_when_agent_config_template_is_missing(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证包内 agent config 模板缺失时 init 仍使用内置默认配置。"""
    project_dir = tmp_path / "project"
    config = project_dir / "config.yaml"
    monkeypatch.setattr(lifecycle_module, "read_builtin_agent_config_template", lambda: None)

    result = runner.invoke(
        agent_app,
        ["init", "-c", str(config), "--base-dir", str(project_dir), "--external-host", "proxy.test"],
    )

    assert result.exit_code == 0
    config_data = YAML(typ="safe").load(config.read_text(encoding="utf-8"))
    assert config_data["base_dir"] == str(project_dir)
    assert config_data["external_host"] == "proxy.test"
    assert config_data["subscription"]["remark_policy"] == "prefix-source"
    assert config_data["port_ranges"]["xrelay_inbound"] == "24000-24999"


def test_agent_add_uses_template_and_refuses_overwrite(tmp_path: Path) -> None:
    """验证 add 使用模板创建 stack，且不会覆盖已有 stack。"""
    config = init_cli_project(tmp_path)

    result = runner.invoke(agent_app, ["add", "new1", "--keep-template-ports", "--no-edit", "-c", str(config)])
    duplicate = runner.invoke(agent_app, ["add", "new1", "--keep-template-ports", "--no-edit", "-c", str(config)])

    assert result.exit_code == 0
    stack_data = YAML(typ="safe").load((config.parent / "stacks" / "new1.yaml").read_text(encoding="utf-8"))
    assert stack_data["name"] == "new1"
    assert stack_data["xrelay"]["outbound"]["ref"] == "new1.clash.socks"
    assert duplicate.exit_code == 1


def test_agent_add_auto_edits_created_stack(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 add 默认创建后进入安全编辑流程。"""
    config = init_cli_project(tmp_path)
    monkeypatch.setattr(lifecycle_module, "is_port_available", lambda _host, _port: True)

    result = runner.invoke(agent_app, ["add", "new1", "--editor", "true", "-c", str(config)])

    assert result.exit_code == 0
    assert "stack 已创建" in result.output
    assert "编辑校验通过" in result.output
    assert (config.parent / "stacks" / "new1.yaml").exists()


def test_agent_list_outputs_aligned_table(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 list 使用对齐表格展示 stack 摘要。"""
    config = copy_example_project(tmp_path)
    generated_dir = config.parent / "runtime" / "generated"
    (generated_dir / "xray").mkdir(parents=True)
    (generated_dir / "mihomo").mkdir(parents=True)
    (generated_dir / "xray" / "usa1.json").write_text("{}", encoding="utf-8")
    (generated_dir / "mihomo" / "usa1.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(lifecycle_module, "is_service_active", lambda service_name: service_name == "proxystack-xray@usa1.service")

    result = runner.invoke(agent_app, ["list", "-c", str(config)])

    assert result.exit_code == 0
    assert "正在执行 proxystack-agent list" not in result.output
    assert result.output.splitlines()[0].startswith("Name  Running")
    assert "----" in result.output
    assert "Services" in result.output
    assert "xrelay,clash" in result.output
    assert "Generated" in result.output
    assert "Running" in result.output
    assert "xrelay,clash  xrelay" in result.output
    assert "Xrelay Ports" in result.output
    assert "socks5:24001,vmess:24101" in result.output
    assert "alice/socks5:24001" not in result.output


def test_agent_list_skips_system_port_check_by_default(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 list 默认不因运行中的自身端口占用而失败。"""
    config = copy_example_project(tmp_path)
    monkeypatch.setattr(validation_module, "is_port_available", lambda _host, _port: False)

    result = runner.invoke(agent_app, ["list", "-c", str(config)])
    strict_result = runner.invoke(agent_app, ["list", "--check-system-ports", "-c", str(config)])

    assert result.exit_code == 0
    assert "usa1" in result.output
    assert strict_result.exit_code == 1
    assert "listen port" in strict_result.output
    assert "already in use" in strict_result.output


def test_agent_add_allocates_ports_by_default_for_multiple_stacks(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证连续 add 默认自动分配端口，避免模板端口冲突。"""
    config = init_cli_project(tmp_path)
    monkeypatch.setattr(lifecycle_module, "is_port_available", lambda _host, _port: True)

    first = runner.invoke(agent_app, ["add", "usa1", "--no-edit", "-c", str(config)])
    second = runner.invoke(agent_app, ["add", "usa2", "--no-edit", "-c", str(config)])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    usa1 = YAML(typ="safe").load((config.parent / "stacks" / "usa1.yaml").read_text(encoding="utf-8"))
    usa2 = YAML(typ="safe").load((config.parent / "stacks" / "usa2.yaml").read_text(encoding="utf-8"))
    assert [inbound["port"] for inbound in usa1["xrelay"]["inbounds"]] == [4300, 4301]
    assert [inbound["port"] for inbound in usa2["xrelay"]["inbounds"]] == [4302, 4303]
    assert usa1["clash"]["listeners"]["socks"][0]["port"] == 7090
    assert usa2["clash"]["listeners"]["socks"][0]["port"] == 7091
    assert usa1["xrelay"]["api"]["listen"] == "127.0.0.1:19000"
    assert usa1["clash"]["controller"]["listen"] == "127.0.0.1:19001"
    assert usa2["xrelay"]["api"]["listen"] == "127.0.0.1:19002"
    assert usa2["clash"]["controller"]["listen"] == "127.0.0.1:19003"
    usa1_uuid = usa1["xrelay"]["inbounds"][1]["users"][0]["uuid"]
    usa2_uuid = usa2["xrelay"]["inbounds"][1]["users"][0]["uuid"]
    UUID(usa1_uuid)
    UUID(usa2_uuid)
    assert usa1_uuid != lifecycle_module.VMESS_UUID_PLACEHOLDER
    assert usa2_uuid != lifecycle_module.VMESS_UUID_PLACEHOLDER
    assert usa1_uuid != usa2_uuid


def test_agent_clone_allocates_new_ports(tmp_path: Path) -> None:
    """验证 clone --allocate-ports 会为目标 stack 重分配监听端口。"""
    config = copy_example_project(tmp_path)

    result = runner.invoke(agent_app, ["clone", "usa1", "usa3", "--allocate-ports", "-c", str(config)])

    assert result.exit_code == 0
    cloned_stack = YAML(typ="safe").load((config.parent / "stacks" / "usa3.yaml").read_text(encoding="utf-8"))
    source_stack = YAML(typ="safe").load((config.parent / "stacks" / "usa1.yaml").read_text(encoding="utf-8"))
    assert cloned_stack["name"] == "usa3"
    assert cloned_stack["xrelay"]["outbound"]["ref"] == "usa3.clash.socks"
    assert cloned_stack["xrelay"]["inbounds"][0]["port"] != source_stack["xrelay"]["inbounds"][0]["port"]
    assert cloned_stack["clash"]["listeners"]["socks"][0]["port"] != source_stack["clash"]["listeners"]["socks"][0]["port"]


def test_agent_add_allocates_ports_from_config_ranges(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 add 默认会按端口池写回监听端口。"""
    config = init_cli_project(tmp_path)
    monkeypatch.setattr(lifecycle_module, "is_port_available", lambda _host, _port: True)

    result = runner.invoke(agent_app, ["add", "edge", "--no-edit", "-c", str(config)])

    assert result.exit_code == 0
    stack_data = YAML(typ="safe").load((config.parent / "stacks" / "edge.yaml").read_text(encoding="utf-8"))
    inbound_ports = [inbound["port"] for inbound in stack_data["xrelay"]["inbounds"]]
    assert inbound_ports == [4300, 4301]
    assert stack_data["clash"]["listeners"]["socks"][0]["port"] == 7090
    assert stack_data["xrelay"]["api"]["listen"] == "127.0.0.1:19000"
    assert stack_data["clash"]["controller"]["listen"] == "127.0.0.1:19001"


def test_agent_add_auto_template_without_members_creates_disabled_draft(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证无 members 的 auto 模板作为禁用草稿创建，避免占位 ref 阻断首次添加。"""
    config = init_cli_project(tmp_path)
    monkeypatch.setattr(lifecycle_module, "is_port_available", lambda _host, _port: True)

    result = runner.invoke(agent_app, ["add", "auto", "--template", "auto-url-test", "--no-edit", "-c", str(config)])
    validate_result = runner.invoke(agent_app, ["validate", "-c", str(config), "--skip-system-ports"])

    assert result.exit_code == 0, result.output
    stack_data = YAML(typ="safe").load((config.parent / "stacks" / "auto.yaml").read_text(encoding="utf-8"))
    assert stack_data["enabled"] is False
    assert [upstream["ref"] for upstream in stack_data["clash"]["upstreams"]] == ["usa1.relay", "usa2.relay"]
    assert validate_result.exit_code == 0, validate_result.output


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

    result = runner.invoke(agent_app, ["add", "auto", "--template", "auto-url-test", "--members", "missing", "--no-edit", "-c", str(config)])

    assert result.exit_code == 1
    assert "ref does not exist" in result.output
    assert not (config.parent / "stacks" / "auto.yaml").exists()


def test_agent_check_does_not_write_runtime_files(tmp_path: Path) -> None:
    """验证 check 只展示文件变化，不写入运行目录文件。"""
    config = copy_example_project(tmp_path)
    generated_dir = config.parent / "runtime" / "generated"

    result = runner.invoke(agent_app, ["check", "-c", str(config), "--skip-system-ports"])

    assert result.exit_code == 0
    assert "文件变更" in result.output
    assert not generated_dir.exists()


def test_agent_start_is_idempotent(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 start 第二次执行不会改写未变化文件。"""
    config = copy_example_project(tmp_path)
    use_fake_systemd(monkeypatch, tmp_path)
    manifest = config.parent / "runtime" / "generated" / "manifest.json"

    first = runner.invoke(agent_app, ["start", "-c", str(config)])
    os.utime(manifest, (1000, 1000))
    second = runner.invoke(agent_app, ["start", "-c", str(config)])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert manifest.stat().st_mtime_ns == 1_000_000_000_000


def test_agent_add_sets_managed_stack_metadata_as_root(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 root 新增 stack 时会修正为服务用户可读的托管权限。"""
    config = init_cli_project(tmp_path)
    chown_calls = use_fake_root_managed_owner(monkeypatch)

    result = runner.invoke(agent_app, ["add", "owned", "--no-edit", "-c", str(config)])

    stack_path = config.parent / "stacks" / "owned.yaml"
    assert result.exit_code == 0
    assert stack_path.exists()
    assert stack_path.stat().st_mode & 0o777 == 0o640
    assert (stack_path, 123, 456) in chown_calls


def test_agent_start_repairs_unchanged_generated_metadata_as_root(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 start 内容未变化时仍会修复生成文件权限且保持 mtime 幂等。"""
    config = copy_example_project(tmp_path)
    use_fake_systemd(monkeypatch, tmp_path)
    chown_calls = use_fake_root_managed_owner(monkeypatch)
    manifest = config.parent / "runtime" / "generated" / "manifest.json"
    generated_file = config.parent / "runtime" / "generated" / "xray" / "usa1.json"
    stack_file = config.parent / "stacks" / "usa1.yaml"

    first = runner.invoke(agent_app, ["start", "-c", str(config)])
    os.utime(manifest, (1000, 1000))
    chown_calls.clear()
    second = runner.invoke(agent_app, ["start", "-c", str(config)])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert manifest.stat().st_mtime_ns == 1_000_000_000_000
    assert generated_file.stat().st_mode & 0o777 == 0o640
    assert stack_file.stat().st_mode & 0o777 == 0o640
    assert (stack_file, 123, 456) in chown_calls
    assert (generated_file, 123, 456) in chown_calls
    assert (manifest, 123, 456) in chown_calls


def test_agent_start_applies_changed_target_services_with_step_logs(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 start 写入生成文件，并用动作状态替代 systemd 内部输出。"""
    config = copy_example_project(tmp_path)
    fake_runner = use_fake_systemd(monkeypatch, tmp_path)

    first = runner.invoke(agent_app, ["start", "xrelay/usa1", "-c", str(config)])
    second = runner.invoke(agent_app, ["start", "xrelay/usa1", "-c", str(config)])

    assert first.exit_code == 0
    assert "restart changed services .. done" in first.output
    assert "restart: proxystack-xray@usa1.service" not in first.output
    assert "proxystack-clash@usa1.service" not in first.output
    assert (config.parent / "runtime" / "generated" / "xray" / "usa1.json").exists()
    assert second.exit_code == 0
    assert "start selected services .. done" in second.output
    assert "start: proxystack-xray@usa1.service" not in second.output
    assert fake_runner.calls == [
        ("systemctl", "restart", "proxystack-xray@usa1.service"),
        ("systemctl", "start", "proxystack-xray@usa1.service"),
    ]


def test_agent_start_rejects_missing_proxy_binary_before_systemd(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 start 在代理核心缺失时不写生成文件、不调用 systemd。"""
    config = copy_example_project(tmp_path)
    (config.parent / "bin" / "xray").unlink()
    fake_runner = use_fake_systemd(monkeypatch, tmp_path)

    result = runner.invoke(agent_app, ["start", "xrelay/usa1", "-c", str(config)])

    assert result.exit_code == 1
    assert "代理核心未安装或不可执行" in result.output
    assert "xray: missing" in result.output
    assert "ps-agent install all" in result.output
    assert fake_runner.calls == []
    assert not (config.parent / "runtime" / "generated" / "xray" / "usa1.json").exists()


def test_agent_start_reports_install_hint_when_unit_is_missing(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 start 遇到 systemd unit 缺失时提示先安装 unit。"""
    config = copy_example_project(tmp_path)
    fake_runner = FakeSystemdRunner(
        returncode=5,
        stderr="Failed to restart proxystack-clash@usa1.service: Unit proxystack-clash@usa1.service not found.\n",
    )
    monkeypatch.setattr(agent_module, "SYSTEMD_RUNNER", fake_runner)
    monkeypatch.setattr(agent_module, "SYSTEMD_UNIT_DIR_OVERRIDE", tmp_path / "systemd")

    result = runner.invoke(agent_app, ["start", "usa1", "-c", str(config)])

    assert result.exit_code == 1
    assert "systemd unit 未安装，请先执行" in result.output
    assert f"ps-agent service install usa1 -c {config}" in result.output
    assert fake_runner.calls == [("systemctl", "restart", "proxystack-clash@usa1.service")]


def test_agent_service_target_selection(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 service 分组支持组件和 sub 目标选择。"""
    fake_runner = use_fake_systemd(monkeypatch, tmp_path)
    status_result = runner.invoke(agent_app, ["service", "status", "clash/usa1", "-c", "tests/fixtures/example-project/config.yaml"])
    logs_result = runner.invoke(agent_app, ["service", "log", "sub", "--follow", "-c", "tests/fixtures/example-project/config.yaml"])

    assert status_result.exit_code == 0
    assert "status: proxystack-clash@usa1.service" in status_result.output
    assert "proxystack-xray@usa1.service" not in status_result.output
    assert logs_result.exit_code == 0
    assert "log: proxystack-sub.service" in logs_result.output
    assert fake_runner.calls == [
        ("systemctl", "status", "proxystack-clash@usa1.service"),
        ("journalctl", "-u", "proxystack-sub.service", "--no-pager", "-n", "100", "-f"),
    ]


def test_agent_service_log_pair_follow_uses_single_journalctl_call(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 service log 对实例对 follow 时一次订阅两个 unit。"""
    fake_runner = use_fake_systemd(monkeypatch, tmp_path)

    result = runner.invoke(agent_app, ["service", "log", "usa1", "--follow", "-c", "tests/fixtures/example-project/config.yaml"])

    assert result.exit_code == 0
    assert "log: proxystack-xray@usa1.service" in result.output
    assert "log: proxystack-clash@usa1.service" in result.output
    assert fake_runner.calls == [
        (
            "journalctl",
            "-u",
            "proxystack-clash@usa1.service",
            "-u",
            "proxystack-xray@usa1.service",
            "--no-pager",
            "-n",
            "100",
            "-f",
        )
    ]


def test_agent_logs_stack_follow_uses_single_journalctl_call(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证顶层 logs 对 stack follow 时一次订阅 mihomo 和 xray 两个 unit。"""
    fake_runner = use_fake_systemd(monkeypatch, tmp_path)

    result = runner.invoke(agent_app, ["logs", "usa1", "--follow", "-c", "tests/fixtures/example-project/config.yaml"])

    assert result.exit_code == 0
    assert "log: proxystack-clash@usa1.service" in result.output
    assert "log: proxystack-xray@usa1.service" in result.output
    assert fake_runner.calls == [
        (
            "journalctl",
            "-u",
            "proxystack-clash@usa1.service",
            "-u",
            "proxystack-xray@usa1.service",
            "--no-pager",
            "-n",
            "100",
            "-f",
        )
    ]


def test_agent_service_commands_skip_system_port_occupancy_by_default(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证服务命令默认不会因服务自身端口已占用而失败。"""
    use_fake_systemd(monkeypatch, tmp_path)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            sock.bind(("0.0.0.0", 24001))
            sock.listen()
        except OSError:
            pass
        result = runner.invoke(agent_app, ["status", "usa1", "-c", "tests/fixtures/example-project/config.yaml"])
    finally:
        sock.close()

    assert result.exit_code == 0
    assert "status: proxystack-xray@usa1.service" in result.output


def test_agent_service_install_uninstall_uses_fake_unit_dir(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 service install/uninstall 写删 fake unit_dir 且保留配置和 stack。"""
    config = copy_example_project(tmp_path)
    fake_runner = use_fake_systemd(monkeypatch, tmp_path)
    unit_dir = tmp_path / "systemd"

    install_result = runner.invoke(agent_app, ["service", "install", "sub", "-c", str(config)])
    assert install_result.exit_code == 0
    assert (unit_dir / "proxystack-sub.service").exists()

    uninstall_result = runner.invoke(agent_app, ["service", "uninstall", "sub", "-c", str(config)])

    assert uninstall_result.exit_code == 0
    assert not (unit_dir / "proxystack-sub.service").exists()
    assert config.exists()
    assert (config.parent / "stacks" / "usa1.yaml").exists()
    assert fake_runner.calls == [("systemctl", "daemon-reload"), ("systemctl", "daemon-reload")]


def test_agent_top_level_wrappers_call_fake_runner(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证顶层服务包装命令调用 fake systemd runner。"""
    config = copy_example_project(tmp_path)
    fake_runner = use_fake_systemd(monkeypatch, tmp_path)
    commands = [
        (["stop", "xrelay/usa1"], ("systemctl", "stop", "proxystack-xray@usa1.service")),
        (["restart", "xrelay/usa1"], ("systemctl", "restart", "proxystack-xray@usa1.service")),
        (["enable", "xrelay/usa1"], ("systemctl", "enable", "proxystack-xray@usa1.service")),
        (["disable", "xrelay/usa1"], ("systemctl", "disable", "proxystack-xray@usa1.service")),
        (["status", "xrelay/usa1"], ("systemctl", "status", "proxystack-xray@usa1.service")),
        (["logs", "xrelay/usa1"], ("journalctl", "-u", "proxystack-xray@usa1.service", "--no-pager", "-n", "100")),
    ]

    for command, _ in commands:
        result = runner.invoke(agent_app, [*command, "-c", str(config)])

        assert result.exit_code == 0, command

    assert fake_runner.calls == [expected for _, expected in commands]


def test_agent_start_sub_only_starts_sub_without_reading_stack(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 start sub 不读取 stack、不创建 runtime/generated，只影响 sub 服务。"""
    config = write_cli_config_without_valid_stacks(tmp_path)
    fake_runner = use_fake_systemd(monkeypatch, tmp_path)

    result = runner.invoke(agent_app, ["start", "sub", "-c", str(config)])

    assert result.exit_code == 0
    assert "start subscription service .. done" in result.output
    assert "start: proxystack-sub.service" not in result.output
    assert fake_runner.calls == [("systemctl", "start", "proxystack-sub.service")]
    assert not (config.parent / "runtime" / "generated").exists()


def test_install_update_group_has_no_unit_install_entry(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 install/update 分组没有 systemd unit 安装入口。"""
    use_fake_systemd(monkeypatch, tmp_path)

    install_help = runner.invoke(agent_app, ["install", "--help"])
    update_help = runner.invoke(agent_app, ["update", "--help"])
    invalid_install = runner.invoke(agent_app, ["install", "service", "install"])
    invalid_update = runner.invoke(agent_app, ["update", "service", "install"])

    assert install_help.exit_code == 0
    assert update_help.exit_code == 0
    assert "service install" not in install_help.output
    assert "service install" not in update_help.output
    assert invalid_install.exit_code != 0
    assert invalid_update.exit_code != 0


def test_agent_setup_initializes_runtime_and_units(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 setup 串联 init、install all 和 service install。"""
    project_dir = tmp_path / "project"
    config = project_dir / "config.yaml"
    fake_runner = use_fake_systemd(monkeypatch, tmp_path)
    installed_targets: list[str] = []

    def fake_install_artifact(global_config, request, operation: str = "install", progress=None):
        """记录 setup 安装目标，避免测试访问真实下载源。"""
        installed_targets.append(request.target)
        if request.target == "geo":
            installed_path = global_config.resolve_path(global_config.paths.geo) / "geoip.metadb"
        else:
            installed_path = global_config.resolve_path(global_config.paths.bin) / request.target
        installed_path.parent.mkdir(parents=True, exist_ok=True)
        installed_path.write_text("fake", encoding="utf-8")
        return agent_module.InstallResult(
            operation=operation,
            target=request.target,
            version=request.version,
            source=request.source,
            source_sha256="fake-sha256",
            installed_paths=(installed_path,),
            service_plan=tuple(),
        )

    monkeypatch.setattr(agent_module, "install_artifact", fake_install_artifact)

    result = runner.invoke(agent_app, ["setup", "-c", str(config), "--base-dir", str(project_dir)])

    assert result.exit_code == 0, result.output
    assert config.exists()
    assert installed_targets == ["mihomo", "xray", "geo"]
    assert (tmp_path / "systemd" / "proxystack-xray@.service").exists()
    assert (tmp_path / "systemd" / "proxystack-clash@.service").exists()
    assert (tmp_path / "systemd" / "proxystack-sub.service").exists()
    assert fake_runner.calls == [("systemctl", "daemon-reload")]
    assert "initialize project .. done" in result.output
    assert "install mihomo .. done" in result.output
    assert "install systemd units .. done" in result.output


def test_agent_config_rejects_invalid_stack_before_replacing(tmp_path: Path) -> None:
    """验证 config 编辑 stack 保存前会做全局校验，失败时不替换原 stack。"""
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
path.write_text(text.replace("usa1.clash.socks", "missing.clash.socks"), encoding="utf-8")
""".lstrip(),
        encoding="utf-8",
    )

    result = runner.invoke(agent_app, ["config", "usa1", "--editor", f"{sys.executable} {editor}", "-c", str(config)])

    assert result.exit_code == 1
    assert "ref does not exist" in result.output
    assert stack_path.read_text(encoding="utf-8") == original_text


def test_agent_config_unchanged_stack_does_not_restart(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 config 编辑后内容未变化时，不探测或重启 systemd 服务。"""
    config = copy_example_project(tmp_path)
    fake_runner = FakeSystemdRunner(
        active_services={
            "proxystack-clash@usa1.service",
            "proxystack-xray@usa1.service",
        }
    )
    monkeypatch.setattr(agent_module, "SYSTEMD_RUNNER", fake_runner)
    monkeypatch.setattr(agent_module, "SYSTEMD_UNIT_DIR_OVERRIDE", tmp_path / "systemd")

    result = runner.invoke(agent_app, ["config", "usa1", "--editor", "true", "-c", str(config)])

    assert result.exit_code == 0, result.output
    assert fake_runner.calls == []
    assert "编辑校验通过" in result.output


def test_agent_config_restarts_active_stack_after_change(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 config 修改运行中 stack 后，会重新生成配置并重启 active 组件。"""
    config = copy_example_project(tmp_path)
    fake_runner = FakeSystemdRunner(
        active_services={
            "proxystack-clash@usa1.service",
            "proxystack-xray@usa1.service",
        }
    )
    monkeypatch.setattr(agent_module, "SYSTEMD_RUNNER", fake_runner)
    monkeypatch.setattr(agent_module, "SYSTEMD_UNIT_DIR_OVERRIDE", tmp_path / "systemd")
    editor = tmp_path / "mode_editor.py"
    editor.write_text(
        """
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
path.write_text(text.replace("mode: Rule", "mode: Global"), encoding="utf-8")
""".lstrip(),
        encoding="utf-8",
    )

    result = runner.invoke(agent_app, ["config", "usa1", "--editor", f"{sys.executable} {editor}", "-c", str(config)])

    assert result.exit_code == 0, result.output
    assert "detect running stack services .. done" in result.output
    assert "write runtime files .. done" in result.output
    assert "restart running stack services .. done" in result.output
    assert (config.parent / "runtime" / "generated" / "xray" / "usa1.json").exists()
    clash_path = config.parent / "runtime" / "generated" / "mihomo" / "usa1.yaml"
    rendered_clash = YAML(typ="safe").load(clash_path.read_text(encoding="utf-8"))
    assert rendered_clash["mode"] == "Global"
    assert fake_runner.calls == [
        ("systemctl", "is-active", "--quiet", "proxystack-clash@usa1.service"),
        ("systemctl", "is-active", "--quiet", "proxystack-xray@usa1.service"),
        ("systemctl", "restart", "proxystack-clash@usa1.service"),
        ("systemctl", "restart", "proxystack-xray@usa1.service"),
    ]


def test_agent_remove_purge_deletes_generated_files(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 remove --purge 删除 stack 文件和 manifest 中对应生成文件。"""
    config = copy_example_project(tmp_path)
    use_fake_systemd(monkeypatch, tmp_path)
    start_result = runner.invoke(agent_app, ["start", "usa1", "-c", str(config)])

    result = runner.invoke(agent_app, ["remove", "usa1", "--purge", "-c", str(config)])

    assert start_result.exit_code == 0
    assert result.exit_code == 0
    assert not (config.parent / "stacks" / "usa1.yaml").exists()
    assert not (config.parent / "runtime" / "generated" / "xray" / "usa1.json").exists()
    assert not (config.parent / "runtime" / "generated" / "mihomo" / "usa1.yaml").exists()
    manifest = json.loads((config.parent / "runtime" / "generated" / "manifest.json").read_text(encoding="utf-8"))
    assert "xray/usa1.json" not in manifest["files"]
    assert "mihomo/usa1.yaml" not in manifest["files"]


def test_agent_check_config_check_only_and_doctor(tmp_path: Path) -> None:
    """验证 check、config --check-only 和 doctor 的基础输出。"""
    config = copy_example_project(tmp_path)

    check_result = runner.invoke(agent_app, ["check", "usa1", "-c", str(config), "--skip-system-ports"])
    stack_config_result = runner.invoke(agent_app, ["config", "usa1", "--check-only", "-c", str(config)])
    config_result = runner.invoke(agent_app, ["config", "--check-only", "-c", str(config)])
    doctor_result = runner.invoke(agent_app, ["doctor", "-c", str(config)])

    assert check_result.exit_code == 0
    assert "配置校验通过" in check_result.output
    assert stack_config_result.exit_code == 0
    assert "编辑校验通过" in stack_config_result.output
    assert config_result.exit_code == 0
    assert f"编辑校验通过：{config}" in config_result.output
    assert doctor_result.exit_code == 0
    assert "Directories:" in doctor_result.output
    assert "Binaries:" in doctor_result.output
    assert "Systemd units:" in doctor_result.output
    assert "Ports:" in doctor_result.output
    assert "subscription.listen" in doctor_result.output


def test_agent_sub_export_all_stacks_bundle(tmp_path: Path) -> None:
    """验证 proxystack-agent sub export 可以按 stack 写出发布包。"""
    output = tmp_path / "sub-bundle.zip"

    result = runner.invoke(
        agent_app,
        ["sub", "export", "-o", str(output), "-c", "tests/fixtures/example-project/config.yaml"],
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
        auto_input = YAML(typ="safe").load(zip_file.read("inputs/auto.yaml").decode("utf-8"))
    assert manifest["bundle_schema"] == "proxystack.sub-bundle"
    assert manifest["bundle_version"] == 1
    assert sorted(manifest["inputs_sha256"]) == ["auto.yaml", "usa1.yaml", "usa2.yaml"]
    assert manifest["access"] == {"type": "none"}
    assert auto_input["source"] == "auto"
    assert auto_input["nodes"][0]["id"] == "auto:relay"


def test_agent_sub_export_stack_bundle(tmp_path: Path) -> None:
    """验证 sub export 指定 stack 时只导出该 stack。"""
    output = tmp_path / "usa1-sub-bundle.zip"

    result = runner.invoke(
        agent_app,
        ["sub", "export", "usa1", "-o", str(output), "-c", "tests/fixtures/example-project/config.yaml"],
    )

    assert result.exit_code == 0
    with ZipFile(output) as zip_file:
        assert sorted(zip_file.namelist()) == ["inputs/usa1.yaml", "manifest.json"]
        manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
        bundled_input = YAML(typ="safe").load(zip_file.read("inputs/usa1.yaml").decode("utf-8"))
    assert manifest["source"] == "usa1"
    assert bundled_input["source"] == "usa1"
    assert [node["id"] for node in bundled_input["nodes"]] == ["usa1:relay", "usa1:vmess:alice"]


def test_agent_sub_export_rejects_missing_stack(tmp_path: Path) -> None:
    """验证 sub export 指定不存在 stack 时失败。"""
    output = tmp_path / "missing-sub-bundle.zip"

    result = runner.invoke(
        agent_app,
        ["sub", "export", "missing", "-o", str(output), "-c", "tests/fixtures/example-project/config.yaml"],
    )

    assert result.exit_code == 1
    assert "stack does not exist: missing" in result.output


def test_agent_sub_export_skips_running_service_ports_by_default(tmp_path: Path) -> None:
    """验证 sub export 不会因自身服务端口已被监听而失败。"""
    config = copy_example_project(tmp_path)
    stack_path = config.parent / "stacks" / "usa1.yaml"
    yaml = YAML()
    stack_data = yaml.load(stack_path.read_text(encoding="utf-8"))
    output = tmp_path / "usa1-sub-bundle.zip"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", 0))
        sock.listen()
        stack_data["xrelay"]["inbounds"][0]["port"] = sock.getsockname()[1]
        with stack_path.open("w", encoding="utf-8") as stack_file:
            yaml.dump(stack_data, stack_file)

        result = runner.invoke(agent_app, ["sub", "export", "usa1", "-o", str(output), "-c", str(config)])
    finally:
        sock.close()

    assert result.exit_code == 0
    assert output.exists()


def test_agent_sub_validate_inputs(tmp_path: Path) -> None:
    """验证 proxystack-agent sub validate-inputs 可以校验 inputs 目录。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_cli_input(input_dir / "manual.yaml")

    result = runner.invoke(agent_app, ["sub", "validate-inputs", "--input-dir", str(input_dir)])

    assert result.exit_code == 0
    assert "订阅 inputs 校验通过" in result.output


def test_agent_sub_export_default_output_for_stack(tmp_path: Path) -> None:
    """验证 sub export 指定 stack 时默认输出到 stack 专属发布包。"""
    config = copy_example_project(tmp_path)
    output = config.parent / "publish" / "usa1-sub-bundle.zip"

    result = runner.invoke(agent_app, ["sub", "export", "usa1", "-c", str(config)])

    assert result.exit_code == 0
    assert output.exists()


def test_agent_sub_export_sets_managed_bundle_metadata_as_root(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 root 导出订阅包时会修正 zip 文件权限和 owner。"""
    output = tmp_path / "sub-bundle.zip"
    chown_calls = use_fake_root_managed_owner(monkeypatch)

    result = runner.invoke(
        agent_app,
        ["sub", "export", "-o", str(output), "-c", "tests/fixtures/example-project/config.yaml"],
    )

    assert result.exit_code == 0
    assert output.stat().st_mode & 0o777 == 0o640
    assert (output, 123, 456) in chown_calls


def test_agent_sub_export_bundle_schema(tmp_path: Path) -> None:
    """验证 sub export 生成的发布包包含 schema 和 input 元数据。"""
    output = tmp_path / "sub-bundle.zip"

    result = runner.invoke(agent_app, ["sub", "export", "usa1", "-o", str(output), "-c", "tests/fixtures/example-project/config.yaml"])

    assert result.exit_code == 0
    with ZipFile(output) as zip_file:
        assert sorted(zip_file.namelist()) == ["inputs/usa1.yaml", "manifest.json"]
        manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
        bundled_input = YAML(typ="safe").load(zip_file.read("inputs/usa1.yaml").decode("utf-8"))
    assert manifest["bundle_schema"] == "proxystack.sub-bundle"
    assert manifest["bundle_version"] == 1
    assert "usa1.yaml" in manifest["inputs_sha256"]
    assert bundled_input["input_schema"] == "proxystack.subscription-input"


def test_agent_native_backup_export_import_roundtrip(tmp_path: Path) -> None:
    """验证原生备份包只携带 config/stacks，并可导入到新的 base_dir。"""
    source_config = copy_example_project(tmp_path / "source")
    runtime_dir = source_config.parent / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "manifest.json").write_text("{}", encoding="utf-8")
    backup = tmp_path / "proxystack-backup.zip"

    export_result = runner.invoke(agent_app, ["export", "-o", str(backup), "-c", str(source_config)])

    assert export_result.exit_code == 0
    with ZipFile(backup) as zip_file:
        names = sorted(zip_file.namelist())
        manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
    assert "runtime/manifest.json" not in names
    assert names == [
        "config/config.yaml",
        "manifest.json",
        "stacks/auto.yaml",
        "stacks/usa1.yaml",
        "stacks/usa2.yaml",
    ]
    assert manifest["backup_schema"] == "proxystack.native-backup"
    assert "config/config.yaml" in manifest["files_sha256"]

    target_config = tmp_path / "target" / "config.yaml"
    import_result = runner.invoke(agent_app, ["import", str(backup), "-c", str(target_config)])

    assert import_result.exit_code == 0
    imported_config = YAML(typ="safe").load(target_config.read_text(encoding="utf-8"))
    assert imported_config["base_dir"] == str(target_config.parent)
    assert (target_config.parent / "stacks" / "usa1.yaml").exists()
    assert not (target_config.parent / "runtime" / "manifest.json").exists()
    validate_result = runner.invoke(agent_app, ["validate", "-c", str(target_config), "--skip-system-ports"])
    assert validate_result.exit_code == 0


def test_agent_native_backup_import_refuses_existing_files_without_force(tmp_path: Path) -> None:
    """验证导入原生备份包默认不覆盖目标 agent 既有配置。"""
    source_config = copy_example_project(tmp_path / "source")
    backup = tmp_path / "proxystack-backup.zip"
    export_result = runner.invoke(agent_app, ["export", "-o", str(backup), "-c", str(source_config)])
    assert export_result.exit_code == 0

    result = runner.invoke(agent_app, ["import", str(backup), "-c", str(source_config)])

    assert result.exit_code == 1
    assert "target file already exists" in result.output


def test_agent_native_backup_import_rejects_subscription_bundle(tmp_path: Path) -> None:
    """验证 agent 原生导入拒绝误导入 sub-bundle.zip。"""
    sub_bundle = tmp_path / "sub-bundle.zip"
    export_result = runner.invoke(
        agent_app,
        ["sub", "export", "usa1", "-o", str(sub_bundle), "-c", "tests/fixtures/example-project/config.yaml"],
    )
    assert export_result.exit_code == 0

    result = runner.invoke(agent_app, ["import", str(sub_bundle), "-c", str(tmp_path / "target" / "config.yaml")])

    assert result.exit_code == 1
    assert "unexpected native backup path: inputs/usa1.yaml" in result.output


def test_agent_native_backup_import_rejects_unsafe_member_path(tmp_path: Path) -> None:
    """验证原生备份导入拒绝 zip 路径穿越。"""
    backup = tmp_path / "unsafe-backup.zip"
    with ZipFile(backup, "w") as zip_file:
        zip_file.writestr(
            "manifest.json",
            json.dumps(
                {
                    "backup_schema": "proxystack.native-backup",
                    "backup_version": 1,
                    "created_at": "2026-06-06T12:00:00+08:00",
                    "files_sha256": {"../bad.yaml": "0" * 64},
                }
            ),
        )
        zip_file.writestr("../bad.yaml", "bad")

    result = runner.invoke(agent_app, ["import", str(backup), "-c", str(tmp_path / "target" / "config.yaml")])

    assert result.exit_code == 1
    assert "unsafe native backup path" in result.output


def test_agent_native_backup_import_rejects_hash_mismatch(tmp_path: Path) -> None:
    """验证原生备份导入会校验每个文件的 sha256。"""
    source_config = copy_example_project(tmp_path / "source")
    backup = tmp_path / "proxystack-backup.zip"
    bad_backup = tmp_path / "bad-proxystack-backup.zip"
    export_result = runner.invoke(agent_app, ["export", "-o", str(backup), "-c", str(source_config)])
    assert export_result.exit_code == 0
    with ZipFile(backup) as source_zip:
        names = source_zip.namelist()
        member_contents = {name: source_zip.read(name) for name in names if name != "manifest.json"}
        manifest = source_zip.read("manifest.json")
    member_contents["config/config.yaml"] = b"version: 1\n"
    with ZipFile(bad_backup, "w") as zip_file:
        zip_file.writestr("manifest.json", manifest)
        for name, content in member_contents.items():
            zip_file.writestr(name, content)

    result = runner.invoke(agent_app, ["import", str(bad_backup), "-c", str(tmp_path / "target" / "config.yaml")])

    assert result.exit_code == 1
    assert "file hash mismatch: config/config.yaml" in result.output


def test_agent_native_backup_import_rejects_stack_path_outside_base_dir(tmp_path: Path) -> None:
    """验证导入时拒绝备份配置把 stacks 目录指向 base_dir 外部。"""
    outside_stacks = tmp_path / "outside-stacks"
    config_content = f"""version: 1
base_dir: /tmp/original
paths:
  stacks: {outside_stacks}
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
    stack_content = Path("tests/fixtures/example-project/stacks/usa1.yaml").read_bytes()
    backup = tmp_path / "outside-stack-backup.zip"
    files_sha256 = {
        "config/config.yaml": hashlib.sha256(config_content.encode("utf-8")).hexdigest(),
        "stacks/usa1.yaml": hashlib.sha256(stack_content).hexdigest(),
    }
    with ZipFile(backup, "w") as zip_file:
        zip_file.writestr(
            "manifest.json",
            json.dumps(
                {
                    "backup_schema": "proxystack.native-backup",
                    "backup_version": 1,
                    "created_at": "2026-06-06T12:00:00+08:00",
                    "files_sha256": files_sha256,
                }
            ),
        )
        zip_file.writestr("config/config.yaml", config_content)
        zip_file.writestr("stacks/usa1.yaml", stack_content)

    result = runner.invoke(agent_app, ["import", str(backup), "-c", str(tmp_path / "target" / "config.yaml")])

    assert result.exit_code == 1
    assert "import stacks directory must be inside base_dir" in result.output


def test_sub_help_is_available() -> None:
    """验证 proxystack-sub 帮助可以正常输出。"""
    result = runner.invoke(sub_app, ["--help"])

    assert result.exit_code == 0
    assert "proxystack-sub" in result.output


def test_sub_command_help_is_available() -> None:
    """验证 proxystack-sub P0 子命令都提供 help 输出。"""
    for command in [["version"], ["config"], ["import"], ["clear"], ["serve"]]:
        result = runner.invoke(sub_app, [*command, "--help"])

        assert result.exit_code == 0, command


def test_sub_version_is_available() -> None:
    """验证 proxystack-sub 版本命令可以正常输出。"""
    result = runner.invoke(sub_app, ["version"])

    assert result.exit_code == 0
    assert "proxystack-sub" in result.output


def test_sub_config_creates_default_config(tmp_path: Path) -> None:
    """验证 proxystack-sub config 会创建并校验默认 config.yaml。"""
    data_dir = tmp_path / "sub"
    config_path = data_dir / "config.yaml"

    result = runner.invoke(sub_app, ["config", "--data-dir", str(data_dir), "--editor", "true"])

    assert result.exit_code == 0, result.output
    assert "编辑校验通过" in result.output
    config_data = YAML(typ="safe").load(config_path.read_text(encoding="utf-8"))
    assert config_data["data_dir"] == str(data_dir)
    assert config_data["listen"] == "0.0.0.0:3003"
    assert config_data["access"]["type"] == "token"
    assert config_data["access"]["token"] == "change-me"


def test_sub_default_config_falls_back_when_builtin_template_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """验证内置模板缺失时 ps-sub 默认配置回退到代码默认值。"""
    data_dir = tmp_path / "sub"
    monkeypatch.setattr(sub_config_module, "read_builtin_sub_config_template", lambda: None)

    config = sub_config_module.default_sub_server_config(data_dir)

    assert config.listen == "0.0.0.0:3003"
    assert config.data_dir == data_dir


def test_sub_config_rejects_invalid_edit_before_replacing(tmp_path: Path) -> None:
    """验证 proxystack-sub config 编辑失败时不会替换原 config.yaml。"""
    data_dir = tmp_path / "sub"
    data_dir.mkdir()
    config_path = data_dir / "config.yaml"
    config_path.write_text(
        f"""data_dir: {data_dir}
listen: 127.0.0.1:3003
access:
  type: none
""",
        encoding="utf-8",
    )
    original_text = config_path.read_text(encoding="utf-8")
    editor = tmp_path / "bad_sub_config_editor.py"
    editor.write_text(
        """
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
path.write_text(text.replace("listen: 127.0.0.1:3003", "listen: ["), encoding="utf-8")
""".lstrip(),
        encoding="utf-8",
    )

    result = runner.invoke(sub_app, ["config", "--config", str(config_path), "--editor", f"{sys.executable} {editor}"])

    assert result.exit_code == 1
    assert "配置编辑失败" in result.output
    assert config_path.read_text(encoding="utf-8") == original_text


def test_sub_config_check_only_validates_existing_config(tmp_path: Path) -> None:
    """验证 proxystack-sub config --check-only 只校验配置，不启动编辑器。"""
    data_dir = tmp_path / "sub"
    data_dir.mkdir()
    config_path = data_dir / "config.yaml"
    config_path.write_text(
        """listen: 127.0.0.1:3003
access:
  type: none
""",
        encoding="utf-8",
    )

    result = runner.invoke(sub_app, ["config", "--config", str(config_path), "--check-only"])

    assert result.exit_code == 0
    assert "编辑校验通过" in result.output


def test_sub_import_writes_bundle_inputs_only(tmp_path: Path) -> None:
    """验证 proxystack-sub import 只解包 inputs，不生成 current 或 access 文件。"""
    bundle = tmp_path / "sub-bundle.zip"
    data_dir = tmp_path / "sub"
    export_result = runner.invoke(
        agent_app,
        ["sub", "export", "usa1", "-o", str(bundle), "-c", "tests/fixtures/example-project/config.yaml"],
    )
    assert export_result.exit_code == 0

    result = runner.invoke(sub_app, ["import", str(bundle), "--data-dir", str(data_dir)])

    assert result.exit_code == 0
    assert "订阅发布包已导入" in result.output
    assert "source=usa1" in result.output
    assert "inputs=1" in result.output
    assert "written usa1.yaml" in result.output
    rendered_index = merge_input_files(data_dir / "inputs")
    assert "alice" in rendered_index.users
    assert (data_dir / "inputs" / "usa1.yaml").exists()
    assert not (data_dir / "bundles" / "access.json").exists()
    assert not (data_dir / "current" / "index.json").exists()


def test_sub_import_rejects_duplicate_proxy_name(tmp_path: Path) -> None:
    """验证 proxystack-sub import 会拒绝同一用户下重复订阅代理名。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    first_input = input_dir / "first.yaml"
    second_input = input_dir / "second.yaml"
    bundle = tmp_path / "duplicate-proxy-name.zip"
    data_dir = tmp_path / "sub"
    write_cli_input(first_input, source="first", node_id="first:id", remark="same proxy")
    write_cli_input(second_input, source="second", node_id="second:id", remark="same proxy")
    write_bundle(
        bundle,
        "duplicate",
        [
            ("first.yaml", first_input.read_bytes()),
            ("second.yaml", second_input.read_bytes()),
        ],
    )

    result = runner.invoke(sub_app, ["import", str(bundle), "--data-dir", str(data_dir)])

    assert result.exit_code == 1
    assert "duplicate proxy name for user: user=alice name=same proxy" in result.output
    assert not (data_dir / "inputs").exists() or list((data_dir / "inputs").iterdir()) == []


def test_sub_clear_removes_imported_inputs_only(tmp_path: Path) -> None:
    """验证 proxystack-sub clear 只清理 inputs 中受管理的导入节点文件。"""
    data_dir = tmp_path / "sub"
    input_dir = data_dir / "inputs"
    input_dir.mkdir(parents=True)
    write_cli_input(input_dir / "manual.yaml")
    (input_dir / "other.json").write_text("{}", encoding="utf-8")
    (input_dir / "keep.txt").write_text("keep", encoding="utf-8")
    config_path = data_dir / "config.yaml"
    config_path.write_text(
        """listen: 127.0.0.1:3003
access:
  type: none
""",
        encoding="utf-8",
    )

    result = runner.invoke(sub_app, ["clear", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "已清空导入节点：inputs=2" in result.output
    assert "manual.yaml" in result.output
    assert "other.json" in result.output
    assert sorted(path.name for path in input_dir.iterdir()) == ["keep.txt"]
    assert config_path.exists()


def test_sub_serve_uses_config_access_and_memory_index(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    """验证 serve CLI 从配置读取 token，并把 inputs 加载到内存 app。"""
    caplog.set_level(logging.INFO)
    captured: dict[str, object] = {}
    data_dir = tmp_path / "sub"
    (data_dir / "inputs").mkdir(parents=True)
    write_cli_input(data_dir / "inputs" / "manual.yaml")
    config_path = tmp_path / "sub-config.yaml"
    config_path.write_text(
        f"""data_dir: {data_dir}
listen: 0.0.0.0:3004
access:
  type: token
  token: demo-token
watch_interval: 0.1
watch_debounce: 0
""",
        encoding="utf-8",
    )

    def fake_run(app: object, host: str, port: int) -> None:
        """记录 uvicorn.run 参数，避免测试启动真实 HTTP 服务。"""
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(sub_module.uvicorn, "run", fake_run)

    result = runner.invoke(
        sub_app,
        ["serve", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert "Subscription server configuration" in caplog.text
    assert "access=token" in caplog.text
    assert "demo-token" not in caplog.text
    assert "Subscription server template sources" in caplog.text
    assert "Subscription server loaded inputs" in caplog.text
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 3004
    client = TestClient(captured["app"])
    assert client.get("/sub/alice").status_code == 401
    assert client.get("/sub/alice", params={"token": "demo-token"}).status_code == 200


def test_sub_serve_requires_config_file(tmp_path: Path) -> None:
    """验证 serve 缺少 ps-sub 配置时不会以无 token 默认配置启动。"""
    data_dir = tmp_path / "sub"

    result = runner.invoke(sub_app, ["serve", "--data-dir", str(data_dir)])

    assert result.exit_code == 1
    assert "sub config file could not be read" in result.output


def test_sub_serve_rejects_duplicate_proxy_name_before_startup(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 serve 会在启动 HTTP 服务前拒绝同一用户下重复订阅代理名。"""
    data_dir = tmp_path / "sub"
    input_dir = data_dir / "inputs"
    input_dir.mkdir(parents=True)
    write_cli_input(input_dir / "first.yaml", source="first", node_id="first:id", remark="same proxy")
    write_cli_input(input_dir / "second.yaml", source="second", node_id="second:id", remark="same proxy")
    config_path = data_dir / "config.yaml"
    config_path.write_text(
        """listen: 127.0.0.1:3003
access:
  type: none
""",
        encoding="utf-8",
    )

    def fail_run(app: object, host: str, port: int) -> None:
        """serve 输入校验失败时不应启动真实 HTTP 服务。"""
        raise AssertionError("uvicorn.run should not be called")

    monkeypatch.setattr(sub_module.uvicorn, "run", fail_run)

    result = runner.invoke(sub_app, ["serve", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "duplicate proxy name for user: user=alice name=same proxy" in result.output


def test_sub_serve_defaults_data_dir_to_config_parent(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 ps-sub 配置缺省 data_dir 时使用配置文件所在目录。"""
    captured: dict[str, object] = {}
    data_dir = tmp_path / "sub"
    (data_dir / "inputs").mkdir(parents=True)
    write_cli_input(data_dir / "inputs" / "manual.yaml")
    config_path = data_dir / "config.yaml"
    config_path.write_text(
        """listen: 127.0.0.1:3003
access:
  type: none
""",
        encoding="utf-8",
    )

    def fake_run(app: object, host: str, port: int) -> None:
        """记录 uvicorn.run 参数，避免测试启动真实 HTTP 服务。"""
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(sub_module.uvicorn, "run", fake_run)

    result = runner.invoke(sub_app, ["serve", "--config", str(config_path)])

    assert result.exit_code == 0
    client = TestClient(captured["app"])
    response = client.get("/sub/alice")
    assert response.status_code == 200
    assert "manual:id" in response.text


def test_sub_serve_uses_config_templates_dir(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 serve CLI 会把配置中的 templates_dir 传给订阅渲染。"""
    captured: dict[str, object] = {}
    data_dir = tmp_path / "sub"
    template_root = tmp_path / "templates"
    (data_dir / "inputs").mkdir(parents=True)
    (template_root / "sub").mkdir(parents=True)
    write_cli_input(data_dir / "inputs" / "manual.yaml")
    (template_root / "sub" / "clash.yaml.j2").write_text(
        "mode: ConfigTemplate\nproxies:\n{{ proxies | yaml_block }}",
        encoding="utf-8",
    )
    config_path = data_dir / "config.yaml"
    config_path.write_text(
        f"""listen: 127.0.0.1:3003
templates_dir: {template_root}
access:
  type: none
""",
        encoding="utf-8",
    )

    def fake_run(app: object, host: str, port: int) -> None:
        """记录 uvicorn.run 参数，避免测试启动真实 HTTP 服务。"""
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(sub_module.uvicorn, "run", fake_run)

    result = runner.invoke(sub_app, ["serve", "--config", str(config_path)])

    assert result.exit_code == 0
    client = TestClient(captured["app"])
    response = client.get("/sub/alice")
    assert response.status_code == 200
    assert "mode: ConfigTemplate" in response.text


def test_subscription_export_import_e2e_merges_multiple_stack_bundles(tmp_path: Path) -> None:
    """验证多个 stack 发布包连续导入后会合并到同一个订阅索引。"""
    usa1_bundle = tmp_path / "usa1-sub-bundle.zip"
    usa2_bundle = tmp_path / "usa2-sub-bundle.zip"
    data_dir = tmp_path / "sub"
    usa1_export = runner.invoke(agent_app, ["sub", "export", "usa1", "-o", str(usa1_bundle), "-c", "tests/fixtures/example-project/config.yaml"])
    usa2_export = runner.invoke(agent_app, ["sub", "export", "usa2", "-o", str(usa2_bundle), "-c", "tests/fixtures/example-project/config.yaml"])
    usa1_import = runner.invoke(sub_app, ["import", str(usa1_bundle), "--data-dir", str(data_dir)])
    usa2_import = runner.invoke(sub_app, ["import", str(usa2_bundle), "--data-dir", str(data_dir)])

    assert usa1_export.exit_code == 0
    assert usa2_export.exit_code == 0
    assert usa1_import.exit_code == 0
    assert usa2_import.exit_code == 0
    sub_index = merge_input_files(data_dir / "inputs")
    assert [node.id for node in sub_index.nodes] == ["usa1:relay", "usa1:vmess:alice", "usa2:relay"]
    assert sub_index.sources == ["usa1", "usa2"]
    assert sorted(path.name for path in (data_dir / "inputs").iterdir()) == ["usa1.yaml", "usa2.yaml"]


def test_agent_sub_export_summary_does_not_write_bundle(tmp_path: Path) -> None:
    """验证 sub export --summary 只预览发布包内容，不写 zip。"""
    output = tmp_path / "summary-only.zip"

    result = runner.invoke(
        agent_app,
        ["sub", "export", "usa1", "--summary", "-o", str(output), "-c", "tests/fixtures/example-project/config.yaml"],
    )

    assert result.exit_code == 0
    assert "订阅发布包预览" in result.output
    assert "source=usa1" in result.output
    assert "inputs=1" in result.output
    assert "nodes=2" in result.output
    assert "usa1.yaml" in result.output
    assert "usa1-usa1 relay socks" in result.output
    assert "usa1-usa1 vmess" in result.output
    assert not output.exists()


def test_sub_import_keeps_existing_inputs_by_default(tmp_path: Path) -> None:
    """验证连续导入发布包默认保留其它 input。"""
    old_input_dir = tmp_path / "old-inputs"
    new_input_dir = tmp_path / "new-inputs"
    old_input_dir.mkdir()
    new_input_dir.mkdir()
    write_cli_input(old_input_dir / "old.yaml", source="old", node_id="old:id")
    write_cli_input(new_input_dir / "new.yaml", source="new", node_id="new:id")
    old_bundle = tmp_path / "old.zip"
    new_bundle = tmp_path / "new.zip"
    data_dir = tmp_path / "sub"

    write_bundle(old_bundle, "old", [("old.yaml", (old_input_dir / "old.yaml").read_bytes())])
    write_bundle(new_bundle, "new", [("new.yaml", (new_input_dir / "new.yaml").read_bytes())])

    old_import = runner.invoke(sub_app, ["import", str(old_bundle), "--data-dir", str(data_dir)])
    new_import = runner.invoke(sub_app, ["import", str(new_bundle), "--data-dir", str(data_dir)])
    overwrite_import = runner.invoke(sub_app, ["import", str(new_bundle), "--data-dir", str(data_dir)])

    assert old_import.exit_code == 0
    assert new_import.exit_code == 0
    assert overwrite_import.exit_code == 0
    assert "written new.yaml" in new_import.output
    assert "overwritten new.yaml" in overwrite_import.output
    rendered_index = merge_input_files(data_dir / "inputs")
    assert [node.id for node in rendered_index.nodes] == ["new:id", "old:id"]
    assert sorted(path.name for path in (data_dir / "inputs").iterdir()) == ["new.yaml", "old.yaml"]


def test_sub_import_replace_all_clears_existing_inputs(tmp_path: Path) -> None:
    """验证 import --replace-all 会清空旧 input 后再导入。"""
    old_input_dir = tmp_path / "old-inputs"
    new_input_dir = tmp_path / "new-inputs"
    old_input_dir.mkdir()
    new_input_dir.mkdir()
    write_cli_input(old_input_dir / "old.yaml", source="old", node_id="old:id")
    write_cli_input(new_input_dir / "new.yaml", source="new", node_id="new:id")
    old_bundle = tmp_path / "old.zip"
    new_bundle = tmp_path / "new.zip"
    data_dir = tmp_path / "sub"
    write_bundle(old_bundle, "old", [("old.yaml", (old_input_dir / "old.yaml").read_bytes())])
    write_bundle(new_bundle, "new", [("new.yaml", (new_input_dir / "new.yaml").read_bytes())])

    old_import = runner.invoke(sub_app, ["import", str(old_bundle), "--data-dir", str(data_dir)])
    new_import = runner.invoke(sub_app, ["import", str(new_bundle), "--data-dir", str(data_dir), "--replace-all"])

    assert old_import.exit_code == 0
    assert new_import.exit_code == 0
    assert "replace_all=true" in new_import.output
    assert "已删除旧 input" in new_import.output
    assert "old.yaml" in new_import.output
    rendered_index = merge_input_files(data_dir / "inputs")
    assert [node.id for node in rendered_index.nodes] == ["new:id"]
    assert sorted(path.name for path in (data_dir / "inputs").iterdir()) == ["new.yaml"]


def test_sub_import_ignores_bundle_access_metadata(tmp_path: Path) -> None:
    """验证 import 不再根据发布包 access 做兼容性判断。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    write_cli_input(input_dir / "first.yaml", source="first", node_id="first:id")
    write_cli_input(input_dir / "second.yaml", source="second", node_id="second:id")
    first_bundle = tmp_path / "first.zip"
    second_bundle = tmp_path / "second.zip"
    data_dir = tmp_path / "sub"
    write_bundle(first_bundle, "first", [("first.yaml", (input_dir / "first.yaml").read_bytes())])

    write_bundle(
        second_bundle,
        "second",
        [("second.yaml", (input_dir / "second.yaml").read_bytes())],
    )

    first_import = runner.invoke(sub_app, ["import", str(first_bundle), "--data-dir", str(data_dir)])
    second_import = runner.invoke(sub_app, ["import", str(second_bundle), "--data-dir", str(data_dir)])

    assert first_import.exit_code == 0
    assert second_import.exit_code == 0
    assert not (data_dir / "bundles" / "access.json").exists()
    assert sorted(path.name for path in (data_dir / "inputs").iterdir()) == ["first.yaml", "second.yaml"]


def test_release_artifacts_define_console_scripts_and_sub_container_defaults() -> None:
    """验证发布材料包含 console scripts 和 proxystack-sub 容器默认命令。"""
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    makefile = Path("Makefile").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile.sub").read_text(encoding="utf-8")
    compose = YAML(typ="safe").load(Path("docker-compose.sub.yml").read_text(encoding="utf-8"))
    service = compose["services"]["proxystack-sub"]

    assert 'proxystack-agent = "proxystack.cli.agent:run"' in pyproject
    assert 'proxystack-sub = "proxystack.cli.sub:run"' in pyproject
    assert 'ps-agent = "proxystack.cli.agent:run"' in pyproject
    assert 'ps-sub = "proxystack.cli.sub:run"' in pyproject
    assert "scripts/build_package.py" in makefile
    assert 'CMD ["proxystack-sub", "serve", "--config", "/data/config.yaml"]' in dockerfile
    assert service["user"] == "10001:10001"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "/opt/proxystack/sub:/data" in service["volumes"]
    assert service["healthcheck"]["test"][0] == "CMD"
    assert service["command"] == [
        "proxystack-sub",
        "serve",
        "--config",
        "/data/config.yaml",
    ]


def test_release_build_cleanup_removes_stale_build_state(tmp_path: Path) -> None:
    """验证发布构建前会清理旧 build、dist 和 egg-info 状态。"""
    dist_dir = tmp_path / "dist"
    build_dir = tmp_path / "build"
    egg_info_dir = tmp_path / "src" / "proxystack.egg-info"
    for directory in [dist_dir, build_dir, egg_info_dir]:
        directory.mkdir(parents=True)
        (directory / "stale.txt").write_text("stale", encoding="utf-8")

    clean_build_state(dist_dir, no_clean=False, build_dir=build_dir, egg_info_dir=egg_info_dir)

    assert not dist_dir.exists()
    assert not build_dir.exists()
    assert not egg_info_dir.exists()


def write_cli_input(
    path: Path,
    source: str = "manual",
    node_id: str = "manual:id",
    remark: Optional[str] = None,
) -> None:
    """写入 CLI 测试使用的最小订阅 input。"""
    content = {
        "input_schema": "proxystack.subscription-input",
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
                "remark": remark or node_id,
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
    """复制测试项目 fixture 到临时目录，并把 base_dir 改为临时目录。"""
    project_dir = tmp_path / "project"
    stacks_dir = project_dir / "stacks"
    stacks_dir.mkdir(parents=True)
    for source_path in Path("tests/fixtures/example-project/stacks").glob("*.yaml"):
        shutil.copy2(source_path, stacks_dir / source_path.name)

    yaml = YAML(typ="safe")
    config_data = yaml.load(Path("tests/fixtures/example-project/config.yaml").read_text(encoding="utf-8"))
    config_data["base_dir"] = str(project_dir)
    config = project_dir / "config.yaml"
    writer = YAML()
    with config.open("w", encoding="utf-8") as config_file:
        writer.dump(config_data, config_file)
    write_fake_proxy_binaries(project_dir)
    return config


def write_fake_proxy_binaries(project_dir: Path) -> None:
    """写入测试用代理核心占位文件，避免 start 测试调用真实二进制。"""
    bin_dir = project_dir / "bin"
    bin_dir.mkdir(exist_ok=True)
    for binary_name in ["mihomo", "xray"]:
        binary_path = bin_dir / binary_name
        binary_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary_path.chmod(0o750)


def use_fake_systemd(monkeypatch: MonkeyPatch, tmp_path: Path) -> FakeSystemdRunner:
    """把 agent CLI 的 systemd 调用替换为 fake runner 和 fake unit_dir。"""
    fake_runner = FakeSystemdRunner()
    monkeypatch.setattr(agent_module, "SYSTEMD_RUNNER", fake_runner)
    monkeypatch.setattr(agent_module, "SYSTEMD_UNIT_DIR_OVERRIDE", tmp_path / "systemd")
    return fake_runner


def use_fake_root_managed_owner(monkeypatch: MonkeyPatch) -> list[tuple[Path, int, int]]:
    """模拟 root 下存在 proxystack 用户组，并记录 chown 调用。"""
    chown_calls: list[tuple[Path, int, int]] = []

    def fake_chown(path, user_id: int, group_id: int) -> None:
        chown_calls.append((Path(path), user_id, group_id))

    monkeypatch.setattr(lifecycle_module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(lifecycle_module.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=123))
    monkeypatch.setattr(lifecycle_module.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=456))
    monkeypatch.setattr(lifecycle_module.os, "chown", fake_chown)
    return chown_calls


def write_cli_config_without_valid_stacks(tmp_path: Path) -> Path:
    """写入包含坏 stack 文件的配置，供 start sub 验证不扫描 stacks。"""
    project_dir = tmp_path / "project"
    stacks_dir = project_dir / "stacks"
    stacks_dir.mkdir(parents=True)
    (stacks_dir / "broken.yaml").write_text("name: [", encoding="utf-8")
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
  listen: 127.0.0.1:3003
  access:
    type: token
    token: test-token
port_ranges:
  xrelay_inbound: 24000-24999
  clash_socks: 17000-17999
  clash_controller: 19000-19999
""".lstrip(),
        encoding="utf-8",
    )
    return config
