"""Task11 配置矩阵增量测试。"""

from pathlib import Path
from typing import Any

from pydantic import ValidationError
import pytest
from ruamel.yaml import YAML

from proxystack.config import load_stack
from proxystack.domain.models import GlobalConfig
from proxystack.domain.models import Stack


def test_examples_stack_files_load_individually() -> None:
    """验证 examples/stacks 下每个示例 stack 文件都能独立加载。"""
    stack_paths = sorted(Path("examples/stacks").glob("*.yaml"))

    stacks = [load_stack(stack_path) for stack_path in stack_paths]

    assert [stack.name for stack in stacks] == [stack_path.stem for stack_path in stack_paths]


def test_global_config_rejects_missing_subscription_token() -> None:
    """验证 token 鉴权缺少 token 时全局配置校验失败。"""
    config_data = load_yaml(Path("examples/config.yaml"))
    config_data["subscription"]["access"]["token"] = ""

    with pytest.raises(ValidationError, match="token is required"):
        GlobalConfig.model_validate(config_data)


def test_stack_rejects_missing_published_socks_password() -> None:
    """验证发布 socks/http 节点缺少密码鉴权字段时失败。"""
    stack_data = load_yaml(Path("examples/stacks/usa1.yaml"))
    stack_data["xrelay"]["inbounds"][0]["auth"].pop("password")

    with pytest.raises(ValidationError, match="username and password are required"):
        Stack.model_validate(stack_data)


def test_stack_rejects_missing_raw_vmess_uuid() -> None:
    """验证 raw vmess upstream 缺少 uuid 时失败。"""
    stack_data = load_yaml(Path("examples/stacks/usa1.yaml"))
    stack_data["clash"]["upstreams"][0]["config"].pop("uuid")

    with pytest.raises(ValidationError, match="raw vmess upstream uuid is required"):
        Stack.model_validate(stack_data)


def load_yaml(path: Path) -> dict[str, Any]:
    """读取测试 YAML 并返回 mapping。"""
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))
