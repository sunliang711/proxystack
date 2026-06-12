"""Task11 CLI 命令矩阵增量测试。"""

from pathlib import Path

from typer.testing import CliRunner

from proxystack.cli.agent import app as agent_app
from proxystack.cli.sub import app as sub_app
from proxystack.generator.sub import write_bundle

runner = CliRunner()


def test_agent_and_sub_p0_subcommand_help_matrix() -> None:
    """验证 Task11 补充的 P0 子命令都有 help 输出。"""
    commands = [
        (agent_app, ["sub"]),
        (agent_app, ["sub", "export"]),
        (agent_app, ["sub", "validate-inputs"]),
        (sub_app, ["import"]),
        (sub_app, ["serve"]),
    ]

    for app, command in commands:
        result = runner.invoke(app, [*command, "--help"])

        assert result.exit_code == 0, command


def test_validate_missing_stack_is_failure_path() -> None:
    """验证 validate 对不存在 stack 提供失败路径覆盖。"""
    result = runner.invoke(agent_app, ["validate", "missing", "-c", "examples/config.yaml", "--skip-system-ports"])

    assert result.exit_code == 1
    assert "stack does not exist: missing" in result.output


def test_sub_import_writes_input_atomically_without_current(tmp_path: Path) -> None:
    """验证 import 原子写入 input，不生成 current 或 access 元数据。"""
    bundle = tmp_path / "bundle.zip"
    data_dir = tmp_path / "sub"
    fixture = Path("tests/fixtures/sub/manual.yaml")
    write_bundle(bundle, "manual", [(fixture.name, fixture.read_bytes())])

    import_result = runner.invoke(sub_app, ["import", str(bundle), "--data-dir", str(data_dir)])

    assert import_result.exit_code == 0
    assert (data_dir / "inputs" / "manual.yaml").exists()
    assert not (data_dir / "bundles" / "access.json").exists()
    assert not (data_dir / "current" / "index.json").exists()
