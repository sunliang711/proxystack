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


def test_agent_validate_examples() -> None:
    """验证 proxystack-agent validate 可以校验示例配置。"""
    result = runner.invoke(agent_app, ["validate", "-c", "examples/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    assert "配置校验通过" in result.output


def test_agent_plan_examples() -> None:
    """验证 proxystack-agent plan 可以展示依赖和顺序。"""
    result = runner.invoke(agent_app, ["plan", "-c", "examples/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 0
    assert "依赖服务" in result.output
    assert "建议操作顺序" in result.output
    assert "auto.clash" in result.output
    assert "proxystack-xray@usa1.service" in result.output


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
