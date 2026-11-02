"""报告历史接口"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from astrbot.api.web import error_response, file_response, json_response, request

from ..infrastructure.persistence.report_archive import ReportArchive

PAGE_SIZE = 20


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


class ReportRoutes:
    def __init__(self, archive: ReportArchive):
        self.archive = archive

    def routes(self):
        return [
            ("reports", self.list_reports, ["GET"], "报告列表"),
            ("reports/<report_id>", self.get_report, ["GET"], "查看报告"),
            ("reports/<report_id>/download", self.download, ["GET"], "下载报告"),
            ("reports/<report_id>/delete", self.delete, ["POST"], "删除报告"),
        ]

    async def list_reports(self):
        start = _parse_date(request.query.get("start"))
        end = _parse_date(request.query.get("end"))
        data = await asyncio.to_thread(
            self.archive.list,
            group_id=request.query.get("group_id", "") or "",
            start=start.timestamp() if start else None,
            # 结束日期包含当天
            end=(end + timedelta(days=1)).timestamp() if end else None,
            page=request.query.get("page", 1, type=int),
            page_size=PAGE_SIZE,
        )
        return json_response(data)

    async def get_report(self, report_id: str):
        record = await asyncio.to_thread(self.archive.get_record, report_id)
        html = await asyncio.to_thread(self.archive.get_html, report_id)
        if record is None or html is None:
            return error_response("报告不存在或文件已被删除", status_code=404)
        return json_response({"record": record, "html": html})

    async def download(self, report_id: str):
        record = await asyncio.to_thread(self.archive.get_record, report_id)
        path = await asyncio.to_thread(self.archive.export_file, report_id)
        if record is None or path is None:
            return error_response("报告不存在或文件已被删除", status_code=404)
        return file_response(
            path,
            filename=f"群分析报告_{record['group_id']}_{report_id}.html",
            content_type="text/html; charset=utf-8",
        )

    async def delete(self, report_id: str):
        if not await asyncio.to_thread(self.archive.delete, report_id):
            return error_response("报告不存在", status_code=404)
        return json_response({"deleted": report_id})
