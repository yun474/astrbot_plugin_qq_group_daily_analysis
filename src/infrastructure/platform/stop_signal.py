"""
AstrBot /stop 停止信号桥接

AstrBot 原生 /stop 是协作式取消：它给本会话所有活跃事件打上 ``agent_stop_requested`` 标记。
命令式插件需要自己读取这个标记，才能取消自己创建的分析任务。

两点取舍（参考上游实现）：
- 不读 ``event.is_stopped()``：它表示「终止事件传播」，任何地方调用 ``event.stop_event()`` 都会置位，
  与用户主动停止无关，混用会误杀正常任务。
- 不向宿主注册停止回调：宿主每个事件只有一个回调槽位，注册会覆盖 Agent 运行器已有的回调。
  0.5 秒轮询一次，对分钟级的分析任务没有体感差异，且只依赖公开接口。
"""

from __future__ import annotations

import asyncio

from astrbot.api.event import AstrMessageEvent

from ...application.services.stop_request import StopRequest
from ...utils.logger import logger

STOP_EXTRA_KEY = "agent_stop_requested"
STOP_POLL_INTERVAL_SECONDS = 0.5


class FrontendStopWatcher:
    """把 AstrBot 事件上的停止标记转换成 StopRequest

    生命周期由调用方管理：任务开始前 start()，结束后 stop()。
    """

    def __init__(
        self,
        event: AstrMessageEvent,
        poll_interval: float = STOP_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._event = event
        self._poll_interval = poll_interval
        self._poll_task: asyncio.Task | None = None
        self._read_error_logged = False
        self.stop_request = StopRequest(self._read_host_stop)

    def start(self) -> None:
        """启动后台轮询"""
        if not callable(getattr(self._event, "get_extra", None)):
            logger.warning("当前 AstrBot 事件不支持读取停止标记，/stop 对本次分析无效")
            return
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """停止后台轮询，可重复调用"""
        task = self._poll_task
        self._poll_task = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _read_host_stop(self) -> bool:
        try:
            return bool(self._event.get_extra(STOP_EXTRA_KEY))
        except Exception as e:
            if not self._read_error_logged:
                self._read_error_logged = True
                logger.warning(f"读取 AstrBot 停止标记失败，将继续重试: {e}")
            return False

    async def _poll_loop(self) -> None:
        while True:
            if self.stop_request.refresh():
                logger.info("检测到 /stop 停止标记，正在中止本次群分析")
                return
            await asyncio.sleep(self._poll_interval)
