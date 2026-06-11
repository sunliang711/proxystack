"""项目日志封装。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging as std_logging
from pathlib import Path
import sys
import tempfile
from typing import Any
from typing import Iterator
from typing import TextIO

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
ERROR_SUMMARY_MAX_CHARS = 800
ERROR_SUMMARY_MAX_LINES = 8


def configure_logging(level: str = "INFO") -> None:
    """初始化基础日志格式，适用于 CLI 和后续服务入口。"""
    normalized_level = level.upper()
    std_logging.basicConfig(
        level=getattr(std_logging, normalized_level, std_logging.INFO),
        format=DEFAULT_LOG_FORMAT,
    )


def get_logger(name: str) -> std_logging.Logger:
    """获取命名 logger，供各模块输出结构化日志事件。"""
    return std_logging.getLogger(name)


def format_log_fields(**fields: Any) -> str:
    """把日志字段转换为稳定的 key=value 片段，便于 systemd journal 检索。"""
    return " ".join(f"{key}={value}" for key, value in sorted(fields.items()))


@dataclass(frozen=True)
class ErrorSummary:
    """保存面向屏幕展示的错误摘要和可选完整日志路径。"""

    text: str
    detail_path: Path | None = None


class StepLogger:
    """按步骤输出 doing/done/failed 状态，隐藏步骤内部细节。"""

    def __init__(self, stream: TextIO | None = None) -> None:
        """初始化输出流，默认写入 stderr。"""
        self.stream = stream or sys.stderr
        self.step_index = 0

    @contextmanager
    def step(self, label: str) -> Iterator[None]:
        """输出单个步骤状态，并在异常时打印摘要。"""
        self.step_index += 1
        current_step = self.step_index
        self.write(f"Step {current_step} doing: {label}")
        try:
            yield
        except BaseException as exc:
            summary = summarize_exception(exc)
            self.write(f"Step {current_step} failed: {summary.text}")
            if summary.detail_path is not None:
                self.write(f"Full output: {summary.detail_path}")
            raise
        self.write(f"Step {current_step} done: {label}")

    def write(self, message: str) -> None:
        """把 step 日志写入目标流并立即刷新。"""
        print(message, file=self.stream, flush=True)


def summarize_exception(exc: BaseException) -> ErrorSummary:
    """把异常文本压缩为屏幕摘要，必要时写入 /tmp 详情文件。"""
    full_text = exception_text(exc)
    summary_text = truncate_error_text(full_text)
    detail_path = None
    if summary_text != full_text:
        detail_path = write_error_detail(full_text)
    return ErrorSummary(summary_text, detail_path)


def exception_text(exc: BaseException) -> str:
    """提取异常消息；空消息时回退到异常类型名。"""
    text = str(exc).strip()
    if text:
        return text
    return exc.__class__.__name__


def truncate_error_text(value: str) -> str:
    """限制错误摘要行数和字符数，避免终端输出过长。"""
    lines = value.splitlines()
    limited_lines = lines[:ERROR_SUMMARY_MAX_LINES]
    summary = "\n".join(limited_lines)
    if len(summary) > ERROR_SUMMARY_MAX_CHARS:
        summary = summary[:ERROR_SUMMARY_MAX_CHARS].rstrip()
    if summary != value:
        return f"{summary}\n... truncated ..."
    return summary


def write_error_detail(value: str) -> Path:
    """把完整错误内容写入 /tmp，便于失败后排查。"""
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir="/tmp",
        prefix="proxystack-",
        suffix=".log",
    ) as detail_file:
        detail_file.write(value)
        if not value.endswith("\n"):
            detail_file.write("\n")
        return Path(detail_file.name)
