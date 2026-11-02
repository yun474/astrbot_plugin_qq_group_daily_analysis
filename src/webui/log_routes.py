"""插件日志接口"""

from __future__ import annotations

from astrbot.api.web import json_response, request

from ..utils.log_buffer import log_buffer


class LogRoutes:
    def routes(self):
        return [("logs", self.get_logs, ["GET"], "插件日志")]

    async def get_logs(self):
        entries = log_buffer.query(
            level=request.query.get("level", "") or "",
            keyword=request.query.get("keyword", "") or "",
            after=request.query.get("after", 0, type=int),
        )
        return json_response({"entries": entries})
