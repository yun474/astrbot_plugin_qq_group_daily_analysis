"""
单次分析任务的协作式停止请求

不依赖宿主：外部停止来源（AstrBot /stop 标记、WebUI 停止按钮）由调用方注入或直接调用 request()。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class AnalysisStoppedError(Exception):
    """分析任务被用户主动停止"""


class StopRequest:
    """管理一次分析任务的停止状态，以及停止时要取消的后台任务

    Args:
        probe: 读取外部停止来源的函数，返回 True 表示外部已请求停止
    """

    def __init__(self, probe: Callable[[], bool] | None = None) -> None:
        self._probe = probe
        self._event = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()

    @property
    def requested(self) -> bool:
        """是否已请求停止（只读本地状态）"""
        return self._event.is_set()

    def refresh(self) -> bool:
        """读取一次外部停止来源，首次命中时触发停止"""
        if not self.requested and self._probe is not None and self._probe():
            self.request()
        return self.requested

    def request(self) -> None:
        """请求停止，并取消已登记的任务；重复调用无副作用"""
        if self.requested:
            return
        self._event.set()
        for task in list(self._tasks):
            task.cancel()

    def cancel_on_stop(self, task: asyncio.Task) -> None:
        """登记一个停止时需要取消的任务，任务结束后自动解除登记"""
        if task.done():
            return
        if self.refresh():
            task.cancel()
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


async def run_stoppable(awaitable: Awaitable[T], stop_request: StopRequest | None) -> T:
    """
    把一段工作包成任务执行，收到停止请求时取消它并抛出 AnalysisStoppedError。

    外层任务自身被取消（插件重载、卸载）时，仍然原样抛出 CancelledError。
    """
    if stop_request is None:
        return await awaitable

    task = asyncio.ensure_future(awaitable)
    stop_request.cancel_on_stop(task)
    try:
        return await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        outer_cancelled = current is not None and current.cancelling() > 0
        if stop_request.requested and not outer_cancelled:
            raise AnalysisStoppedError() from None
        raise
