"""配置文件加载基础能力。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from proxystack.domain.models import GlobalConfig
from proxystack.domain.models import Stack
from proxystack.domain.models import StackSet
from proxystack.domain.validation import ConfigValidationError
from proxystack.domain.validation import ValidationIssue
from proxystack.domain.validation import validate_stack_set

DEFAULT_CONFIG_PATH = Path("/opt/proxystack/config.yaml")


def load_config_file(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """读取 YAML 配置文件并返回映射，供模型加载和测试复用。"""
    return _load_yaml_mapping(path, "Config file")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> GlobalConfig:
    """读取全局配置文件并构建强类型模型。"""
    config = GlobalConfig.model_validate(load_config_file(path))
    config.config_path = path
    return config


def load_stack(path: Path) -> Stack:
    """读取单个 stack 文件并构建强类型模型。"""
    stack = Stack.model_validate(_load_yaml_mapping(path, "Stack file"))
    stack.source_path = path
    if path.stem != stack.name:
        raise ConfigValidationError(
            [
                ValidationIssue(
                    path=f"stacks.{path.name}.name",
                    message=f"stack name must match file name: {path.stem}",
                )
            ]
        )
    return stack


def load_stacks(config: GlobalConfig, check_system_ports: bool = True) -> StackSet:
    """读取全局配置指定目录下的所有 stack 文件并执行跨文件校验。"""
    stack_paths = sorted(config.stacks_dir.glob("*.yaml"))
    stacks: list[Stack] = []
    for stack_path in stack_paths:
        try:
            stacks.append(load_stack(stack_path))
        except ValidationError as exc:
            raise ValueError(f"Invalid stack file: {stack_path}\n{exc}") from exc
    stack_set = StackSet(config=config, stacks=stacks)
    validate_stack_set(stack_set, check_system_ports=check_system_ports)
    return stack_set


def _load_yaml_mapping(path: Path, label: str) -> dict[str, Any]:
    """读取 YAML 文件并确保顶层是 mapping。"""
    yaml = YAML(typ="safe")
    try:
        with path.open("r", encoding="utf-8") as config_file:
            loaded_config = yaml.load(config_file)
    except OSError as exc:
        raise ValueError(f"{label} could not be read: {path} ({exc})") from exc
    except YAMLError as exc:
        raise ValueError(f"{label} contains invalid YAML: {path}\n{exc}") from exc
    if loaded_config is None:
        return {}
    if not isinstance(loaded_config, dict):
        raise ValueError(f"{label} must be a mapping: {path}")
    return loaded_config
