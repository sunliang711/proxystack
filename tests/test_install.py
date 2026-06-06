"""安装与更新命令测试。"""

import hashlib
import gzip
from pathlib import Path
from typing import Optional
from typing import Sequence
from zipfile import ZipFile

import pytest
from ruamel.yaml import YAML
from typer.testing import CliRunner

from proxystack.cli.agent import app as agent_app
from proxystack.config import load_config
from proxystack.install import CommandResult
from proxystack.install import InstallRequest
from proxystack.install import SelfUpdateRequest
from proxystack.install import build_install_request
from proxystack.install import detect_component_version
from proxystack.install import install_artifact
from proxystack.install import run_self_update
from proxystack.install.service import atomic_replace_file
from proxystack.install.service import download_url_with_opener
from proxystack.install.service import file_sha256
from proxystack.install.service import validate_download_url

runner = CliRunner()


def test_install_mihomo_from_local_file(tmp_path: Path) -> None:
    """验证 CLI 可以从本地文件安装 mihomo 并设置可执行权限。"""
    config = write_install_config(tmp_path)
    source = write_source(tmp_path / "sources" / "mihomo.bin", b"mihomo-binary")

    result = runner.invoke(
        agent_app,
        ["install", "mihomo", "--source", str(source), "--sha256", file_sha256(source), "-c", str(config)],
    )

    installed = config.parent / "bin" / "mihomo"
    assert result.exit_code == 0
    assert installed.read_bytes() == b"mihomo-binary"
    assert installed.parent.stat().st_mode & 0o777 == 0o750
    assert installed.stat().st_mode & 0o777 == 0o750


def test_install_cli_reports_progress_for_local_file(tmp_path: Path) -> None:
    """验证 install CLI 会输出准备、来源、校验和安装进度。"""
    config = write_install_config(tmp_path)
    source = write_source(tmp_path / "sources" / "mihomo.bin", b"mihomo-binary")

    result = runner.invoke(
        agent_app,
        ["install", "mihomo", "--source", str(source), "--sha256", file_sha256(source), "-c", str(config)],
    )

    assert result.exit_code == 0
    assert "install: prepare mihomo" in result.output
    assert "source: local file" in result.output
    assert "install: verify mihomo.bin" in result.output
    assert "install: complete mihomo" in result.output


def test_install_xray_uses_fake_downloader(tmp_path: Path) -> None:
    """验证服务层支持 fake downloader，不依赖真实网络。"""
    config = write_install_config(tmp_path)
    global_config = load_config(config)
    payload = b"xray-binary"
    payload_sha256 = sha256_bytes(payload)
    downloaded_paths: list[Path] = []

    def fake_downloader(source: str, destination: Path) -> Path:
        """写入测试内容并记录缓存路径。"""
        destination.write_bytes(payload)
        downloaded_paths.append(destination)
        return destination

    result = install_artifact(
        global_config,
        InstallRequest(target="xray", version="v1.0.0", source="https://example.com/xray", sha256=payload_sha256),
        downloader=fake_downloader,
    )

    assert result.installed_paths == (config.parent / "bin" / "xray",)
    assert result.installed_paths[0].read_bytes() == payload
    assert downloaded_paths == [config.parent / "downloads" / "xray"]


def test_install_auto_source_falls_back_to_r2_and_extracts_gzip(tmp_path: Path) -> None:
    """验证托管下载源会在 GitHub 失败后回退到 R2，并解压 mihomo gzip。"""
    config = write_install_config(tmp_path)
    global_config = load_config(config)
    payload = b"mihomo-binary"
    compressed_payload = gzip.compress(payload)
    downloaded_sources: list[str] = []

    def fake_downloader(source: str, destination: Path) -> Path:
        """模拟 GitHub 失败、R2 成功下载 gzip 文件。"""
        downloaded_sources.append(source)
        if "github.com" in source:
            raise OSError("github failed")
        destination.write_bytes(compressed_payload)
        return destination

    result = install_artifact(
        global_config,
        InstallRequest(target="mihomo", version="v1.2.3", source="auto"),
        downloader=fake_downloader,
    )

    assert result.installed_paths == (config.parent / "bin" / "mihomo",)
    assert result.installed_paths[0].read_bytes() == payload
    assert downloaded_sources == [
        "https://github.com/MetaCubeX/mihomo/releases/download/v1.2.3/mihomo-linux-amd64-compatible-v1.2.3.gz",
        "https://pub-06197a088952412f8ff879716ee84855.r2.dev/mihomo/v1.2.3/mihomo-linux-amd64-compatible-v1.2.3.gz",
    ]


def test_install_auto_latest_uses_r2_latest_version_when_github_download_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 latest 自动回退时使用 R2 当前可用版本。"""
    config = write_install_config(tmp_path)
    global_config = load_config(config)
    payload = b"mihomo-r2-latest"
    compressed_payload = gzip.compress(payload)
    downloaded_sources: list[str] = []

    monkeypatch.setattr("proxystack.install.service.github_latest_version", lambda target: "1.2.4")
    monkeypatch.setattr("proxystack.install.service.r2_latest_version", lambda target: "1.2.3")

    def fake_downloader(source: str, destination: Path) -> Path:
        """模拟 GitHub 最新版本下载失败、R2 latest 成功。"""
        downloaded_sources.append(source)
        if "github.com" in source:
            raise OSError("github failed")
        destination.write_bytes(compressed_payload)
        return destination

    result = install_artifact(
        global_config,
        InstallRequest(target="mihomo", version="latest", source="auto"),
        downloader=fake_downloader,
    )

    assert result.installed_paths[0].read_bytes() == payload
    assert downloaded_sources == [
        "https://github.com/MetaCubeX/mihomo/releases/download/v1.2.4/mihomo-linux-amd64-compatible-v1.2.4.gz",
        "https://pub-06197a088952412f8ff879716ee84855.r2.dev/mihomo/latest/mihomo-linux-amd64-compatible-v1.2.3.gz",
    ]


def test_install_mihomo_defaults_to_auto_source(tmp_path: Path) -> None:
    """验证 mihomo 未配置 source 时默认使用托管自动源。"""
    config = write_install_config(tmp_path, {"mihomo": {"version": "v1.2.3"}})
    global_config = load_config(config)

    built_request = build_install_request(
        global_config,
        "mihomo",
        None,
        None,
        None,
        None,
    )

    assert built_request.source == "auto"
    assert built_request.version == "v1.2.3"


def test_install_geo_defaults_to_auto_source(tmp_path: Path) -> None:
    """验证 geo 未配置 source 时默认使用托管自动源。"""
    config = write_install_config(tmp_path, {"geo": {"version": "latest"}})
    global_config = load_config(config)

    built_request = build_install_request(
        global_config,
        "geo",
        None,
        None,
        None,
        None,
    )

    assert built_request.source == "auto"
    assert built_request.version == "latest"


def test_install_geo_auto_source_falls_back_to_r2_and_installs_metadb(tmp_path: Path) -> None:
    """验证 geo 托管源沿用 clash 的 geoip.metadb 规则，并可回退到 R2。"""
    config = write_install_config(tmp_path)
    global_config = load_config(config)
    payload = b"geoip-metadb"
    downloaded_sources: list[str] = []

    def fake_downloader(source: str, destination: Path) -> Path:
        """模拟 GitHub 失败、R2 成功下载 geoip.metadb。"""
        downloaded_sources.append(source)
        if "github.com" in source:
            raise OSError("github failed")
        destination.write_bytes(payload)
        return destination

    result = install_artifact(
        global_config,
        InstallRequest(target="geo", version="latest", source="auto"),
        downloader=fake_downloader,
    )

    assert result.installed_paths == (config.parent / "geo" / "geoip.metadb",)
    assert result.installed_paths[0].read_bytes() == payload
    assert result.installed_paths[0].stat().st_mode & 0o777 == 0o640
    assert downloaded_sources == [
        "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb",
        "https://pub-06197a088952412f8ff879716ee84855.r2.dev/mmdb/latest/geoip.metadb",
    ]


def test_download_url_rejects_private_ip() -> None:
    """验证下载 URL 拒绝本机和私网 IP。"""
    with pytest.raises(ValueError, match="private or local"):
        validate_download_url("https://127.0.0.1/xray.zip", resolve_dns=False)


def test_download_url_reports_byte_progress(tmp_path: Path) -> None:
    """验证真实下载循环会输出字节进度，避免长时间静默。"""
    payload = b"x" * (6 * 1024 * 1024)
    destination = tmp_path / "downloads" / "xray.zip"
    destination.parent.mkdir()
    messages: list[str] = []

    result = download_url_with_opener(
        "https://example.com/xray.zip",
        destination,
        FakeOpener(payload),
        progress=messages.append,
    )

    assert result == destination
    assert destination.read_bytes() == payload
    assert messages[0].startswith("download: start xray.zip")
    assert any(message.startswith("download: progress xray.zip") for message in messages)
    assert messages[-1].startswith("download: complete xray.zip")


def test_download_requires_sha256_before_downloader_runs(tmp_path: Path) -> None:
    """验证远端下载缺少 sha256 时在调用 downloader 前失败。"""
    config = write_install_config(tmp_path)
    global_config = load_config(config)
    called = False

    def fake_downloader(source: str, destination: Path) -> Path:
        """如果被调用则说明 sha256 防线时机错误。"""
        nonlocal called
        called = True
        destination.write_bytes(b"payload")
        return destination

    with pytest.raises(ValueError, match="sha256 is required"):
        install_artifact(
            global_config,
            InstallRequest(target="xray", version="v1.0.0", source="https://example.com/xray"),
            downloader=fake_downloader,
        )

    assert called is False
    assert not (config.parent / "downloads").exists()


def test_geo_archive_replace_failure_restores_previous_files(tmp_path: Path) -> None:
    """验证 geo 多文件归档替换失败时恢复所有既有文件。"""
    config = write_install_config(tmp_path)
    global_config = load_config(config)
    geo_dir = config.parent / "geo"
    geo_dir.mkdir(parents=True)
    (geo_dir / "geo.dat").write_bytes(b"old-dat")
    (geo_dir / "geo.mmdb").write_bytes(b"old-mmdb")
    archive = tmp_path / "sources" / "geo.zip"
    write_zip(archive, {"geo.dat": b"new-dat", "geo.mmdb": b"new-mmdb"})
    calls = 0

    def failing_second_replacer(source_path: Path, destination: Path, mode: int) -> None:
        """第二个文件替换失败，用于验证事务回滚。"""
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("replace failed")
        atomic_replace_file(source_path, destination, mode)

    with pytest.raises(OSError, match="replace failed"):
        install_artifact(
            global_config,
            InstallRequest(target="geo", version="latest", source=str(archive), sha256=file_sha256(archive)),
            replacer=failing_second_replacer,
        )

    assert (geo_dir / "geo.dat").read_bytes() == b"old-dat"
    assert (geo_dir / "geo.mmdb").read_bytes() == b"old-mmdb"


def test_archive_member_rejects_path_traversal(tmp_path: Path) -> None:
    """验证归档成员路径穿越会在写入目标前失败。"""
    config = write_install_config(tmp_path)
    global_config = load_config(config)
    archive = tmp_path / "sources" / "bad-geo.zip"
    write_zip(archive, {"../evil.dat": b"evil"})

    with pytest.raises(ValueError, match="unsafe archive member"):
        install_artifact(
            global_config,
            InstallRequest(target="geo", version="latest", source=str(archive), sha256=file_sha256(archive)),
        )

    assert not (tmp_path / "sources" / "evil.dat").exists()
    assert not (config.parent / "geo" / "evil.dat").exists()


def test_install_sha256_failure_does_not_write_target(tmp_path: Path) -> None:
    """验证 sha256 不匹配时拒绝安装且不写目标文件。"""
    config = write_install_config(tmp_path)
    source = write_source(tmp_path / "sources" / "mihomo.bin", b"bad-hash")

    result = runner.invoke(
        agent_app,
        ["install", "mihomo", "--source", str(source), "--sha256", "0" * 64, "-c", str(config)],
    )

    assert result.exit_code == 1
    assert "sha256 mismatch" in result.output
    assert not (config.parent / "bin" / "mihomo").exists()


def test_replace_failure_keeps_existing_binary(tmp_path: Path) -> None:
    """验证替换异常时不会破坏已有二进制。"""
    config = write_install_config(tmp_path)
    global_config = load_config(config)
    source = write_source(tmp_path / "sources" / "mihomo.bin", b"new")
    installed = config.parent / "bin" / "mihomo"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"old")

    def failing_replacer(source_path: Path, destination: Path, mode: int) -> None:
        """模拟原子替换前失败。"""
        raise OSError("replace failed")

    with pytest.raises(OSError, match="replace failed"):
        install_artifact(
            global_config,
            InstallRequest(target="mihomo", version="v1.0.0", source=str(source), sha256=file_sha256(source)),
            replacer=failing_replacer,
        )

    assert installed.read_bytes() == b"old"


def test_self_update_uses_fake_runner(tmp_path: Path) -> None:
    """验证 self update 只调用 venv 内 python -m pip install --upgrade。"""
    config = write_install_config(tmp_path)
    global_config = load_config(config)
    venv_python = config.parent / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    wheel = write_source(tmp_path / "dist" / "proxystack-0.2.0-py3-none-any.whl", b"wheel")
    calls: list[tuple[str, ...]] = []

    def fake_runner(args: Sequence[str]) -> CommandResult:
        """记录 pip 调用并返回成功结果。"""
        calls.append(tuple(args))
        return CommandResult(args=tuple(args), returncode=0)

    result = run_self_update(
        global_config,
        SelfUpdateRequest(wheel=wheel, sha256=file_sha256(wheel)),
        runner=fake_runner,
    )

    assert result.returncode == 0
    assert calls == [(str(venv_python), "-m", "pip", "install", "--upgrade", str(wheel))]


def test_detect_mihomo_version_uses_short_version_flag(tmp_path: Path) -> None:
    """验证 mihomo 版本检测使用 -v，避免误触发核心启动。"""
    config = write_install_config(tmp_path)
    global_config = load_config(config)
    mihomo = config.parent / "bin" / "mihomo"
    mihomo.parent.mkdir(parents=True)
    mihomo.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def fake_runner(args: Sequence[str]) -> CommandResult:
        """记录版本检测命令并返回成功结果。"""
        calls.append(tuple(args))
        return CommandResult(args=tuple(args), returncode=0, stdout="Mihomo Meta v1")

    result = detect_component_version(global_config, "mihomo", runner=fake_runner)

    assert result.status == "ok"
    assert result.output == "Mihomo Meta v1"
    assert calls == [(str(mihomo), "-v")]


def test_install_all_does_not_include_self(tmp_path: Path) -> None:
    """验证 install all 只安装 mihomo、xray 和 geo。"""
    config = write_config_with_sources(tmp_path)

    result = runner.invoke(agent_app, ["install", "all", "-c", str(config)])

    assert result.exit_code == 0
    assert (config.parent / "bin" / "mihomo").exists()
    assert (config.parent / "bin" / "xray").exists()
    assert (config.parent / "geo" / "geo.dat").exists()
    assert "self" not in result.output
    assert "systemd" not in result.output


def test_update_all_does_not_include_self(tmp_path: Path) -> None:
    """验证 update all 只更新代理核心和 geo，并输出服务计划。"""
    config = write_config_with_sources(tmp_path)

    result = runner.invoke(agent_app, ["update", "all", "-c", str(config)])

    assert result.exit_code == 0
    assert "self" not in result.output
    assert "Service adapter dry-run" in result.output
    assert "proxystack-xray@*.service" in result.output
    assert "proxystack-clash@*.service" in result.output


def test_install_update_help_is_available() -> None:
    """验证安装更新相关 help 可以正常输出。"""
    for command in [["install"], ["update"], ["version"]]:
        result = runner.invoke(agent_app, [*command, "--help"])

        assert result.exit_code == 0, command


def test_install_help_describes_source_choices() -> None:
    """验证 install help 展示 mihomo/xray 和 geo 的 source 可选形式。"""
    result = runner.invoke(agent_app, ["install", "--help"])

    assert result.exit_code == 0
    assert "auto/github/r2" in result.output
    assert "MetaCubeX geoip.metadb" in result.output
    assert "普通远端" in result.output
    assert "URL 需要 --sha256" in result.output


def write_config_with_sources(tmp_path: Path) -> Path:
    """写入包含 mihomo/xray/geo 本地 source 和 sha256 的配置。"""
    mihomo_source = write_source(tmp_path / "sources" / "mihomo.bin", b"mihomo")
    xray_source = write_source(tmp_path / "sources" / "xray.bin", b"xray")
    geo_source = write_source(tmp_path / "sources" / "geo.dat", b"geo")
    return write_install_config(
        tmp_path,
        {
            "mihomo": {
                "source": str(mihomo_source),
                "sha256": file_sha256(mihomo_source),
            },
            "xray": {
                "source": str(xray_source),
                "sha256": file_sha256(xray_source),
            },
            "geo": {
                "source": str(geo_source),
                "sha256": file_sha256(geo_source),
            },
        },
    )


def write_install_config(tmp_path: Path, install_config: Optional[dict[str, dict[str, str]]] = None) -> Path:
    """写入安装测试使用的最小全局配置。"""
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    config_data = {
        "version": 1,
        "base_dir": str(project_dir),
        "paths": {
            "bin": "bin",
            "geo": "geo",
            "stacks": "stacks",
            "runtime": "runtime",
            "generated": "runtime/generated",
            "publish": "publish",
            "downloads": "downloads",
            "sub": "sub",
        },
        "external_host": "proxy.example.com",
        "subscription": {
            "source": "local",
            "listen": "127.0.0.1:3003",
            "access": {
                "type": "token",
                "token": "test-token",
            },
        },
        "port_ranges": {
            "xrelay_inbound": "24000-24999",
            "clash_socks": "17000-17999",
            "clash_controller": "19000-19999",
        },
        "install": install_config or {},
    }
    config = project_dir / "config.yaml"
    yaml = YAML()
    with config.open("w", encoding="utf-8") as config_file:
        yaml.dump(config_data, config_file)
    return config


def write_source(path: Path, content: bytes) -> Path:
    """写入测试源文件并返回路径。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def write_zip(path: Path, members: dict[str, bytes]) -> Path:
    """写入测试 zip 归档并返回路径。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as zip_file:
        for name, content in members.items():
            zip_file.writestr(name, content)
    return path


def sha256_bytes(content: bytes) -> str:
    """计算测试字节内容的 sha256。"""
    return hashlib.sha256(content).hexdigest()


class FakeResponse:
    """模拟 urllib response，供下载进度测试读取。"""

    def __init__(self, payload: bytes) -> None:
        """保存响应字节和 Content-Length。"""
        self.payload = payload
        self.offset = 0
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> "FakeResponse":
        """支持 with opener.open(...) as response。"""
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        """测试响应无需额外释放资源。"""
        return None

    def read(self, size: int) -> bytes:
        """按请求大小返回下一段响应内容。"""
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class FakeOpener:
    """模拟 urllib opener，避免进度测试访问真实网络。"""

    def __init__(self, payload: bytes) -> None:
        """保存每次 open 要返回的响应内容。"""
        self.payload = payload

    def open(self, _source: str, timeout: int) -> FakeResponse:
        """返回 fake response，并校验 timeout 参数仍按常量传入。"""
        assert timeout > 0
        return FakeResponse(self.payload)
