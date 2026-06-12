"""订阅服务内存状态。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Optional

from proxystack.generator.sub import SubscriptionAccess
from proxystack.generator.sub import SubscriptionGeneratorError
from proxystack.generator.sub import SubscriptionIndex
from proxystack.generator.sub import merge_input_files


@dataclass(frozen=True)
class SubscriptionStateHealth:
    """描述当前内存索引加载状态，供 /health 输出。"""

    loaded: bool
    users: int
    last_error: Optional[str]


class SubscriptionState:
    """维护由 inputs 动态合并得到的内存订阅索引。"""

    def __init__(self, data_dir: Path, access: SubscriptionAccess) -> None:
        """初始化订阅状态，实际索引由 load 或 reload 填充。"""
        self.data_dir = data_dir
        self.input_dir = data_dir / "inputs"
        self.access = access
        self._lock = RLock()
        self._index: SubscriptionIndex | None = None
        self._last_error: str | None = None

    def load(self) -> None:
        """启动时创建 inputs 目录并加载一次内存索引。"""
        self.input_dir.mkdir(parents=True, exist_ok=True)
        if not self.reload():
            raise SubscriptionGeneratorError(self._last_error or "subscription index unavailable")

    def reload(self) -> bool:
        """重新扫描 inputs；成功时原子替换内存索引，失败时保留旧索引。"""
        try:
            index = merge_input_files(self.input_dir, access=self.access)
        except (OSError, SubscriptionGeneratorError) as exc:
            with self._lock:
                self._last_error = str(exc)
            return False
        with self._lock:
            self._index = index
            self._last_error = None
        return True

    def snapshot(self) -> SubscriptionIndex:
        """返回当前请求使用的索引快照；未加载时抛出统一生成异常。"""
        with self._lock:
            if self._index is None:
                raise SubscriptionGeneratorError("subscription index unavailable")
            return self._index

    def health(self) -> SubscriptionStateHealth:
        """返回当前内存索引健康状态。"""
        with self._lock:
            return SubscriptionStateHealth(
                loaded=self._index is not None,
                users=0 if self._index is None else len(self._index.users),
                last_error=self._last_error,
            )
