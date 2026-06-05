"""proxystack 下载安装与更新能力。"""

from proxystack.install.service import CommandResult
from proxystack.install.service import InstallRequest
from proxystack.install.service import InstallResult
from proxystack.install.service import SelfUpdateRequest
from proxystack.install.service import VersionResult
from proxystack.install.service import build_install_request
from proxystack.install.service import detect_component_version
from proxystack.install.service import expand_artifact_targets
from proxystack.install.service import install_artifact
from proxystack.install.service import run_self_update

__all__ = [
    "CommandResult",
    "InstallRequest",
    "InstallResult",
    "SelfUpdateRequest",
    "VersionResult",
    "build_install_request",
    "detect_component_version",
    "expand_artifact_targets",
    "install_artifact",
    "run_self_update",
]
