"""订阅 inputs 目录监控。"""

from __future__ import annotations

from pathlib import Path
import ctypes
import logging
import os
import select
import struct
import sys
import threading
from typing import Callable

InputChangeCallback = Callable[[], None]
LOGGER = logging.getLogger(__name__)
WATCHED_INPUT_EXTENSIONS = {".yaml", ".yml", ".json"}

IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_IGNORED = 0x00008000
IN_ISDIR = 0x40000000
IN_MODIFY = 0x00000002
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
INOTIFY_EVENT_HEADER = "iIII"
INOTIFY_EVENT_HEADER_SIZE = struct.calcsize(INOTIFY_EVENT_HEADER)
WATCH_MASK = (
    IN_CLOSE_WRITE
    | IN_CREATE
    | IN_DELETE
    | IN_DELETE_SELF
    | IN_MOVED_FROM
    | IN_MOVED_TO
    | IN_MOVE_SELF
    | IN_Q_OVERFLOW
)


class InputWatcher:
    """inputs 目录监控基类。"""

    def start(self) -> None:
        """启动监控线程。"""
        raise NotImplementedError

    def stop(self) -> None:
        """停止监控线程并释放资源。"""
        raise NotImplementedError


class PollingInputWatcher(InputWatcher):
    """基于文件状态快照的跨平台 fallback 监控。"""

    def __init__(self, input_dir: Path, on_change: InputChangeCallback, interval: float) -> None:
        """初始化轮询监控参数。"""
        self.input_dir = input_dir
        self.on_change = on_change
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot = self._read_snapshot()

    def start(self) -> None:
        """后台启动轮询监控。"""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="proxystack-sub-polling-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """通知轮询线程退出。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 1.0)

    def _run(self) -> None:
        """周期比较 inputs 快照，变化时触发 reload。"""
        while not self._stop_event.wait(self.interval):
            next_snapshot = self._read_snapshot()
            if next_snapshot == self._snapshot:
                continue
            self._snapshot = next_snapshot
            LOGGER.info("Input watcher detected change: input_dir=%s watcher=polling", self.input_dir)
            run_change_callback(self.on_change)

    def _read_snapshot(self) -> dict[str, tuple[int, int]]:
        """读取当前目录中文件的 mtime 与 size。"""
        try:
            return {
                path.name: (path.stat().st_mtime_ns, path.stat().st_size)
                for path in self.input_dir.iterdir()
                if path.is_file() and has_watched_input_extension(path.name)
            }
        except OSError:
            return {}


class InotifyInputWatcher(InputWatcher):
    """Linux inotify inputs 目录监控。"""

    def __init__(self, input_dir: Path, on_change: InputChangeCallback, interval: float, debounce: float) -> None:
        """初始化 inotify 监控参数。"""
        if not sys.platform.startswith("linux"):
            raise OSError("inotify is only available on linux")
        self.input_dir = input_dir
        self.on_change = on_change
        self.interval = interval
        self.debounce = debounce
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._libc = ctypes.CDLL(None, use_errno=True)
        self._fd = self._inotify_init()
        self._wd = self._inotify_add_watch()

    def start(self) -> None:
        """后台启动 inotify 事件循环。"""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="proxystack-sub-inotify-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止 inotify 线程并关闭 fd。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + self.debounce + 1.0)
        self._close()

    def _run(self) -> None:
        """读取 inotify 事件，目录变化后 debounce 再触发 reload。"""
        while not self._stop_event.is_set():
            readable, _writable, _error = select.select([self._fd], [], [], self.interval)
            if not readable:
                continue
            if self._read_events():
                if self._stop_event.wait(self.debounce):
                    return
                self._drain_events()
                LOGGER.info("Input watcher detected change: input_dir=%s watcher=inotify", self.input_dir)
                run_change_callback(self.on_change)

    def _read_events(self) -> bool:
        """读取并解析一批 inotify 事件。"""
        try:
            event_bytes = os.read(self._fd, 4096)
        except BlockingIOError:
            return False
        except OSError:
            return False
        return any(is_relevant_input_event(mask, name) for _wd, mask, _cookie, name in _iter_inotify_events(event_bytes))

    def _drain_events(self) -> None:
        """清空 debounce 期间积累的事件，避免重复 reload。"""
        while True:
            try:
                if not os.read(self._fd, 4096):
                    return
            except BlockingIOError:
                return
            except OSError:
                return

    def _inotify_init(self) -> int:
        """调用 libc 创建非阻塞 inotify fd。"""
        fd = self._libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if fd < 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))
        return fd

    def _inotify_add_watch(self) -> int:
        """为 inputs 目录添加 inotify watch。"""
        wd = self._libc.inotify_add_watch(self._fd, os.fsencode(self.input_dir), WATCH_MASK)
        if wd < 0:
            errno = ctypes.get_errno()
            self._close()
            raise OSError(errno, os.strerror(errno))
        return wd

    def _close(self) -> None:
        """移除 watch 并关闭 inotify fd。"""
        fd = getattr(self, "_fd", -1)
        wd = getattr(self, "_wd", -1)
        if fd < 0:
            return
        if wd >= 0:
            self._libc.inotify_rm_watch(fd, wd)
        os.close(fd)
        self._fd = -1
        self._wd = -1


def create_input_watcher(
    input_dir: Path,
    on_change: InputChangeCallback,
    interval: float,
    debounce: float,
) -> InputWatcher:
    """创建 inputs 目录监控器，Linux 优先使用 inotify。"""
    try:
        return InotifyInputWatcher(input_dir, on_change, interval=interval, debounce=debounce)
    except OSError:
        return PollingInputWatcher(input_dir, on_change, interval=interval)


def run_change_callback(on_change: InputChangeCallback) -> None:
    """执行 reload 回调，避免异常导致 watcher 线程退出。"""
    try:
        on_change()
    except Exception as exc:
        LOGGER.warning("Input watcher callback failed: %s", exc)


def is_relevant_input_event(mask: int, name: str) -> bool:
    """判断 inotify 事件是否代表订阅 input 的有效变更。"""
    if mask & (IN_Q_OVERFLOW | IN_DELETE_SELF | IN_MOVE_SELF | IN_IGNORED):
        return True
    if mask & IN_ISDIR:
        return False
    if not mask & (IN_CLOSE_WRITE | IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO):
        return False
    return has_watched_input_extension(name)


def has_watched_input_extension(name: str) -> bool:
    """判断文件名是否是订阅服务需要监控的 input 扩展名。"""
    return Path(name).suffix in WATCHED_INPUT_EXTENSIONS


def _iter_inotify_events(event_bytes: bytes) -> list[tuple[int, int, int, str]]:
    """解析 inotify 原始事件字节。"""
    events: list[tuple[int, int, int, str]] = []
    offset = 0
    while offset + INOTIFY_EVENT_HEADER_SIZE <= len(event_bytes):
        wd, mask, cookie, name_length = struct.unpack_from(INOTIFY_EVENT_HEADER, event_bytes, offset)
        offset += INOTIFY_EVENT_HEADER_SIZE
        raw_name = event_bytes[offset : offset + name_length].rstrip(b"\0")
        offset += name_length
        events.append((wd, mask, cookie, raw_name.decode("utf-8", errors="ignore")))
    return events
