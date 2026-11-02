"""
分析任务登记表（WebUI 任务状态页使用）

- 内存里记录正在运行的分析任务：群、来源、开始时间、当前阶段
- 最近 50 条已结束的任务存进插件 KV，重启后还能看到
- stop(task_id)：手动任务走 StopRequest（聊天里会回复「已停止」），定时/增量任务直接取消协程

分析流程通过 shared.task_context.set_stage() 汇报当前阶段，不需要持有登记表引用。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from ...shared.task_context import bind_task, unbind_task
from ...utils.logger import logger
from .analysis_application_service import DuplicateGroupTaskError
from .stop_request import AnalysisStoppedError, StopRequest

HISTORY_KV_KEY = "task_history_v1"
MAX_HISTORY = 50

SOURCE_LABELS = {
    "manual": "手动",
    "scheduled": "定时",
    "incremental": "增量",
    "incremental_report": "增量报告",
}


@dataclass
class TaskRecord:
    task_id: str
    group_id: str
    platform_id: str
    source: str
    group_name: str = ""
    started_at: float = field(default_factory=time.time)
    stage: str = "准备中"
    status: str = "running"  # running / success / failed / stopped / skipped
    error: str = ""
    finished_at: float = 0.0
    stop_requested: bool = False
    asyncio_task: asyncio.Task | None = field(default=None, repr=False)
    stop_request: StopRequest | None = field(default=None, repr=False)

    def fail(self, reason: str) -> None:
        """标记为失败（用于没有抛异常、但结果不成功的情况）"""
        self.status = "failed"
        self.error = reason

    def skip(self, reason: str) -> None:
        self.status = "skipped"
        self.error = reason

    def to_dict(self) -> dict:
        end = self.finished_at or time.time()
        return {
            "task_id": self.task_id,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "platform_id": self.platform_id,
            "source": self.source,
            "source_label": SOURCE_LABELS.get(self.source, self.source),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": round(end - self.started_at, 1),
            "stage": self.stage,
            "status": self.status,
            "error": self.error,
        }


class TaskRegistry:
    def __init__(self, plugin):
        self.plugin = plugin
        self._running: dict[str, TaskRecord] = {}
        self._history: deque[dict] = deque(maxlen=MAX_HISTORY)
        self._history_loaded = False

    @asynccontextmanager
    async def track(
        self,
        group_id: str,
        platform_id: str,
        source: str,
        group_name: str = "",
        stop_request: StopRequest | None = None,
    ):
        """登记一次分析任务；with 块内的代码就是任务本体"""
        record = TaskRecord(
            task_id=uuid.uuid4().hex[:10],
            group_id=str(group_id),
            platform_id=str(platform_id or ""),
            source=source,
            group_name=group_name,
            asyncio_task=asyncio.current_task(),
            stop_request=stop_request,
        )
        self._running[record.task_id] = record
        token = bind_task(record)
        try:
            yield record
            if record.status == "running":
                record.status = "success"
        except AnalysisStoppedError:
            record.status = "stopped"
            record.error = "已在插件页面停止" if record.stop_requested else "/stop 指令"
            raise
        except DuplicateGroupTaskError:
            record.skip("already_running")
            raise
        except asyncio.CancelledError:
            if not record.stop_requested:
                record.status = "stopped"
                record.error = "插件重载或停止"
                raise
            # WebUI 主动停止的定时/增量任务：吞掉这次取消，让调度流程正常收尾
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()
            record.status = "stopped"
            record.error = "已在插件页面停止"
            logger.info(f"群 {record.group_id} 的分析任务已在插件页面停止")
        except Exception as e:
            record.status = "failed"
            record.error = str(e) or type(e).__name__
            raise
        finally:
            if record.status == "running":
                # 生成器被提前关闭等情况
                record.status = "stopped"
            record.finished_at = time.time()
            self._running.pop(record.task_id, None)
            record.asyncio_task = None
            record.stop_request = None
            try:
                unbind_task(token)
            except ValueError:
                # 手动分析是异步生成器，被框架提前回收时可能处在另一个上下文里
                pass
            await self._append_history(record)

    def stop(self, task_id: str) -> bool:
        record = self._running.get(task_id)
        if record is None or record.stop_requested:
            return False
        record.stop_requested = True
        record.stage = "正在停止"
        if record.stop_request is not None:
            record.stop_request.request()
        elif record.asyncio_task is not None:
            record.asyncio_task.cancel()
        return True

    def list_running(self) -> list[dict]:
        return [
            r.to_dict()
            for r in sorted(self._running.values(), key=lambda r: r.started_at)
        ]

    async def list_history(self) -> list[dict]:
        await self._ensure_history_loaded()
        return list(reversed(self._history))

    async def _ensure_history_loaded(self) -> None:
        if self._history_loaded:
            return
        self._history_loaded = True
        try:
            data = await self.plugin.get_kv_data(HISTORY_KV_KEY, [])
            if isinstance(data, list):
                # 加载前可能已经有任务结束，旧记录放前面
                current = list(self._history)
                self._history.clear()
                self._history.extend(
                    [d for d in data if isinstance(d, dict)][-MAX_HISTORY:]
                )
                self._history.extend(current)
        except Exception as e:
            logger.warning(f"读取任务历史失败: {e}")

    async def _append_history(self, record: TaskRecord) -> None:
        try:
            await self._ensure_history_loaded()
            self._history.append(record.to_dict())
            await self.plugin.put_kv_data(HISTORY_KV_KEY, list(self._history))
        except Exception as e:
            logger.warning(f"保存任务历史失败: {e}")
