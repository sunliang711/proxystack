"""systemd unit 生成、安装和命令执行封装。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Callable
from typing import Optional
from typing import Sequence

from proxystack.domain.models import GlobalConfig
from proxystack.domain.models import parse_listen

SYSTEMD_UNIT_DIR = Path("/etc/systemd/system")
XRAY_TEMPLATE_UNIT = "proxystack-xray@.service"
CLASH_TEMPLATE_UNIT = "proxystack-clash@.service"
SUB_UNIT = "proxystack-sub.service"
UNIT_NAMES = (XRAY_TEMPLATE_UNIT, CLASH_TEMPLATE_UNIT, SUB_UNIT)

CommandRunner = Callable[[Sequence[str]], "CommandResult"]


@dataclass(frozen=True)
class CommandResult:
    """表示一次 systemctl 或 journalctl 命令执行结果。"""

    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class UnitFile:
    """表示一个待安装的 systemd unit 文件。"""

    name: str
    content: str


class SystemdCommandError(RuntimeError):
    """表示 systemctl 或 journalctl 返回非零退出码。"""


class SystemdManager:
    """封装 systemd unit 文件和命令调用，便于 CLI 与测试复用。"""

    def __init__(
        self,
        config: GlobalConfig,
        runner: Optional[CommandRunner] = None,
        unit_dir: Path = SYSTEMD_UNIT_DIR,
    ) -> None:
        """初始化 manager，测试可传入 fake runner 和 fake unit_dir。"""
        self.config = config
        self.runner = runner or run_command
        self.unit_dir = unit_dir

    def build_units(self, unit_names: Sequence[str] = UNIT_NAMES) -> tuple[UnitFile, ...]:
        """按 unit 名称渲染 unit 内容。"""
        builders = {
            XRAY_TEMPLATE_UNIT: self.build_xray_unit,
            CLASH_TEMPLATE_UNIT: self.build_clash_unit,
            SUB_UNIT: self.build_sub_unit,
        }
        units: list[UnitFile] = []
        for unit_name in unit_names:
            builder = builders.get(unit_name)
            if builder is None:
                raise ValueError(f"unsupported systemd unit: {unit_name}")
            units.append(builder())
        return tuple(units)

    def build_xray_unit(self) -> UnitFile:
        """生成 Xray 模板 unit，只引用 runtime/generated 下的实例配置。"""
        bin_dir = self.config.resolve_path(self.config.paths.bin)
        generated_dir = self.config.resolve_path(self.config.paths.generated)
        config_path = generated_dir / "xray" / "%i.json"
        read_write_paths = self.agent_runtime_write_paths()
        content = "\n".join(
            [
                "[Unit]",
                "Description=Proxystack Xray instance %i",
                "After=network-online.target",
                "Wants=network-online.target",
                "",
                "[Service]",
                "Type=simple",
                "User=proxystack",
                "Group=proxystack",
                "NoNewPrivileges=true",
                "ProtectSystem=strict",
                "ProtectHome=true",
                "PrivateTmp=true",
                f"ReadWritePaths={read_write_paths}",
                f"ExecStart={systemd_join_args([bin_dir / 'xray', 'run', '-config', config_path])}",
                "Restart=on-failure",
                "RestartSec=3s",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
                "",
            ]
        )
        return UnitFile(XRAY_TEMPLATE_UNIT, content)

    def build_clash_unit(self) -> UnitFile:
        """生成 mihomo 模板 unit，只引用 runtime/generated 下的实例配置。"""
        bin_dir = self.config.resolve_path(self.config.paths.bin)
        generated_dir = self.config.resolve_path(self.config.paths.generated)
        config_path = generated_dir / "mihomo" / "%i.yaml"
        data_dir = self.config.resolve_path(self.config.paths.runtime) / "mihomo" / "%i"
        read_write_paths = self.agent_runtime_write_paths()
        content = "\n".join(
            [
                "[Unit]",
                "Description=Proxystack mihomo instance %i",
                "After=network-online.target",
                "Wants=network-online.target",
                "",
                "[Service]",
                "Type=simple",
                "User=proxystack",
                "Group=proxystack",
                "NoNewPrivileges=true",
                "ProtectSystem=strict",
                "ProtectHome=true",
                "PrivateTmp=true",
                f"ReadWritePaths={read_write_paths}",
                f"ExecStart={systemd_join_args([bin_dir / 'mihomo', '-d', data_dir, '-f', config_path])}",
                "Restart=on-failure",
                "RestartSec=3s",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
                "",
            ]
        )
        return UnitFile(CLASH_TEMPLATE_UNIT, content)

    def build_sub_unit(self) -> UnitFile:
        """生成订阅服务 unit，只传入 data-dir、host 和 port。"""
        host, port = parse_listen(self.config.subscription.listen)
        sub_dir = self.config.resolve_path(self.config.paths.sub)
        command_path = self.config.base_dir / ".venv" / "bin" / "proxystack-sub"
        content = "\n".join(
            [
                "[Unit]",
                "Description=Proxystack subscription service",
                "After=network-online.target",
                "Wants=network-online.target",
                "",
                "[Service]",
                "Type=simple",
                "User=proxystack",
                "Group=proxystack",
                "NoNewPrivileges=true",
                "ProtectSystem=strict",
                "ProtectHome=true",
                "PrivateTmp=true",
                f"ReadWritePaths={systemd_quote_arg(sub_dir)}",
                f"ExecStart={systemd_join_args([command_path, 'serve', '--data-dir', sub_dir, '--host', host, '--port', str(port)])}",
                "Restart=on-failure",
                "RestartSec=3s",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
                "",
            ]
        )
        return UnitFile(SUB_UNIT, content)

    def agent_runtime_write_paths(self) -> str:
        """返回 xray/clash 允许写入的 agent runtime 相关目录。"""
        paths = unique_paths(
            [
                self.config.resolve_path(self.config.paths.runtime),
                self.config.resolve_path(self.config.paths.generated),
            ]
        )
        return " ".join(systemd_quote_arg(path) for path in paths)

    def install_units(self, unit_names: Sequence[str] = UNIT_NAMES) -> list[str]:
        """写入 unit 文件并执行 daemon-reload。"""
        lines: list[str] = []
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        for unit_file in self.build_units(unit_names):
            path = self.unit_dir / unit_file.name
            path.write_text(unit_file.content, encoding="utf-8")
            path.chmod(0o644)
            lines.append(f"install: {path}")
        self.daemon_reload()
        lines.append("daemon-reload: ok")
        return lines

    def uninstall_units(self, unit_names: Sequence[str] = UNIT_NAMES) -> list[str]:
        """删除 unit 文件并执行 daemon-reload，不触碰 config 或 stacks。"""
        lines: list[str] = []
        for unit_name in unit_names:
            path = self.unit_dir / unit_name
            if path.exists():
                path.unlink()
                lines.append(f"uninstall: {path}")
            else:
                lines.append(f"uninstall: missing {path}")
        self.daemon_reload()
        lines.append("daemon-reload: ok")
        return lines

    def daemon_reload(self) -> CommandResult:
        """调用 systemctl daemon-reload，并在失败时抛出摘要错误。"""
        return self.run_checked(["systemctl", "daemon-reload"])

    def systemctl(self, action: str, service_names: Sequence[str]) -> list[str]:
        """对服务逐个执行 systemctl 动作并返回可展示输出。"""
        if not service_names:
            return [f"{action}: no services selected"]
        lines: list[str] = []
        for service_name in service_names:
            result = self.run_checked(["systemctl", action, service_name])
            lines.extend(format_success_output(action, service_name, result))
        return lines

    def journalctl(self, service_names: Sequence[str], follow: bool = False) -> list[str]:
        """读取指定服务 journal，follow 时传递 -f。"""
        if not service_names:
            suffix = " --follow" if follow else ""
            return [f"log{suffix}: no services selected"]
        if follow:
            result = self.run_checked(build_journalctl_command(service_names, follow=True))
            lines = [f"log: {service_name}" for service_name in service_names]
            output_lines = command_output_summary(result, limit=4000).splitlines()
            lines.extend(f"  {line}" for line in output_lines)
            return lines
        lines: list[str] = []
        for service_name in service_names:
            command = build_journalctl_command((service_name,), follow=False)
            result = self.run_checked(command)
            lines.extend(format_success_output("log", service_name, result))
        return lines

    def run_checked(self, args: Sequence[str]) -> CommandResult:
        """执行外部命令，非零退出码转为包含 stdout/stderr 摘要的错误。"""
        result = self.runner([str(argument) for argument in args])
        if result.returncode != 0:
            raise SystemdCommandError(command_error_message(result))
        return result


def run_command(args: Sequence[str]) -> CommandResult:
    """以参数数组调用外部命令，避免 shell 拼接。"""
    command = [str(argument) for argument in args]
    if should_stream_command(command):
        completed = subprocess.run(
            command,
            check=False,
            text=True,
        )
        return CommandResult(
            args=tuple(command),
            returncode=completed.returncode,
        )
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return CommandResult(
        args=tuple(command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def build_journalctl_command(service_names: Sequence[str], follow: bool = False) -> list[str]:
    """构造 journalctl 参数数组，follow 模式可一次订阅多个 unit。"""
    command = ["journalctl"]
    for service_name in service_names:
        command.extend(["-u", service_name])
    command.extend(["--no-pager", "-n", "100"])
    if follow:
        command.append("-f")
    return command


def should_stream_command(command: Sequence[str]) -> bool:
    """journalctl follow 需要直接流式输出到终端。"""
    return bool(command) and command[0] == "journalctl" and "-f" in command


def systemd_join_args(args: Sequence[object]) -> str:
    """把参数数组渲染为 systemd ExecStart 可读文本。"""
    return " ".join(systemd_quote_arg(argument) for argument in args)


def systemd_quote_arg(argument: object) -> str:
    """按 systemd 简单引号规则保护包含空白的参数。"""
    value = str(argument)
    if not value:
        return '""'
    if not any(character.isspace() or character in {'"', "\\"} for character in value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def unique_paths(paths: Sequence[Path]) -> tuple[Path, ...]:
    """保持顺序去重，避免 ReadWritePaths 重复。"""
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return tuple(unique)


def format_success_output(action: str, service_name: str, result: CommandResult) -> list[str]:
    """格式化成功命令的 stdout/stderr，供 CLI 直接输出。"""
    lines = [f"{action}: {service_name}"]
    output_lines = command_output_summary(result, limit=4000).splitlines()
    lines.extend(f"  {line}" for line in output_lines)
    return lines


def command_error_message(result: CommandResult) -> str:
    """生成 systemctl/journalctl 失败摘要，保留 stdout 和 stderr 线索。"""
    command = " ".join(result.args)
    stdout = truncate_text(result.stdout.strip(), 1200) or "-"
    stderr = truncate_text(result.stderr.strip(), 1200) or "-"
    return (
        f"command failed with exit code {result.returncode}: {command}\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}"
    )


def command_output_summary(result: CommandResult, limit: int = 1200) -> str:
    """合并成功命令输出，避免 CLI 丢失 status/log 结果。"""
    output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
    return truncate_text(output, limit)


def truncate_text(value: str, limit: int) -> str:
    """限制命令输出摘要长度，防止错误信息过长。"""
    if len(value) <= limit:
        return value
    return value[:limit] + "\n... truncated ..."
