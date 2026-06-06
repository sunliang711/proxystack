"""下载安装和自更新服务函数。"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import grp
import hashlib
import ipaddress
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import pwd
import shutil
import socket
import subprocess
import tarfile
import tempfile
from typing import Callable
from typing import Optional
from typing import Sequence
from urllib.parse import unquote
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler
from urllib.request import Request
from urllib.request import build_opener
from zipfile import ZipFile
from zipfile import is_zipfile

from proxystack.domain.models import GlobalConfig

ARTIFACT_TARGETS = ("mihomo", "xray", "geo")
BINARY_NAMES = {
    "mihomo": "mihomo",
    "xray": "xray",
}
MANAGED_SOURCE_ALIASES = {"auto", "github", "r2"}
MANAGED_DOWNLOAD_ROOT = "https://pub-06197a088952412f8ff879716ee84855.r2.dev"
MANAGED_PROJECTS = {
    "mihomo": {
        "repo": "MetaCubeX/mihomo",
        "filename_tpl": "mihomo-linux-amd64-compatible-v{version}.gz",
        "r2_path": "mihomo",
        "r2_latest": True,
    },
    "xray": {
        "repo": "XTLS/Xray-core",
        "filename_tpl": "Xray-linux-64.zip",
        "r2_path": "xray",
        "r2_latest": False,
    },
}
VERSION_ARGS = {
    "mihomo": ("-v",),
    "xray": ("version",),
}
GEO_SUFFIXES = {".dat", ".mmdb"}
DOWNLOAD_TIMEOUT = 30

Downloader = Callable[[str, Path], Path]
FileReplacer = Callable[[Path, Path, int], None]
CommandRunner = Callable[[Sequence[str]], "CommandResult"]


@dataclass(frozen=True)
class CommandResult:
    """表示一次外部命令执行结果，供 self update 和版本检测复用。"""

    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class InstallRequest:
    """表示单个安装目标的下载、校验和解包参数。"""

    target: str
    version: str
    source: str
    sha256: Optional[str] = None
    archive_member: Optional[str] = None


@dataclass(frozen=True)
class InstallResult:
    """表示一次代理核心或 geo 数据安装结果。"""

    operation: str
    target: str
    version: str
    source: str
    source_sha256: str
    installed_paths: tuple[Path, ...]
    service_plan: tuple[str, ...]


@dataclass(frozen=True)
class ManagedDownloadSource:
    """表示内置 GitHub/R2 下载源候选。"""

    name: str
    url: str
    filename: str
    version: str


@dataclass(frozen=True)
class SelfUpdateRequest:
    """表示 proxystack Python 包自更新参数。"""

    wheel: Optional[Path] = None
    package_spec: Optional[str] = None
    sha256: Optional[str] = None


@dataclass(frozen=True)
class VersionResult:
    """表示单个组件的版本检测结果。"""

    target: str
    path: Optional[Path]
    status: str
    output: str


def expand_artifact_targets(target: str) -> tuple[str, ...]:
    """展开 install/update 目标，保证 all 不包含 self。"""
    if target == "all":
        return ARTIFACT_TARGETS
    if target in ARTIFACT_TARGETS:
        return (target,)
    raise ValueError(f"unsupported install target: {target}")


def build_install_request(
    config: GlobalConfig,
    target: str,
    version: Optional[str],
    source: Optional[str],
    sha256: Optional[str],
    archive_member: Optional[str],
) -> InstallRequest:
    """从全局配置和 CLI 覆盖参数构建单个目标的安装请求。"""
    if target not in ARTIFACT_TARGETS:
        raise ValueError(f"unsupported install target: {target}")
    target_config = getattr(config.install, target)
    resolved_source = source or target_config.source
    if resolved_source is None and target in BINARY_NAMES:
        resolved_source = "auto"
    if not resolved_source:
        raise ValueError(f"source is required for {target}")
    return InstallRequest(
        target=target,
        version=version or target_config.version,
        source=resolved_source,
        sha256=sha256 or target_config.sha256,
        archive_member=archive_member or target_config.archive_member,
    )


def install_artifact(
    config: GlobalConfig,
    request: InstallRequest,
    operation: str = "install",
    downloader: Optional[Downloader] = None,
    replacer: FileReplacer = None,
) -> InstallResult:
    """安装或更新单个代理核心/geo 目标，不调用 systemctl。"""
    target = normalize_artifact_target(request.target)
    downloads_dir = config.resolve_path(config.paths.downloads)
    require_download_hash(request.source, request.sha256)
    source_path = fetch_source(request, downloads_dir, downloader)
    source_sha256 = file_sha256(source_path)
    verify_sha256_value(source_sha256, request.sha256)
    installed_paths = install_source_files(
        config,
        target,
        source_path,
        request.archive_member,
        replacer or atomic_replace_file,
    )
    return InstallResult(
        operation=operation,
        target=target,
        version=request.version,
        source=request.source,
        source_sha256=source_sha256,
        installed_paths=tuple(installed_paths),
        service_plan=service_plan_for_target(target) if operation == "update" else tuple(),
    )


def is_managed_source_alias(target: str, source: str) -> bool:
    """判断 source 是否为内置 GitHub/R2 托管源别名。"""
    return target in MANAGED_PROJECTS and source in MANAGED_SOURCE_ALIASES


def normalize_artifact_target(target: str) -> str:
    """校验并返回支持的代理核心/geo 目标名。"""
    if target not in ARTIFACT_TARGETS:
        raise ValueError(f"unsupported install target: {target}")
    return target


def fetch_source(request: InstallRequest, downloads_dir: Path, downloader: Optional[Downloader]) -> Path:
    """读取本地文件或下载远端 URL，远端内容写入 downloads 缓存目录。"""
    source = request.source
    if is_managed_source_alias(request.target, source):
        return fetch_managed_source(request, downloads_dir, downloader or download_url_with_redirects)
    parsed_url = urlparse(source)
    if parsed_url.scheme in {"http", "https"}:
        effective_downloader = downloader or download_url
        validate_download_url(source, resolve_dns=effective_downloader is download_url)
        ensure_private_directory(downloads_dir)
        destination = downloads_dir / safe_download_name(parsed_url.path)
        return effective_downloader(source, destination)
    if parsed_url.scheme == "file":
        local_path = Path(unquote(parsed_url.path))
    elif parsed_url.scheme:
        raise ValueError(f"unsupported source scheme: {parsed_url.scheme}")
    else:
        local_path = Path(source)
    if local_path.is_dir():
        raise ValueError(f"source must be a file: {local_path}")
    if not local_path.exists():
        raise ValueError(f"source file does not exist: {local_path}")
    return local_path


def fetch_managed_source(request: InstallRequest, downloads_dir: Path, downloader: Downloader) -> Path:
    """按内置 GitHub/R2 候选源下载 mihomo 或 xray。"""
    ensure_private_directory(downloads_dir)
    sources = build_managed_sources(request.target, request.version, request.source)
    failures: list[str] = []
    for source in sources:
        destination = downloads_dir / source.filename
        try:
            return downloader(source.url, destination)
        except (OSError, TimeoutError, ValueError) as exc:
            destination.unlink(missing_ok=True)
            failures.append(f"{source.name}: {exc}")
    raise ValueError(f"all managed download sources failed for {request.target}: {'; '.join(failures)}")


def build_managed_sources(target: str, version: str, source_mode: str) -> list[ManagedDownloadSource]:
    """根据目标、版本和源模式构造 GitHub/R2 下载候选。"""
    if target not in MANAGED_PROJECTS:
        raise ValueError(f"managed download is not supported for {target}")
    if source_mode not in MANAGED_SOURCE_ALIASES:
        raise ValueError(f"unsupported managed source: {source_mode}")
    normalized_version = normalize_managed_version(version)
    if normalized_version == "latest":
        return build_latest_managed_sources(target, source_mode)
    sources: list[ManagedDownloadSource] = []
    if source_mode in {"auto", "github"}:
        sources.append(build_github_managed_source(target, normalized_version))
    if source_mode in {"auto", "r2"}:
        sources.append(build_r2_versioned_managed_source(target, normalized_version))
    return sources


def build_latest_managed_sources(target: str, source_mode: str) -> list[ManagedDownloadSource]:
    """按候选源各自的 latest 版本构造下载源。"""
    sources: list[ManagedDownloadSource] = []
    failures: list[str] = []
    builders = []
    if source_mode in {"auto", "github"}:
        builders.append(lambda: build_github_managed_source(target, github_latest_version(target)))
    if source_mode in {"auto", "r2"}:
        builders.append(lambda: build_r2_latest_managed_source(target))
    for builder in builders:
        try:
            sources.append(builder())
        except (OSError, TimeoutError, ValueError) as exc:
            failures.append(str(exc))
    if not sources:
        raise ValueError(f"latest version cannot be resolved for {target}: {'; '.join(failures)}")
    return sources


def normalize_managed_version(version: str) -> str:
    """把 v1.2.3 这类版本号归一为 1.2.3，latest 保持不变。"""
    normalized_version = version.strip()
    if normalized_version == "latest":
        return normalized_version
    return normalized_version.removeprefix("v")


def github_latest_version(target: str) -> str:
    """通过 GitHub releases/latest API 获取最新版本。"""
    project = MANAGED_PROJECTS[target]
    url = f"https://api.github.com/repos/{project['repo']}/releases/latest"
    data = json.loads(read_url_text(url))
    return normalize_managed_version(str(data["tag_name"]))


def r2_latest_version(target: str) -> str:
    """通过 R2 latest/.version 获取当前镜像版本。"""
    project = MANAGED_PROJECTS[target]
    url = f"{MANAGED_DOWNLOAD_ROOT}/{project['r2_path']}/latest/.version"
    return normalize_managed_version(read_url_text(url).strip())


def read_url_text(url: str) -> str:
    """读取内置版本探测 URL 文本。"""
    request = urllib_request(url)
    with build_opener().open(request, timeout=DOWNLOAD_TIMEOUT) as response:
        return response.read().decode("utf-8")


def build_github_managed_source(target: str, version: str) -> ManagedDownloadSource:
    """构造 GitHub Release 资产下载源。"""
    project = MANAGED_PROJECTS[target]
    filename = managed_filename(project, version)
    url = f"https://github.com/{project['repo']}/releases/download/v{version}/{filename}"
    return ManagedDownloadSource("GitHub Release", url, filename, version)


def build_r2_latest_managed_source(target: str) -> ManagedDownloadSource:
    """构造 Cloudflare R2 当前可用的 latest 镜像源。"""
    project = MANAGED_PROJECTS[target]
    needs_version = "{version}" in str(project["filename_tpl"])
    version = r2_latest_version(target) if needs_version or not project["r2_latest"] else ""
    filename = managed_filename(project, version)
    if project["r2_latest"]:
        url = f"{MANAGED_DOWNLOAD_ROOT}/{project['r2_path']}/latest/{filename}"
        return ManagedDownloadSource("Cloudflare R2 (latest)", url, filename, version)
    url = f"{MANAGED_DOWNLOAD_ROOT}/{project['r2_path']}/v{version}/{filename}"
    return ManagedDownloadSource("Cloudflare R2 (latest versioned)", url, filename, version)


def build_r2_versioned_managed_source(target: str, version: str) -> ManagedDownloadSource:
    """构造 Cloudflare R2 指定版本镜像源。"""
    project = MANAGED_PROJECTS[target]
    filename = managed_filename(project, version)
    url = f"{MANAGED_DOWNLOAD_ROOT}/{project['r2_path']}/v{version}/{filename}"
    return ManagedDownloadSource("Cloudflare R2 (versioned)", url, filename, version)


def managed_filename(project: dict[str, object], version: str) -> str:
    """根据托管项目文件名模板生成资产文件名。"""
    template = str(project["filename_tpl"])
    return template.format(version=version)


def urllib_request(url: str):
    """构造带 User-Agent 的 urllib 请求。"""
    return Request(url, headers={"User-Agent": "proxystack-installer/1.0"})


def validate_download_url(source: str, resolve_dns: bool = True) -> None:
    """校验下载 URL 的协议和主机，避免明显的本机/私网目标。"""
    parsed_url = urlparse(source)
    if parsed_url.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported download URL scheme: {parsed_url.scheme}")
    if not parsed_url.hostname:
        raise ValueError("download URL host is required")
    host = parsed_url.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("download URL must not target local host")
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        if resolve_dns:
            validate_resolved_host(host)
        return
    validate_public_ip(host_ip)


def validate_resolved_host(host: str) -> None:
    """解析下载域名并拒绝解析到私网或本机地址。"""
    try:
        address_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError("download URL host cannot be resolved") from exc
    for address_info in address_infos:
        validate_public_ip(ipaddress.ip_address(address_info[4][0]))


def validate_public_ip(host_ip: ipaddress._BaseAddress) -> None:
    """拒绝明显不适合作为下载目标的 IP 地址。"""
    if (
        host_ip.is_loopback
        or host_ip.is_private
        or host_ip.is_link_local
        or host_ip.is_multicast
        or host_ip.is_reserved
        or host_ip.is_unspecified
    ):
        raise ValueError("download URL must not target private or local address")


def safe_download_name(raw_path: str) -> str:
    """从 URL path 中提取安全的缓存文件名。"""
    filename = Path(unquote(raw_path)).name
    if not filename:
        return "download"
    if filename in {".", ".."}:
        raise ValueError("download URL filename is invalid")
    return filename


def download_url(source: str, destination: Path) -> Path:
    """下载远端文件到缓存路径，失败时不替换既有缓存文件。"""
    return download_url_with_opener(source, destination, build_opener(NoRedirectHandler()))


def download_url_with_redirects(source: str, destination: Path) -> Path:
    """下载内置托管源文件，允许 GitHub Release 资产重定向。"""
    return download_url_with_opener(source, destination, build_opener())


def download_url_with_opener(source: str, destination: Path, opener) -> Path:
    """使用指定 opener 下载远端文件到缓存路径。"""
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=destination.parent) as temp_file:
        temp_path = Path(temp_file.name)
        try:
            with opener.open(source, timeout=DOWNLOAD_TIMEOUT) as response:
                shutil.copyfileobj(response, temp_file)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
    temp_path.replace(destination)
    return destination


class NoRedirectHandler(HTTPRedirectHandler):
    """禁用 urllib 默认重定向，避免下载目标绕过初始 URL 校验。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        """返回 None 表示拒绝所有 HTTP 重定向。"""
        return None


def require_download_hash(source: str, expected_sha256: Optional[str]) -> None:
    """要求远端下载必须显式提供 sha256，避免未校验替换。"""
    if source in MANAGED_SOURCE_ALIASES:
        return
    parsed_url = urlparse(source)
    if parsed_url.scheme in {"http", "https"} and not expected_sha256:
        raise ValueError("sha256 is required for downloaded artifacts")


def verify_sha256_value(actual_sha256: str, expected_sha256: Optional[str]) -> None:
    """校验 sha256 摘要；未提供期望值时跳过本地文件校验。"""
    if expected_sha256 is None:
        return
    normalized_expected = expected_sha256.lower()
    if len(normalized_expected) != 64 or any(character not in "0123456789abcdef" for character in normalized_expected):
        raise ValueError("sha256 must be a 64-character hex digest")
    if actual_sha256 != normalized_expected:
        raise ValueError("sha256 mismatch")


def install_source_files(
    config: GlobalConfig,
    target: str,
    source_path: Path,
    archive_member: Optional[str],
    replacer: FileReplacer,
) -> list[Path]:
    """把源文件或归档成员转换为目标文件并原子替换。"""
    target_dir = install_target_dir(config, target)
    ensure_private_directory(target_dir)
    mode = install_target_mode(target)
    with tempfile.TemporaryDirectory() as staging_dir_name:
        staging_dir = Path(staging_dir_name)
        extracted_files = materialize_source_files(target, source_path, archive_member, staging_dir)
        replacement_pairs = target_replacement_pairs(target, target_dir, extracted_files)
        return replace_files_transactionally(replacement_pairs, mode, replacer)


def install_target_dir(config: GlobalConfig, target: str) -> Path:
    """返回安装目标目录，二进制走 bin，geo 数据走 geo。"""
    if target in BINARY_NAMES:
        return config.resolve_path(config.paths.bin)
    return config.resolve_path(config.paths.geo)


def install_target_mode(target: str) -> int:
    """返回目标文件权限，二进制可执行，geo 数据只读。"""
    if target in BINARY_NAMES:
        return 0o750
    return 0o640


def materialize_source_files(
    target: str,
    source_path: Path,
    archive_member: Optional[str],
    staging_dir: Path,
) -> list[Path]:
    """将普通文件或归档内容释放到 staging 目录。"""
    if is_archive(source_path):
        return extract_archive_files(target, source_path, archive_member, staging_dir)
    if is_gzip_file(source_path):
        if target not in BINARY_NAMES:
            raise ValueError("gzip source is only supported for binary targets")
        if archive_member is not None:
            raise ValueError("archive-member requires a zip or tar archive source")
        return [extract_gzip_file(source_path, staging_dir)]
    if archive_member is not None:
        raise ValueError("archive-member requires an archive source")
    return [source_path]


def is_archive(source_path: Path) -> bool:
    """判断源文件是否为 zip 或 tar 归档。"""
    return is_zipfile(source_path) or tarfile.is_tarfile(source_path)


def is_gzip_file(source_path: Path) -> bool:
    """判断源文件是否为单文件 gzip 压缩包。"""
    return source_path.suffix == ".gz"


def extract_gzip_file(source_path: Path, staging_dir: Path) -> Path:
    """解压单文件 gzip，并返回 staging 中的解压后文件。"""
    destination = staging_dir / source_path.with_suffix("").name
    with gzip.open(source_path, "rb") as source_file:
        with destination.open("wb") as destination_file:
            shutil.copyfileobj(source_file, destination_file)
    return destination


def extract_archive_files(
    target: str,
    source_path: Path,
    archive_member: Optional[str],
    staging_dir: Path,
) -> list[Path]:
    """按目标类型从 zip/tar 归档中抽取一个或多个文件。"""
    if is_zipfile(source_path):
        with ZipFile(source_path) as zip_file:
            member_names = zip_member_names(target, zip_file.namelist(), archive_member)
            return [extract_zip_member(zip_file, member_name, staging_dir) for member_name in member_names]
    with tarfile.open(source_path) as tar_file:
        members = tar_member_names(target, tar_file, archive_member)
        return [extract_tar_member(tar_file, member_name, staging_dir) for member_name in members]


def zip_member_names(target: str, names: list[str], archive_member: Optional[str]) -> list[str]:
    """从 zip 成员列表中选择需要安装的文件成员。"""
    file_names = [name for name in names if not name.endswith("/")]
    return select_archive_members(target, file_names, archive_member)


def tar_member_names(target: str, tar_file: tarfile.TarFile, archive_member: Optional[str]) -> list[str]:
    """从 tar 成员列表中选择普通文件成员。"""
    file_names = [member.name for member in tar_file.getmembers() if member.isfile()]
    return select_archive_members(target, file_names, archive_member)


def select_archive_members(target: str, names: list[str], archive_member: Optional[str]) -> list[str]:
    """按显式成员名或目标默认规则选择归档文件成员。"""
    if archive_member is not None:
        if archive_member not in names:
            raise ValueError(f"archive member does not exist: {archive_member}")
        validate_archive_member_name(archive_member)
        return [archive_member]
    if target in BINARY_NAMES:
        binary_name = BINARY_NAMES[target]
        matches = [name for name in names if PurePosixPath(name).name == binary_name]
        if len(matches) != 1:
            raise ValueError(f"archive-member is required for {target} archive")
        validate_archive_member_name(matches[0])
        return matches
    matches = [name for name in names if PurePosixPath(name).suffix in GEO_SUFFIXES]
    if not matches:
        raise ValueError("geo archive must contain .dat or .mmdb files")
    for member_name in matches:
        validate_archive_member_name(member_name)
    return matches


def validate_archive_member_name(member_name: str) -> None:
    """校验归档成员名不包含绝对路径或路径穿越。"""
    member_path = PurePosixPath(member_name)
    if member_path.is_absolute() or any(part == ".." for part in member_path.parts):
        raise ValueError(f"unsafe archive member: {member_name}")
    if not member_path.name:
        raise ValueError(f"archive member must be a file: {member_name}")


def extract_zip_member(zip_file: ZipFile, member_name: str, staging_dir: Path) -> Path:
    """安全抽取单个 zip 成员到 staging 目录。"""
    validate_archive_member_name(member_name)
    destination = staging_dir / PurePosixPath(member_name).name
    with zip_file.open(member_name) as source_file:
        with destination.open("wb") as destination_file:
            shutil.copyfileobj(source_file, destination_file)
    return destination


def extract_tar_member(tar_file: tarfile.TarFile, member_name: str, staging_dir: Path) -> Path:
    """安全抽取单个 tar 普通文件成员到 staging 目录。"""
    validate_archive_member_name(member_name)
    member = tar_file.getmember(member_name)
    source_file = tar_file.extractfile(member)
    if source_file is None:
        raise ValueError(f"archive member is not readable: {member_name}")
    destination = staging_dir / PurePosixPath(member_name).name
    with source_file:
        with destination.open("wb") as destination_file:
            shutil.copyfileobj(source_file, destination_file)
    return destination


def target_replacement_pairs(target: str, target_dir: Path, extracted_files: list[Path]) -> list[tuple[Path, Path]]:
    """把 staging 文件映射为最终安装路径。"""
    if target in BINARY_NAMES:
        if len(extracted_files) != 1:
            raise ValueError(f"{target} install requires exactly one binary")
        return [(extracted_files[0], target_dir / BINARY_NAMES[target])]
    return [(extracted_file, target_dir / extracted_file.name) for extracted_file in extracted_files]


def replace_files_transactionally(
    replacement_pairs: list[tuple[Path, Path]],
    mode: int,
    replacer: FileReplacer,
) -> list[Path]:
    """批量替换目标文件，任一文件失败时恢复已替换文件。"""
    backups: list[tuple[Path, Optional[Path]]] = []
    try:
        for source_path, destination in replacement_pairs:
            backup_path = backup_destination(destination)
            backups.append((destination, backup_path))
            replacer(source_path, destination, mode)
    except BaseException:
        restore_backups(backups)
        raise
    cleanup_backups(backups)
    return [destination for _, destination in replacement_pairs]


def backup_destination(destination: Path) -> Optional[Path]:
    """复制既有目标文件到同目录临时备份，缺失目标返回 None。"""
    if not destination.exists():
        return None
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=destination.parent) as backup_file:
        backup_path = Path(backup_file.name)
    shutil.copy2(destination, backup_path)
    return backup_path


def restore_backups(backups: list[tuple[Path, Optional[Path]]]) -> None:
    """按反向顺序恢复事务备份，尽量回到替换前状态。"""
    for destination, backup_path in reversed(backups):
        if backup_path is None:
            destination.unlink(missing_ok=True)
            continue
        os.replace(backup_path, destination)
    cleanup_backups(backups)


def cleanup_backups(backups: list[tuple[Path, Optional[Path]]]) -> None:
    """清理尚未被 restore 消费的临时备份文件。"""
    for _, backup_path in backups:
        if backup_path is not None:
            backup_path.unlink(missing_ok=True)


def atomic_replace_file(source_path: Path, destination: Path, mode: int) -> None:
    """用同目录临时文件原子替换目标，替换前设置权限。"""
    ensure_private_directory(destination.parent)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=destination.parent) as temp_file:
        temp_path = Path(temp_file.name)
        try:
            with source_path.open("rb") as source_file:
                shutil.copyfileobj(source_file, temp_file)
            temp_file.flush()
            os.chmod(temp_path, mode)
            chown_if_root(temp_path)
            os.replace(temp_path, destination)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise


def ensure_private_directory(path: Path) -> None:
    """创建安装相关目录，并按本地部署约定设置私有权限。"""
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o750)
    chown_if_root(path)


def chown_if_root(path: Path) -> None:
    """在 root 执行且 proxystack 用户组存在时设置 owner。"""
    if os.geteuid() != 0:
        return
    try:
        user_id = pwd.getpwnam("proxystack").pw_uid
        group_id = grp.getgrnam("proxystack").gr_gid
    except KeyError:
        return
    os.chown(path, user_id, group_id)


def file_sha256(path: Path) -> str:
    """以流式方式计算文件 sha256 摘要。"""
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def service_plan_for_target(target: str) -> tuple[str, ...]:
    """生成更新流程的 service adapter 文本计划，不执行真实服务动作。"""
    if target == "mihomo":
        affected_services = ("proxystack-clash@*.service",)
    elif target == "xray":
        affected_services = ("proxystack-xray@*.service",)
    else:
        affected_services = ("proxystack-xray@*.service", "proxystack-clash@*.service")
    return tuple(
        [
            "Service adapter dry-run; Task09 will execute systemd.",
            *[f"stop: {service_name}" for service_name in affected_services],
            *[f"restore: {service_name}" for service_name in affected_services],
        ]
    )


def run_self_update(
    config: GlobalConfig,
    request: SelfUpdateRequest,
    runner: CommandRunner = None,
) -> CommandResult:
    """使用 venv 内 python 调用 pip 升级 proxystack Python 包。"""
    if request.wheel is not None and request.package_spec is not None:
        raise ValueError("use either --wheel or package spec, not both")
    if request.wheel is None and request.package_spec is None:
        raise ValueError("self update requires --wheel or package spec")
    venv_dir = config.base_dir / ".venv"
    python_path = venv_dir / "bin" / "python"
    validate_writable_venv(venv_dir, python_path)
    install_target = resolve_self_update_target(request)
    command = [str(python_path), "-m", "pip", "install", "--upgrade", install_target]
    result = (runner or run_command)(command)
    if result.returncode != 0:
        raise ValueError("pip install failed")
    return result


def validate_writable_venv(venv_dir: Path, python_path: Path) -> None:
    """校验 venv 存在、可写且包含 python，不自动提权。"""
    if not venv_dir.is_dir():
        raise ValueError(f"venv does not exist: {venv_dir}")
    if not python_path.exists():
        raise ValueError(f"venv python does not exist: {python_path}")
    if not os.access(venv_dir, os.W_OK):
        raise ValueError(f"venv is not writable: {venv_dir}")


def resolve_self_update_target(request: SelfUpdateRequest) -> str:
    """解析 self update 安装目标并在 wheel 场景执行 sha256 校验。"""
    if request.wheel is not None:
        if not request.wheel.exists() or request.wheel.is_dir():
            raise ValueError(f"wheel file does not exist: {request.wheel}")
        verify_sha256_value(file_sha256(request.wheel), request.sha256)
        return str(request.wheel)
    package_spec = request.package_spec or ""
    if not package_spec or package_spec.startswith("-"):
        raise ValueError("package spec is invalid")
    if request.sha256 is not None:
        raise ValueError("sha256 is only supported with --wheel")
    return package_spec


def run_command(args: Sequence[str]) -> CommandResult:
    """以参数数组执行外部命令，禁止 shell 拼接。"""
    completed = subprocess.run(
        list(args),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return CommandResult(
        args=tuple(str(argument) for argument in args),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def detect_component_version(
    config: GlobalConfig,
    target: str,
    runner: CommandRunner = None,
) -> VersionResult:
    """检测 proxystack 组件版本，二进制通过本地命令查询。"""
    if target not in ARTIFACT_TARGETS:
        raise ValueError(f"unsupported version target: {target}")
    if target == "geo":
        geo_dir = config.resolve_path(config.paths.geo)
        if not geo_dir.exists():
            return VersionResult(target=target, path=geo_dir, status="missing", output="")
        lines = [f"{path.name} {file_sha256(path)}" for path in sorted(geo_dir.iterdir()) if path.is_file()]
        return VersionResult(target=target, path=geo_dir, status="ok", output="\n".join(lines))
    binary_path = config.resolve_path(config.paths.bin) / BINARY_NAMES[target]
    if not binary_path.exists():
        return VersionResult(target=target, path=binary_path, status="missing", output="")
    result = (runner or run_command)([str(binary_path), *VERSION_ARGS[target]])
    output = (result.stdout or result.stderr).strip()
    status = "ok" if result.returncode == 0 else "error"
    return VersionResult(target=target, path=binary_path, status=status, output=output)
