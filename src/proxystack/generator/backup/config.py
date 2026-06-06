"""原生 agent 配置备份包读写与校验。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Literal
from zipfile import ZIP_DEFLATED
from zipfile import BadZipFile
from zipfile import ZipFile
from zipfile import ZipInfo
import hashlib
import json

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from pydantic import field_validator
from pydantic import model_validator
from ruamel.yaml import YAML

from proxystack.config import load_config
from proxystack.config import load_stacks
from proxystack.domain.models import GlobalConfig
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.domain.validation import ConfigValidationError
from proxystack.domain.validation import ValidationIssue
from proxystack.domain.validation import validate_stack_set

BACKUP_SCHEMA = "proxystack.native-backup"
BACKUP_VERSION = 1
CONFIG_MEMBER = "config/config.yaml"
MANIFEST_MEMBER = "manifest.json"


class NativeBackupError(ValueError):
    """原生 agent 配置备份包生成、读取或校验失败。"""


@dataclass(frozen=True)
class NativeBackupFile:
    """表示导入计划中的单个 stack 文件。"""

    name: str
    content: bytes


@dataclass(frozen=True)
class NativeBackupPlan:
    """表示已校验完成、可写入目标 agent 目录的备份内容。"""

    config: GlobalConfig
    config_content: bytes
    stack_files: list[NativeBackupFile]


class NativeBackupManifest(BaseModel):
    """原生 agent 配置备份包 manifest，用于区分订阅发布包并校验文件完整性。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    backup_schema: Literal["proxystack.native-backup"]
    backup_version: Literal[1]
    created_at: str = Field(min_length=1)
    files_sha256: dict[str, str]

    @model_validator(mode="before")
    @classmethod
    def validate_schema_metadata(cls, value: Any) -> Any:
        """校验备份包 schema 和版本，避免和订阅发布包混用。"""
        if not isinstance(value, dict):
            return value
        backup_schema = value.get("backup_schema")
        if backup_schema != BACKUP_SCHEMA:
            raise ValueError(f"unsupported native backup schema: {backup_schema}")
        backup_version = value.get("backup_version")
        if backup_version is not None and (type(backup_version) is not int or backup_version != BACKUP_VERSION):
            raise ValueError(f"unsupported native backup version: {backup_version}")
        return value

    @field_validator("files_sha256")
    @classmethod
    def validate_files_sha256(cls, files_sha256: dict[str, str]) -> dict[str, str]:
        """校验 manifest 中的文件路径和 sha256 摘要格式。"""
        for name, digest in files_sha256.items():
            validate_backup_file_member_name(name)
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError(f"invalid file sha256 for {name}")
        return files_sha256


def now_iso() -> str:
    """返回带本地时区的秒级 ISO 时间戳。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_native_backup(output_path: Path, config_path: Path) -> NativeBackupManifest:
    """从当前 agent config 和 stacks 写出原生备份 zip。"""
    backup_files = collect_backup_files(config_path)
    manifest = NativeBackupManifest(
        backup_schema=BACKUP_SCHEMA,
        backup_version=BACKUP_VERSION,
        created_at=now_iso(),
        files_sha256={name: sha256_bytes(content) for name, content in backup_files},
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as zip_file:
        zip_file.writestr(MANIFEST_MEMBER, json.dumps(manifest.model_dump(mode="json"), indent=2))
        for name, content in backup_files:
            zip_file.writestr(name, content)
    return manifest


def collect_backup_files(config_path: Path) -> list[tuple[str, bytes]]:
    """收集原生备份允许包含的 config.yaml 和 stacks/*.yaml。"""
    config = load_config(config_path)
    load_stacks(config, check_system_ports=False)
    backup_files = [(CONFIG_MEMBER, config_path.read_bytes())]
    for stack_path in sorted(config.stacks_dir.glob("*.yaml"), key=lambda path: path.name):
        backup_files.append((f"stacks/{stack_path.name}", stack_path.read_bytes()))
    return backup_files


def read_native_backup(backup_path: Path, base_dir: Path) -> NativeBackupPlan:
    """读取并校验原生备份 zip，返回可写入目标目录的导入计划。"""
    try:
        zip_file = ZipFile(backup_path, "r")
    except BadZipFile as exc:
        raise NativeBackupError(f"invalid native backup zip: {backup_path}") from exc
    with zip_file:
        validate_backup_members(zip_file)
        manifest = load_manifest_from_zip(zip_file)
        file_members = read_manifest_files(zip_file, manifest)
        validate_file_hashes(file_members, manifest)
        config_content = rewrite_config_base_dir(file_members[CONFIG_MEMBER], base_dir)
        stack_files = [
            NativeBackupFile(Path(name).name, content)
            for name, content in sorted(file_members.items())
            if name.startswith("stacks/")
        ]
        config, _stacks = validate_backup_models(config_content, stack_files)
    return NativeBackupPlan(config=config, config_content=config_content, stack_files=stack_files)


def validate_backup_members(zip_file: ZipFile) -> None:
    """校验 zip 成员路径都属于原生备份包允许范围。"""
    for member in zip_file.infolist():
        validate_backup_member(member)


def validate_backup_member(member: ZipInfo) -> None:
    """校验单个 zip 成员路径安全，拒绝路径穿越和未知目录。"""
    name = member.filename
    path = Path(name)
    if name.startswith("/") or "\\" in name or ".." in path.parts:
        raise NativeBackupError(f"unsafe native backup path: {name}")
    if name == MANIFEST_MEMBER:
        return
    if member.is_dir() and name in {"config/", "stacks/"}:
        return
    validate_backup_file_member_name(name)


def validate_backup_file_member_name(name: str) -> None:
    """校验 manifest 或 zip 中的备份文件路径属于允许集合。"""
    path = Path(name)
    if name == CONFIG_MEMBER:
        return
    if name.startswith("stacks/") and len(path.parts) == 2 and path.suffix == ".yaml" and path.name == path.parts[1]:
        if path.stem.startswith((".", "-")):
            raise NativeBackupError(f"unsafe native backup file: {name}")
        return
    raise NativeBackupError(f"unexpected native backup path: {name}")


def load_manifest_from_zip(zip_file: ZipFile) -> NativeBackupManifest:
    """从备份 zip 读取并校验 manifest。"""
    try:
        manifest_data = json.loads(zip_file.read(MANIFEST_MEMBER).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise NativeBackupError("native backup manifest is missing or invalid") from exc
    try:
        return NativeBackupManifest.model_validate(manifest_data)
    except (ValidationError, ValueError) as exc:
        raise NativeBackupError(f"native backup manifest schema is invalid: {exc}") from exc


def read_manifest_files(zip_file: ZipFile, manifest: NativeBackupManifest) -> dict[str, bytes]:
    """按 manifest 读取备份文件，并确认 zip 文件集合完全匹配。"""
    actual_file_names = {
        member.filename
        for member in zip_file.infolist()
        if not member.is_dir() and member.filename != MANIFEST_MEMBER
    }
    expected_file_names = set(manifest.files_sha256)
    if actual_file_names != expected_file_names:
        raise NativeBackupError("native backup files do not match manifest")
    if CONFIG_MEMBER not in expected_file_names:
        raise NativeBackupError("native backup config is missing")
    try:
        return {name: zip_file.read(name) for name in manifest.files_sha256}
    except KeyError as exc:
        raise NativeBackupError("native backup file is missing") from exc


def validate_file_hashes(file_members: dict[str, bytes], manifest: NativeBackupManifest) -> None:
    """校验备份文件内容 sha256 与 manifest 一致。"""
    for name, content in file_members.items():
        actual_hash = sha256_bytes(content)
        if actual_hash != manifest.files_sha256[name]:
            raise NativeBackupError(f"file hash mismatch: {name}")


def rewrite_config_base_dir(config_content: bytes, base_dir: Path) -> bytes:
    """把导入目标 base_dir 写入 config.yaml 内容。"""
    config_data = load_yaml_mapping_text(config_content.decode("utf-8"), CONFIG_MEMBER)
    config_data["base_dir"] = str(base_dir)
    return dump_yaml(config_data).encode("utf-8")


def validate_backup_models(config_content: bytes, stack_files: list[NativeBackupFile]) -> tuple[GlobalConfig, list[Stack]]:
    """校验导入后的 config 和 stacks 可组成合法 StackSet。"""
    try:
        config = GlobalConfig.model_validate(load_yaml_mapping_text(config_content.decode("utf-8"), CONFIG_MEMBER))
        stacks = [load_stack_content(stack_file) for stack_file in stack_files]
        validate_stack_set(StackSet(config=config, stacks=stacks), check_system_ports=False)
    except (UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise NativeBackupError(f"invalid native backup config or stack: {exc}") from exc
    return config, stacks


def load_stack_content(stack_file: NativeBackupFile) -> Stack:
    """读取并校验单个备份 stack 文件内容。"""
    try:
        stack = Stack.model_validate(load_yaml_mapping_text(stack_file.content.decode("utf-8"), stack_file.name))
    except (UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise NativeBackupError(f"invalid native backup stack {stack_file.name}: {exc}") from exc
    if Path(stack_file.name).stem != stack.name:
        raise ConfigValidationError(
            [
                ValidationIssue(
                    path=f"stacks.{stack_file.name}.name",
                    message=f"stack name must match file name: {Path(stack_file.name).stem}",
                )
            ]
        )
    return stack


def load_yaml_mapping_text(text: str, label: str) -> dict[str, Any]:
    """读取 YAML 文本并要求顶层是 mapping。"""
    yaml = YAML(typ="safe")
    loaded = yaml.load(text)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML file must be a mapping: {label}")
    return loaded


def dump_yaml(value: dict[str, Any]) -> str:
    """把字典编码为稳定、可读的 YAML 文本。"""
    from io import StringIO

    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    stream = StringIO()
    yaml.dump(value, stream)
    return stream.getvalue()


def sha256_bytes(content: bytes) -> str:
    """计算字节内容的 sha256 十六进制摘要。"""
    return hashlib.sha256(content).hexdigest()
