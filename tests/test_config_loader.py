"""配置加载入口测试。"""

from pathlib import Path

import pytest

from proxystack.config import load_config_file


def test_load_config_file_reads_yaml_mapping() -> None:
    """验证示例全局配置可以读取为字典。"""
    config = load_config_file(Path("examples/config.yaml"))

    assert config["version"] == 1
    assert config["base_dir"] == "./examples"


def test_load_config_file_rejects_non_mapping(tmp_path: Path) -> None:
    """验证配置文件顶层不是映射时会失败。"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("- invalid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Config file must be a mapping"):
        load_config_file(config_path)
