"""Task11 CLI 命令矩阵增量测试。"""

from pathlib import Path

from pytest import MonkeyPatch
from typer.testing import CliRunner

import proxystack.cli.sub as sub_module
from proxystack.cli.agent import app as agent_app
from proxystack.cli.sub import app as sub_app
from proxystack.generator.sub import SubscriptionAccess
from proxystack.generator.sub import write_bundle

runner = CliRunner()


def test_agent_and_sub_p0_subcommand_help_matrix() -> None:
    """验证 Task11 补充的 P0 子命令都有 help 输出。"""
    commands = [
        (agent_app, ["sub"]),
        (agent_app, ["sub", "export-input"]),
        (agent_app, ["sub", "validate-inputs"]),
        (sub_app, ["import"]),
        (sub_app, ["rebuild"]),
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


def test_sub_import_no_rebuild_then_rebuild_atomic_switch(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证 import --no-rebuild 跳过 current，rebuild 使用原子替换写入。"""
    bundle = tmp_path / "bundle.zip"
    data_dir = tmp_path / "sub"
    fixture = Path("tests/fixtures/sub/manual.yaml")
    write_bundle(bundle, "manual", [(fixture.name, fixture.read_bytes())], access=SubscriptionAccess(type="token", token="demo-token"))

    import_result = runner.invoke(sub_app, ["import", str(bundle), "--data-dir", str(data_dir), "--no-rebuild"])

    assert import_result.exit_code == 0
    assert (data_dir / "inputs" / "manual.yaml").exists()
    assert (data_dir / "bundles" / "access.json").exists()
    assert not (data_dir / "current" / "index.json").exists()

    replace_calls: list[tuple[Path, Path]] = []
    real_replace = sub_module.os.replace

    def recording_replace(source: object, target: object) -> None:
        """记录 os.replace 调用，并继续执行真实原子替换。"""
        source_path = Path(source)
        target_path = Path(target)
        assert source_path.name == "index.json.tmp"
        assert target_path.name == "index.json"
        assert source_path.exists()
        replace_calls.append((source_path, target_path))
        real_replace(source, target)

    monkeypatch.setattr(sub_module.os, "replace", recording_replace)

    rebuild_result = runner.invoke(sub_app, ["rebuild", "--data-dir", str(data_dir)])

    assert rebuild_result.exit_code == 0
    assert replace_calls == [(data_dir / "current" / "index.json.tmp", data_dir / "current" / "index.json")]
    assert not (data_dir / "current" / "index.json.tmp").exists()
