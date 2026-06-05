"""项目日志封装。"""

from __future__ import annotations

import logging as std_logging
from typing import Any

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


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
