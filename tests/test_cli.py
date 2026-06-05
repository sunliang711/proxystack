"""CLI 骨架测试。"""

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
