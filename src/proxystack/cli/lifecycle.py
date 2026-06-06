"""proxystack-agent 生命周期命令支撑逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
import grp
from importlib import resources
import hashlib
import json
import os
from pathlib import Path
import pwd
import shlex
import subprocess
import tempfile
from typing import Any
from typing import Optional

from pydantic import ValidationError
from ruamel.yaml import YAML

from proxystack.config import DEFAULT_CONFIG_PATH
from proxystack.config import load_config
from proxystack.config import load_stacks
from proxystack.domain.models import GlobalConfig
from proxystack.domain.models import Inbound
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.domain.models import parse_listen
from proxystack.domain.models import validate_identifier
from proxystack.domain.validation import collect_port_bindings
from proxystack.domain.validation import is_port_available
from proxystack.domain.validation import validate_stack_set
from proxystack.generator.mihomo import dumps_mihomo_config
from proxystack.generator.sub import access_from_stack_set
from proxystack.generator.sub import index_to_json
from proxystack.generator.sub import input_to_yaml
from proxystack.generator.sub import merge_inputs
from proxystack.generator.sub import render_stack_input
from proxystack.generator.xray import dumps_xray_config
from proxystack.graph import DependencyPlan
from proxystack.graph import ReferenceGraph
from proxystack.graph import ServiceNode
from proxystack.graph import build_reference_graph

MANIFEST_VERSION = 1
MANIFEST_NAME = "manifest.json"
BUILTIN_TEMPLATES = {"pair", "auto-url-test", "load-balance"}
SUB_SERVICE_NAME = "proxystack-sub.service"
MANAGED_USER = "proxystack"
MANAGED_GROUP = "proxystack"
MANAGED_DIR_MODE = 0o750
MANAGED_FILE_MODE = 0o640
SYSTEMD_UNIT_PATHS = [
    Path("/etc/systemd/system/proxystack-xray@.service"),
    Path("/etc/systemd/system/proxystack-clash@.service"),
    Path("/etc/systemd/system/proxystack-sub.service"),
]


@dataclass(frozen=True)
class GeneratedFile:
    """表示一次编译希望管理的单个生成文件。"""

    relative_path: str
    content: bytes
    service_name: str

    @property
    def sha256(self) -> str:
        """返回生成内容的 sha256 摘要，供 manifest 和 check 对比使用。"""
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class FileChange:
    """表示生成配置写入前后的单个文件变化。"""

    action: str
    relative_path: str
    path: Path
    service_name: str
    old_sha256: Optional[str]
    new_sha256: Optional[str]

    @property
    def is_changed(self) -> bool:
        """判断该文件是否需要写入或删除。"""
        return self.action in {"create", "update", "delete"}


@dataclass(frozen=True)
class TargetScope:
    """表示 CLI target 解析后的组件选择范围。"""

    raw_target: Optional[str]
    components: frozenset[tuple[str, str]]
    include_sub: bool
    all_targets: bool

    @property
    def service_names(self) -> tuple[str, ...]:
        """返回当前范围内的服务名，供 service adapter 输出。"""
        service_names = [component_service_name(component, stack_name) for stack_name, component in sorted(self.components)]
        if self.include_sub:
            service_names.append(SUB_SERVICE_NAME)
        return tuple(service_names)


@dataclass(frozen=True)
class RuntimePlan:
    """表示一次运行配置编译结果和文件变化。"""

    config: GlobalConfig
    stack_set: StackSet
    scope: TargetScope
    generated_files: list[GeneratedFile]
    changes: list[FileChange]
    dependency_plan: Optional[DependencyPlan]

    @property
    def changed_services(self) -> list[str]:
        """返回受文件变化影响的服务名，保持输出顺序稳定。"""
        service_names = {change.service_name for change in self.changes if change.is_changed}
        return [service_name for service_name in self.scope.service_names if service_name in service_names]


def init_project(config_path: Path, base_dir: Optional[Path], external_host: str, force: bool) -> list[Path]:
    """创建 base_dir、标准目录和默认 config.yaml，适用于首次初始化。"""
    actual_base_dir = base_dir or config_path.parent
    created_paths: list[Path] = []
    ensure_managed_directory(actual_base_dir)
    created_paths.append(actual_base_dir)
    if config_path.exists() and not force:
        config = load_config(config_path)
        created_paths.extend(ensure_project_dirs(config))
        return created_paths

    config_text = default_config_yaml(actual_base_dir, external_host)
    write_text_if_changed(config_path, config_text, force=force)
    config = load_config(config_path)
    created_paths.extend(ensure_project_dirs(config))
    return created_paths


def default_config_yaml(base_dir: Path, external_host: str) -> str:
    """生成保守的默认全局配置 YAML。"""
    return f"""version: 1
base_dir: {base_dir}
paths:
  bin: bin
  geo: geo
  stacks: stacks
  runtime: runtime
  generated: runtime/generated
  publish: publish
  downloads: downloads
  sub: sub

external_host: {external_host}

subscription:
  source: local
  listen: 127.0.0.1:3003
  access:
    type: token
    token: change-me-subscription-token

port_ranges:
  xrelay_inbound: 24000-24999
  clash_socks: 17000-17999
  clash_controller: 19000-19999

defaults:
  clash:
    mode: Rule
    rule_profile: default
  xrelay:
    loglevel: warning
    api:
      enabled: false
      tag: api
      listen: 127.0.0.1:10085
      services: [StatsService]
    stats:
      enabled: false
    policy:
      enabled: false
      levels:
        "0":
          statsUserUplink: true
          statsUserDownlink: true
      system:
        statsInboundUplink: true
        statsInboundDownlink: true
        statsOutboundUplink: true
        statsOutboundDownlink: true

security:
  require_auth_for_public_socks_http: true
  allow_noauth_public: false

install:
  mihomo:
    version: latest
    source: auto
  xray:
    version: latest
    source: auto
  geo:
    version: latest
"""


def managed_owner_ids() -> Optional[tuple[int, int]]:
    """root 执行且 proxystack 用户组存在时返回托管 owner。"""
    if os.geteuid() != 0:
        return None
    try:
        return pwd.getpwnam(MANAGED_USER).pw_uid, grp.getgrnam(MANAGED_GROUP).gr_gid
    except KeyError:
        return None


def ensure_managed_metadata(path: Path, mode: int) -> None:
    """校正托管文件或目录权限，root 下同步 owner。"""
    if not path.exists():
        return
    os.chmod(path, mode)
    owner_ids = managed_owner_ids()
    if owner_ids is None:
        return
    os.chown(path, *owner_ids)


def ensure_managed_directory(path: Path) -> None:
    """创建目录并应用托管目录权限。"""
    path.mkdir(parents=True, exist_ok=True)
    ensure_managed_metadata(path, MANAGED_DIR_MODE)


def ensure_managed_file_metadata(path: Path, mode: int = MANAGED_FILE_MODE) -> None:
    """应用托管文件权限，内容未变时也用于修复旧 owner。"""
    ensure_managed_metadata(path, mode)


def ensure_project_dirs(config: GlobalConfig) -> list[Path]:
    """按全局配置创建 agent 生命周期命令需要的目录。"""
    paths = [
        config.base_dir,
        config.resolve_path(config.paths.stacks),
        config.resolve_path(config.paths.runtime),
        config.resolve_path(config.paths.generated),
        config.resolve_path(config.paths.publish),
        config.resolve_path(config.paths.downloads),
        config.resolve_path(config.paths.sub),
        config.resolve_path(config.paths.sub) / "inputs",
        config.resolve_path(config.paths.sub) / "bundles",
        config.resolve_path(config.paths.sub) / "current",
    ]
    for path in paths:
        ensure_managed_directory(path)
    return paths


def ensure_existing_stack_metadata(config: GlobalConfig) -> None:
    """修复既有 stack 文件权限，兼容旧版本 root 执行留下的文件。"""
    ensure_managed_directory(config.stacks_dir)
    for pattern in ("*.yaml", "*.yml"):
        for path in config.stacks_dir.glob(pattern):
            if path.is_file():
                ensure_managed_file_metadata(path)


def add_stack(
    config_path: Path,
    name: str,
    template_name: str,
    from_file: Optional[Path],
    members: Optional[str],
    allocate_ports: bool,
) -> Path:
    """从内置模板或外部文件创建新的 stack YAML，默认不覆盖既有文件。"""
    validate_identifier(name, "stack name")
    config = load_config(config_path)
    ensure_managed_directory(config.stacks_dir)
    target_path = config.stacks_dir / f"{name}.yaml"
    if target_path.exists():
        raise ValueError(f"stack already exists: {name}")
    stack_data = load_stack_source_data(name, template_name, from_file)
    source_name = str(stack_data.get("name", name))
    stack_data["name"] = name
    rewrite_self_refs(stack_data, source_name, name)
    if members:
        apply_auto_members(stack_data, parse_members(members))
    if allocate_ports:
        allocate_stack_ports(config, stack_data)
    stack = validate_stack_document(stack_data, name, target_path)
    validate_stack_in_project(config, stack, replace_existing=False)
    write_yaml_if_changed(target_path, stack_data)
    return target_path


def load_stack_source_data(name: str, template_name: str, from_file: Optional[Path]) -> dict[str, Any]:
    """读取 add 命令的 stack 来源，并校验外部文件和内置模板参数。"""
    if from_file is not None:
        source_data = load_yaml_mapping(from_file)
        if from_file.stem != source_data.get("name"):
            raise ValueError("from-file name must match its file name")
        if source_data.get("name") != name:
            raise ValueError("from-file stack name must match add target")
        return source_data
    if template_name not in BUILTIN_TEMPLATES:
        raise ValueError(f"unknown stack template: {template_name}")
    return load_yaml_text(read_builtin_template(template_name))


def read_builtin_template(template_name: str) -> str:
    """读取打包在 proxystack 内的 stack 模板文本。"""
    template_path = resources.files("proxystack").joinpath("templates", f"stack.{template_name}.yaml")
    return template_path.read_text(encoding="utf-8")


def parse_members(raw_members: str) -> list[str]:
    """解析 --members 参数，并校验成员名可作为 ref 第一段。"""
    members = [member.strip() for member in raw_members.split(",") if member.strip()]
    if not members:
        raise ValueError("members must not be empty")
    for member in members:
        validate_identifier(member, "member stack name")
    return members


def apply_auto_members(stack_data: dict[str, Any], members: list[str]) -> None:
    """把 auto 模板中的成员占位替换为指定 stack 的 xrelay-socks5 引用。"""
    clash_data = stack_data.setdefault("clash", {})
    upstream_names = [f"{member}-local" for member in members]
    clash_data["upstreams"] = [
        {
            "name": upstream_name,
            "type": "xrelay-socks5",
            "ref": f"{member}.relay",
        }
        for member, upstream_name in zip(members, upstream_names)
    ]
    auto_group_name = None
    for group_data in clash_data.get("groups", []):
        group_type = group_data.get("type")
        if group_type in {"url-test", "load-balance"}:
            group_data["proxies"] = upstream_names
            auto_group_name = group_data.get("name")
    if auto_group_name is None:
        raise ValueError("auto members require a url-test or load-balance group")
    for group_data in clash_data.get("groups", []):
        if group_data.get("type") == "select":
            group_data["proxies"] = [auto_group_name, *upstream_names, "DIRECT"]


def clone_stack(config_path: Path, source: str, target: str, allocate_ports: bool) -> Path:
    """复制 stack YAML 为新名称，并按需为监听端口重新分配端口池。"""
    validate_identifier(source, "source stack name")
    validate_identifier(target, "target stack name")
    config = load_config(config_path)
    source_path = config.stacks_dir / f"{source}.yaml"
    target_path = config.stacks_dir / f"{target}.yaml"
    if not source_path.exists():
        raise ValueError(f"source stack does not exist: {source}")
    if target_path.exists():
        raise ValueError(f"target stack already exists: {target}")
    stack_data = load_yaml_mapping(source_path)
    stack_data["name"] = target
    rewrite_self_refs(stack_data, source, target)
    if allocate_ports:
        allocate_stack_ports(config, stack_data)
    stack = validate_stack_document(stack_data, target, target_path)
    validate_stack_in_project(config, stack, replace_existing=False)
    write_yaml_if_changed(target_path, stack_data)
    return target_path


def rewrite_self_refs(value: Any, source: str, target: str) -> None:
    """递归改写 ref 字符串中指向自身 stack 的第一段。"""
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if isinstance(item, str):
                value[key] = rewrite_ref_string(item, source, target)
            else:
                rewrite_self_refs(item, source, target)
    if isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str):
                value[index] = rewrite_ref_string(item, source, target)
            else:
                rewrite_self_refs(item, source, target)


def rewrite_ref_string(value: str, source: str, target: str) -> str:
    """在 ref 形态字符串中把第一段 source 改为 target。"""
    parts = value.split(".")
    if len(parts) in {2, 3} and parts[0] == source and all(parts):
        return ".".join([target, *parts[1:]])
    return value


def allocate_stack_ports(config: GlobalConfig, stack_data: dict[str, Any]) -> None:
    """按全局端口池为 stack 内 xrelay inbound、clash socks 和 controller 分配端口。"""
    used_ports = collect_used_ports(config)
    xrelay_data = stack_data.setdefault("xrelay", {})
    inbounds = xrelay_data.get("inbounds", [])
    inbound_ports = allocate_from_range(config.port_ranges.xrelay_inbound.start, config.port_ranges.xrelay_inbound.end, used_ports, len(inbounds))
    for inbound_data, port in zip(inbounds, inbound_ports):
        inbound_data["port"] = port
        used_ports.add(port)

    clash_data = stack_data.setdefault("clash", {})
    listener_data = clash_data.setdefault("listeners", {})
    socks_listeners = listener_data.get("socks", [])
    socks_ports = allocate_from_range(config.port_ranges.clash_socks.start, config.port_ranges.clash_socks.end, used_ports, len(socks_listeners))
    for socks_data, port in zip(socks_listeners, socks_ports):
        socks_data["port"] = port
        used_ports.add(port)

    controller_data = clash_data.setdefault("controller", {})
    controller_host = "127.0.0.1"
    if "listen" in controller_data:
        controller_host, _ = parse_listen(str(controller_data["listen"]))
    controller_port = allocate_from_range(
        config.port_ranges.clash_controller.start,
        config.port_ranges.clash_controller.end,
        used_ports,
        1,
    )[0]
    controller_data["listen"] = f"{controller_host}:{controller_port}"


def collect_used_ports(config: GlobalConfig) -> set[int]:
    """收集当前已声明和系统已占用的端口，供自动分配避让。"""
    if not config.stacks_dir.exists():
        return set()
    stack_set = load_stacks(config, check_system_ports=False)
    return {binding.port for binding in collect_port_bindings(stack_set)}


def allocate_from_range(start: int, end: int, used_ports: set[int], count: int) -> list[int]:
    """从端口范围中分配未声明且系统未占用的端口。"""
    allocated_ports: list[int] = []
    for port in range(start, end + 1):
        if port in used_ports or not is_port_available("0.0.0.0", port):
            continue
        allocated_ports.append(port)
        if len(allocated_ports) == count:
            return allocated_ports
    raise ValueError("not enough available ports in range")


def validate_stack_document(stack_data: dict[str, Any], expected_name: str, source_path: Optional[Path] = None) -> Stack:
    """校验待写入的 stack 文档基础结构和目标名称。"""
    stack = Stack.model_validate(stack_data)
    if stack.name != expected_name:
        raise ValueError(f"stack name must be {expected_name}")
    if source_path is not None:
        if source_path.stem != stack.name:
            raise ValueError(f"stack name must match file name: {source_path.stem}")
        stack.source_path = source_path
    return stack


def validate_stack_in_project(config: GlobalConfig, stack: Stack, replace_existing: bool) -> None:
    """把候选 stack 放入当前项目做整体验证，避免写入后才发现配置无效。"""
    current_stack_set = load_stacks(config, check_system_ports=False)
    stacks: list[Stack] = []
    replaced = False
    for current_stack in current_stack_set.stacks:
        if current_stack.name != stack.name:
            stacks.append(current_stack)
            continue
        if not replace_existing:
            raise ValueError(f"stack already exists: {stack.name}")
        stacks.append(stack)
        replaced = True
    if not replaced:
        stacks.append(stack)
    validate_stack_set(StackSet(config=config, stacks=stacks), check_system_ports=False)


def list_stacks(config_path: Path, check_system_ports: bool) -> list[dict[str, str]]:
    """读取 stack 列表并提取 CLI 展示所需字段。"""
    config = load_config(config_path)
    stack_set = load_stacks(config, check_system_ports=check_system_ports)
    generated_dir = config.resolve_path(config.paths.generated)
    rows: list[dict[str, str]] = []
    for stack in stack_set.stacks:
        clash_ports = ",".join(str(listener.port) for listener in stack.clash.listeners.socks)
        generated_components = generated_stack_components(generated_dir, stack)
        running_components = running_stack_components(stack)
        rows.append(
            {
                "name": stack.name,
                "enabled": "yes" if stack.enabled else "no",
                "role": stack.role,
                "xrelay": "yes" if stack.xrelay.enabled else "no",
                "clash": "yes" if stack.clash.enabled else "no",
                "generated": format_component_list(generated_components),
                "running": format_component_list(running_components),
                "xrelay_ports": format_xrelay_inbounds(stack.xrelay.inbounds),
                "clash_socks": clash_ports or "-",
                "clash_controller": stack.clash.controller.listen,
            }
        )
    return rows


def generated_stack_components(generated_dir: Path, stack: Stack) -> list[str]:
    """根据 runtime/generated 下的配置文件判断 stack 哪些服务已生成配置。"""
    components: list[str] = []
    if stack.xrelay.enabled and (generated_dir / "xray" / f"{stack.name}.json").exists():
        components.append("xrelay")
    if stack.clash.enabled and (generated_dir / "mihomo" / f"{stack.name}.yaml").exists():
        components.append("clash")
    return components


def running_stack_components(stack: Stack) -> list[str]:
    """通过 systemctl is-active 判断 stack 哪些服务正在运行。"""
    components: list[str] = []
    if stack.xrelay.enabled and is_service_active(component_service_name("xrelay", stack.name)):
        components.append("xrelay")
    if stack.clash.enabled and is_service_active(component_service_name("clash", stack.name)):
        components.append("clash")
    return components


def is_service_active(service_name: str) -> bool:
    """查询 systemd 服务是否 active；无 systemd 或服务不存在时按未运行处理。"""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", service_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return result.returncode == 0


def format_component_list(components: list[str]) -> str:
    """把组件列表格式化为 list 表格中的紧凑展示值。"""
    return ",".join(components) if components else "-"


def format_xrelay_inbounds(inbounds: list[Inbound]) -> str:
    """把 xrelay inbound 展示为 user/protocol:port，方便 list 一眼区分入口。"""
    items = []
    for inbound in inbounds:
        user = inbound.user or "-"
        items.append(f"{user}/{inbound.protocol}:{inbound.port}")
    return ",".join(items) if items else "-"


def remove_stack(config_path: Path, name: str, purge: bool) -> list[Path]:
    """删除 stack YAML，并在指定 purge 时删除对应生成文件和 manifest 记录。"""
    validate_identifier(name, "stack name")
    config = load_config(config_path)
    stack_path = config.stacks_dir / f"{name}.yaml"
    if not stack_path.exists():
        raise ValueError(f"stack does not exist: {name}")
    stack_path.unlink()
    removed_paths = [stack_path]
    if purge:
        removed_paths.extend(purge_stack_generated_files(config, name))
    return removed_paths


def purge_stack_generated_files(config: GlobalConfig, name: str) -> list[Path]:
    """清理指定 stack 的生成文件，并从 manifest 中移除对应记录。"""
    generated_dir = config.resolve_path(config.paths.generated)
    manifest = load_manifest(generated_dir / MANIFEST_NAME)
    service_names = {
        component_service_name("xrelay", name),
        component_service_name("clash", name),
    }
    removed_paths: list[Path] = []
    files = dict(manifest.get("files", {}))
    for relative_path, entry in list(files.items()):
        if entry.get("service") not in service_names:
            continue
        path = generated_dir / relative_path
        if path.exists():
            path.unlink()
            removed_paths.append(path)
        files.pop(relative_path)
    manifest["files"] = files
    write_manifest_if_changed(generated_dir / MANIFEST_NAME, manifest)
    return removed_paths


def render_model_json(config_path: Path, target: Optional[str], check_system_ports: bool) -> str:
    """输出解析后的中间模型 JSON，不写入运行目录。"""
    config = load_config(config_path)
    stack_set = load_stacks(config, check_system_ports=check_system_ports)
    if target is not None:
        selected_stack = stack_set.by_name().get(target)
        if selected_stack is None:
            raise ValueError(f"stack does not exist: {target}")
        stack_set = StackSet(config=config, stacks=[selected_stack])
    return json.dumps(stack_set.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2) + "\n"


def build_runtime_plan(config_path: Path, target: Optional[str], check_system_ports: bool) -> RuntimePlan:
    """编译目标范围内的生成文件变化，不写入生成文件内容。"""
    config = load_config(config_path)
    ensure_existing_stack_metadata(config)
    stack_set = load_stacks(config, check_system_ports=check_system_ports)
    scope = resolve_target_scope(stack_set, target)
    generated_dir = config.resolve_path(config.paths.generated)
    generated_files = compile_generated_files(stack_set, scope, generated_dir)
    manifest = load_manifest(generated_dir / MANIFEST_NAME)
    changes = plan_file_changes(generated_dir, manifest, generated_files, scope)
    dependency_plan = build_dependency_plan(stack_set, scope)
    return RuntimePlan(
        config=config,
        stack_set=stack_set,
        scope=scope,
        generated_files=generated_files,
        changes=changes,
        dependency_plan=dependency_plan,
    )


def apply_runtime_plan(plan: RuntimePlan) -> list[FileChange]:
    """按编译结果写入变化文件和 manifest，未变化文件保持原 mtime。"""
    generated_dir = plan.config.resolve_path(plan.config.paths.generated)
    ensure_managed_directory(generated_dir)
    desired_by_path = {generated_file.relative_path: generated_file for generated_file in plan.generated_files}
    for change in plan.changes:
        if change.action in {"create", "update"}:
            generated_file = desired_by_path[change.relative_path]
            write_bytes_if_changed(change.path, generated_file.content)
        if change.action == "unchanged" and change.path.exists():
            ensure_managed_directory(change.path.parent)
            ensure_managed_file_metadata(change.path)
        if change.action == "delete" and change.path.exists():
            change.path.unlink()
    manifest = update_manifest_for_scope(load_manifest(generated_dir / MANIFEST_NAME), plan)
    write_manifest_if_changed(generated_dir / MANIFEST_NAME, manifest)
    return plan.changes


def compile_generated_files(stack_set: StackSet, scope: TargetScope, generated_dir: Path) -> list[GeneratedFile]:
    """调用现有生成器编译目标范围内的 xray、mihomo 和订阅索引文件。"""
    generated_files: list[GeneratedFile] = []
    for stack in stack_set.stacks:
        if includes_component(scope, stack.name, "xrelay"):
            content = dumps_xray_config(stack_set, stack.name).encode("utf-8")
            generated_files.append(GeneratedFile(f"xray/{stack.name}.json", content, component_service_name("xrelay", stack.name)))
        if includes_component(scope, stack.name, "clash"):
            content = dumps_mihomo_config(stack_set, stack.name).encode("utf-8")
            generated_files.append(GeneratedFile(f"mihomo/{stack.name}.yaml", content, component_service_name("clash", stack.name)))
    if scope.include_sub:
        generated_files.extend(compile_sub_files(stack_set, generated_dir))
    return generated_files


def compile_sub_files(stack_set: StackSet, generated_dir: Path) -> list[GeneratedFile]:
    """编译本地订阅服务使用的 input 和 index 文件。"""
    source = stack_set.config.subscription.source
    input_relative_path = f"sub/inputs/{source}.yaml"
    index_relative_path = "sub/index.json"
    subscription_input = render_stack_input(stack_set, source)
    input_generated_at = read_generated_at(generated_dir / input_relative_path)
    if input_generated_at:
        subscription_input = subscription_input.model_copy(update={"generated_at": input_generated_at})
    subscription_index = merge_inputs(
        [(Path(f"{source}.yaml"), subscription_input)],
        access=access_from_stack_set(stack_set),
    )
    index_generated_at = read_generated_at(generated_dir / index_relative_path)
    if index_generated_at:
        subscription_index = subscription_index.model_copy(update={"generated_at": index_generated_at})
    return [
        GeneratedFile(input_relative_path, input_to_yaml(subscription_input).encode("utf-8"), SUB_SERVICE_NAME),
        GeneratedFile(index_relative_path, index_to_json(subscription_index).encode("utf-8"), SUB_SERVICE_NAME),
    ]


def read_generated_at(path: Path) -> Optional[str]:
    """从既有 YAML/JSON 生成文件中读取 generated_at，用于保持 start 幂等。"""
    if not path.exists():
        return None
    try:
        if path.suffix == ".json":
            loaded = json.loads(path.read_text(encoding="utf-8"))
        else:
            loaded = load_yaml_mapping(path)
    except (OSError, ValueError):
        return None
    if isinstance(loaded, dict) and isinstance(loaded.get("generated_at"), str):
        return loaded["generated_at"]
    return None


def plan_file_changes(
    generated_dir: Path,
    manifest: dict[str, Any],
    generated_files: list[GeneratedFile],
    scope: TargetScope,
) -> list[FileChange]:
    """基于 manifest 和现有文件计算 create/update/unchanged/delete 视图。"""
    changes: list[FileChange] = []
    desired_by_path = {generated_file.relative_path: generated_file for generated_file in generated_files}
    manifest_files = manifest.get("files", {})
    for relative_path, generated_file in sorted(desired_by_path.items()):
        path = generated_dir / relative_path
        old_sha256 = file_sha256(path) if path.exists() else None
        new_sha256 = generated_file.sha256
        if old_sha256 is None:
            action = "create"
        elif old_sha256 == new_sha256:
            action = "unchanged"
        else:
            action = "update"
        changes.append(
            FileChange(
                action=action,
                relative_path=relative_path,
                path=path,
                service_name=generated_file.service_name,
                old_sha256=old_sha256 or manifest_files.get(relative_path, {}).get("sha256"),
                new_sha256=new_sha256,
            )
        )
    selected_services = set(scope.service_names)
    for relative_path, entry in sorted(manifest_files.items()):
        if relative_path in desired_by_path:
            continue
        service_name = str(entry.get("service", ""))
        if not scope.all_targets and service_name not in selected_services:
            continue
        path = generated_dir / relative_path
        changes.append(
            FileChange(
                action="delete",
                relative_path=relative_path,
                path=path,
                service_name=service_name,
                old_sha256=file_sha256(path) if path.exists() else entry.get("sha256"),
                new_sha256=None,
            )
        )
    return changes


def update_manifest_for_scope(manifest: dict[str, Any], plan: RuntimePlan) -> dict[str, Any]:
    """按本次目标范围更新 manifest 文件清单。"""
    files = dict(manifest.get("files", {}))
    selected_services = set(plan.scope.service_names)
    desired_by_path = {generated_file.relative_path: generated_file for generated_file in plan.generated_files}
    for relative_path, entry in list(files.items()):
        service_name = str(entry.get("service", ""))
        if relative_path in desired_by_path:
            continue
        if plan.scope.all_targets or service_name in selected_services:
            files.pop(relative_path)
    for relative_path, generated_file in desired_by_path.items():
        files[relative_path] = {
            "sha256": generated_file.sha256,
            "service": generated_file.service_name,
        }
    return {
        "manifest_version": MANIFEST_VERSION,
        "files": {relative_path: files[relative_path] for relative_path in sorted(files)},
    }


def load_manifest(path: Path) -> dict[str, Any]:
    """读取生成文件 manifest；缺失时返回空 manifest。"""
    if not path.exists():
        return {"manifest_version": MANIFEST_VERSION, "files": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid manifest: {path}") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("files", {}), dict):
        raise ValueError(f"invalid manifest: {path}")
    return loaded


def resolve_target_scope(stack_set: StackSet, target: Optional[str]) -> TargetScope:
    """把 CLI target 解析为具体组件和 sub 服务范围。"""
    target = normalize_target(target)
    if target is None:
        components = {
            (stack.name, component)
            for stack in stack_set.stacks
            if stack.enabled
            for component in enabled_components(stack)
        }
        return TargetScope(raw_target=None, components=frozenset(components), include_sub=True, all_targets=True)
    if target == "sub":
        return TargetScope(raw_target=target, components=frozenset(), include_sub=True, all_targets=False)
    if "/" in target:
        component, stack_name = parse_component_target(target)
        stack = require_stack(stack_set, stack_name)
        ensure_component_enabled(stack, component)
        return TargetScope(raw_target=target, components=frozenset({(stack_name, component)}), include_sub=False, all_targets=False)
    stack = require_stack(stack_set, target)
    if not stack.enabled:
        raise ValueError(f"stack is disabled: {target}")
    components = {(stack.name, component) for component in enabled_components(stack)}
    return TargetScope(raw_target=target, components=frozenset(components), include_sub=False, all_targets=False)


def normalize_target(target: Optional[str]) -> Optional[str]:
    """把显式 all 目标归一为缺省全部目标。"""
    if target == "all":
        return None
    return target


def parse_component_target(target: str) -> tuple[str, str]:
    """解析 `xrelay/name` 或 `clash/name` 形式的组件目标。"""
    component, stack_name = target.split("/", 1)
    if component not in {"xrelay", "clash"} or not stack_name:
        raise ValueError(f"unsupported target: {target}")
    return component, stack_name


def enabled_components(stack: Stack) -> list[str]:
    """返回单个启用 stack 中启用的代理组件。"""
    components: list[str] = []
    if stack.xrelay.enabled:
        components.append("xrelay")
    if stack.clash.enabled:
        components.append("clash")
    return components


def require_stack(stack_set: StackSet, name: str) -> Stack:
    """按名称读取 stack，不存在时抛出面向 CLI 的错误。"""
    stack = stack_set.by_name().get(name)
    if stack is None:
        raise ValueError(f"stack does not exist: {name}")
    return stack


def ensure_component_enabled(stack: Stack, component: str) -> None:
    """校验指定 stack 组件处于可操作状态。"""
    if not stack.enabled:
        raise ValueError(f"stack is disabled: {stack.name}")
    if component == "xrelay" and not stack.xrelay.enabled:
        raise ValueError(f"xrelay is disabled: {stack.name}")
    if component == "clash" and not stack.clash.enabled:
        raise ValueError(f"clash is disabled: {stack.name}")


def includes_component(scope: TargetScope, stack_name: str, component: str) -> bool:
    """判断某个 stack 组件是否包含在当前目标范围内。"""
    return (stack_name, component) in scope.components


def component_service_name(component: str, stack_name: str) -> str:
    """把组件和 stack 名转换为当前约定的 systemd 服务名。"""
    if component == "xrelay":
        return f"proxystack-xray@{stack_name}.service"
    return f"proxystack-{component}@{stack_name}.service"


def build_dependency_plan(stack_set: StackSet, scope: TargetScope) -> Optional[DependencyPlan]:
    """为当前目标范围构建依赖计划；sub 目标没有代理依赖图。"""
    if scope.include_sub and not scope.components:
        return None
    graph = build_reference_graph(stack_set)
    if scope.raw_target is None:
        return graph.build_plan(None)
    if scope.raw_target and "/" not in scope.raw_target:
        return graph.build_plan(scope.raw_target)
    return dependency_plan_for_components(graph, scope)


def dependency_plan_for_components(graph: ReferenceGraph, scope: TargetScope) -> DependencyPlan:
    """为 xrelay/name 或 clash/name 目标计算依赖闭包。"""
    target_nodes = {ServiceNode(stack=stack_name, component=component) for stack_name, component in scope.components}
    plan_nodes = graph.collect_dependency_closure(target_nodes)
    ordered_nodes = graph.topological_order(plan_nodes)
    return DependencyPlan(
        target=scope.raw_target,
        dependency_nodes=[node for node in ordered_nodes if node not in target_nodes],
        dependency_edges=graph.collect_dependency_edges(plan_nodes, ordered_nodes),
        operation_order=ordered_nodes,
    )


def resolve_service_scope(config_path: Path, target: Optional[str], check_system_ports: bool) -> TargetScope:
    """解析服务生命周期命令 target，供 start/stop/status 等命令复用。"""
    target = normalize_target(target)
    config = load_config(config_path)
    if target == "sub":
        return TargetScope(raw_target=target, components=frozenset(), include_sub=True, all_targets=False)
    stack_set = load_stacks(config, check_system_ports=check_system_ports)
    scope = resolve_target_scope(stack_set, target)
    if target is None:
        return TargetScope(
            raw_target=None,
            components=scope.components,
            include_sub=False,
            all_targets=True,
        )
    return scope


def doctor_report(config_path: Path) -> list[str]:
    """执行只读环境检查并返回报告行。"""
    config = load_config(config_path)
    lines = ["Doctor report:"]
    lines.extend(doctor_directory_lines(config))
    lines.extend(doctor_binary_lines(config))
    lines.extend(doctor_systemd_lines())
    lines.extend(doctor_port_lines(config))
    return lines


def doctor_directory_lines(config: GlobalConfig) -> list[str]:
    """检查目录是否存在且当前用户是否可写。"""
    paths = [
        ("base_dir", config.base_dir),
        ("stacks", config.resolve_path(config.paths.stacks)),
        ("runtime", config.resolve_path(config.paths.runtime)),
        ("generated", config.resolve_path(config.paths.generated)),
        ("publish", config.resolve_path(config.paths.publish)),
        ("downloads", config.resolve_path(config.paths.downloads)),
        ("sub", config.resolve_path(config.paths.sub)),
    ]
    lines = ["Directories:"]
    for label, path in paths:
        if not path.exists():
            lines.append(f"  MISSING {label}: {path}")
            continue
        writable = "writable" if os.access(path, os.W_OK) else "not-writable"
        lines.append(f"  OK {label}: {path} ({writable})")
    return lines


def doctor_binary_lines(config: GlobalConfig) -> list[str]:
    """检查代理核心二进制是否存在。"""
    bin_dir = config.resolve_path(config.paths.bin)
    lines = ["Binaries:"]
    for binary_name in ["xray", "mihomo"]:
        path = bin_dir / binary_name
        status = "OK" if path.exists() else "MISSING"
        lines.append(f"  {status} {binary_name}: {path}")
    return lines


def doctor_systemd_lines() -> list[str]:
    """检查 Task09 将要安装的 systemd unit 文件是否存在。"""
    lines = ["Systemd units:"]
    for unit_path in SYSTEMD_UNIT_PATHS:
        status = "OK" if unit_path.exists() else "MISSING"
        lines.append(f"  {status} {unit_path.name}: {unit_path}")
    return lines


def doctor_port_lines(config: GlobalConfig) -> list[str]:
    """检查当前配置声明的监听端口是否被系统占用。"""
    lines = ["Ports:"]
    try:
        stack_set = load_stacks(config, check_system_ports=False)
    except (ValidationError, ValueError) as exc:
        return [*lines, f"  INVALID config: {exc}"]
    for binding in collect_port_bindings(stack_set):
        status = "free" if is_port_available(binding.host, binding.port) else "occupied"
        lines.append(f"  {status} {binding.host}:{binding.port} {binding.path}")
    if len(lines) == 1:
        lines.append("  no ports declared")
    return lines


def edit_config_or_stack(config_path: Path, name: Optional[str], editor: Optional[str], check_only: bool) -> Path:
    """安全编辑 config.yaml 或单个 stack 文件，校验通过后再替换原文件。"""
    target_path = config_path if name is None else load_config(config_path).stacks_dir / f"{name}.yaml"
    if not target_path.exists():
        raise ValueError(f"file does not exist: {target_path}")
    if check_only:
        validate_edit_target(target_path, config_path, name)
        return target_path
    original_text = target_path.read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(original_text)
    try:
        run_editor(editor, temp_path)
        validate_edit_target(temp_path, config_path, name)
        edited_text = temp_path.read_text(encoding="utf-8")
        write_text_if_changed(target_path, edited_text)
    finally:
        temp_path.unlink(missing_ok=True)
    return target_path


def validate_edit_target(path: Path, config_path: Path, name: Optional[str]) -> None:
    """校验编辑后的临时文件不会破坏配置或 stack 结构。"""
    if name is None:
        config = load_config(path)
        if config.config_path != path:
            raise ValueError("invalid config path")
        load_stacks(config, check_system_ports=False)
        return
    stack_data = load_yaml_mapping(path)
    config = load_config(config_path)
    target_path = config.stacks_dir / f"{name}.yaml"
    stack = validate_stack_document(stack_data, name, target_path)
    validate_stack_in_project(config, stack, replace_existing=True)


def run_editor(editor: Optional[str], path: Path) -> None:
    """调用用户指定或环境变量中的编辑器，避免 shell 拼接命令。"""
    command = shlex.split(editor or os.environ.get("EDITOR", "vi"))
    if not command:
        raise ValueError("editor command is empty")
    result = subprocess.run([*command, str(path)], check=False)
    if result.returncode != 0:
        raise ValueError(f"editor exited with code {result.returncode}")


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """读取 YAML 文件并要求顶层是 mapping。"""
    yaml = YAML(typ="safe")
    with path.open("r", encoding="utf-8") as yaml_file:
        loaded = yaml.load(yaml_file)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML file must be a mapping: {path}")
    return loaded


def load_yaml_text(content: str) -> dict[str, Any]:
    """从 YAML 文本读取 mapping，供内置模板加载使用。"""
    yaml = YAML()
    loaded = yaml.load(content)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("YAML content must be a mapping")
    return loaded


def write_yaml_if_changed(path: Path, value: dict[str, Any]) -> bool:
    """把 YAML mapping 写入文件，内容一致时不改 mtime。"""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
        yaml.dump(value, temp_file)
    try:
        content = temp_path.read_text(encoding="utf-8")
    finally:
        temp_path.unlink(missing_ok=True)
    return write_text_if_changed(path, content)


def write_manifest_if_changed(path: Path, manifest: dict[str, Any]) -> bool:
    """把 manifest 以稳定 JSON 写入文件，内容一致时不改 mtime。"""
    content = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return write_text_if_changed(path, content)


def write_text_if_changed(path: Path, content: str, force: bool = True) -> bool:
    """按内容比较后原子写入文本文件，避免无意义更新时间。"""
    if path.exists() and not force:
        ensure_managed_file_metadata(path)
        return False
    return write_bytes_if_changed(path, content.encode("utf-8"))


def write_bytes_if_changed(path: Path, content: bytes) -> bool:
    """按内容比较后原子写入二进制文件。"""
    if path.exists() and path.read_bytes() == content:
        ensure_managed_directory(path.parent)
        ensure_managed_file_metadata(path)
        return False
    ensure_managed_directory(path.parent)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=path.parent) as temp_file:
        temp_path = Path(temp_file.name)
        try:
            temp_file.write(content)
            temp_file.flush()
            ensure_managed_file_metadata(temp_path)
            temp_path.replace(path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
    ensure_managed_file_metadata(path)
    return True


def file_sha256(path: Path) -> str:
    """计算文件 sha256 摘要。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()
