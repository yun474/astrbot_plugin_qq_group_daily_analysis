"""任务状态接口"""

from __future__ import annotations

from astrbot.api.web import error_response, json_response

from ..application.services.task_registry import TaskRegistry
from ..infrastructure.scheduler.incremental_trigger import IncrementalTrigger


class TaskRoutes:
    def __init__(self, registry: TaskRegistry, incremental: IncrementalTrigger):
        self.registry = registry
        self.incremental = incremental

    def routes(self):
        return [
            ("tasks", self.list_tasks, ["GET"], "任务状态"),
            ("tasks/<task_id>/stop", self.stop_task, ["POST"], "停止任务"),
        ]

    async def list_tasks(self):
        await self.incremental.ensure_loaded()
        return json_response(
            {
                "running": self.registry.list_running(),
                "history": await self.registry.list_history(),
                "incremental": [s for s in self.incremental.snapshot() if s["enabled"]],
            }
        )

    async def stop_task(self, task_id: str):
        if not self.registry.stop(task_id):
            return error_response("任务不存在、已结束或正在停止")
        return json_response({"stopping": task_id})
