"""Task11 订阅 golden 测试。"""

from pathlib import Path
import shutil

from pytest import MonkeyPatch

import proxystack.generator.sub.config as sub_config
from proxystack.generator.sub import SubscriptionAccess
from proxystack.generator.sub import index_to_json
from proxystack.generator.sub import merge_input_files

FIXTURE_DIR = Path("tests/fixtures/sub")
GOLDEN_DIR = Path("tests/golden/sub")


def test_subscription_index_matches_golden(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """验证订阅 inputs 合并后的 index JSON 与 golden 快照一致。"""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    shutil.copy2(FIXTURE_DIR / "manual.yaml", input_dir / "manual.yaml")
    monkeypatch.setattr(sub_config, "now_iso", lambda: "2026-06-05T12:00:00+08:00")

    index = merge_input_files(input_dir, access=SubscriptionAccess(type="token", token="demo-token"))

    assert index_to_json(index) == (GOLDEN_DIR / "index.json").read_text(encoding="utf-8")
