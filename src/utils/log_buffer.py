"""
插件日志环形缓冲区（WebUI 插件日志页使用）

只缓冲本插件通过 PluginLogger 输出的日志，不碰 AstrBot 全局日志处理器。
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque

MAX_LOG_ENTRIES = 2000


class PluginLogBuffer:
    def __init__(self, maxlen: int = MAX_LOG_ENTRIES):
        self._entries: deque[dict] = deque(maxlen=maxlen)
        self._seq = itertools.count(1)
        # 分析任务里有 asyncio.to_thread，日志可能来自多个线程
        self._lock = threading.Lock()

    def append(self, level: str, trace_id: str, message: str) -> None:
        with self._lock:
            self._entries.append(
                {
                    "id": next(self._seq),
                    "time": time.time(),
                    "level": level,
                    "trace_id": trace_id,
                    "message": message,
                }
            )

    def query(
        self,
        level: str = "",
        keyword: str = "",
        after: int = 0,
        limit: int = 500,
    ) -> list[dict]:
        """按级别（含更高级别）、关键字、起始序号过滤，返回最新的 limit 条（按时间正序）"""
        min_rank = _LEVEL_RANK.get(level.upper(), 0) if level else 0
        keyword = keyword.lower()
        with self._lock:
            entries = list(self._entries)
        result = [
            e
            for e in entries
            if e["id"] > after
            and _LEVEL_RANK.get(e["level"], 0) >= min_rank
            and (
                not keyword
                or keyword in e["message"].lower()
                or keyword in e["trace_id"].lower()
            )
        ]
        return result[-limit:]


_LEVEL_RANK = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

log_buffer = PluginLogBuffer()
