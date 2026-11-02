"""
报告归档（WebUI 报告历史页使用）

每次报告成功生成后，把完整 HTML 存到：
    <插件数据目录>/report_archive/<群ID>/<日期>_<时间>_<短ID>.html
并在 report_archive/index.json 里记一条索引。超过保留天数的记录在写入时顺便清理。

HistoryManager 只存了摘要且 KV 无法列出全部键，做不了历史列表，所以单独归档。

模板自带的装饰图（local_image 内联的 data URI）每份报告都一样且体积很大（初音模板约 7 MB），
保存时替换成 local-image://<路径> 短标记，读取时再还原，避免归档重复占用磁盘。
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from ...utils.logger import logger

INDEX_FILE = "index.json"
EXPORT_FILE = ".download.html"
_LOCAL_IMAGE_MARK = "local-image://"
_LOCAL_IMAGE_PATTERN = re.compile(r"local-image://([\w./-]+)")
_SAFE_DIR_CHARS = re.compile(r"[^A-Za-z0-9_.-]")


class ReportArchive:
    def __init__(self, data_dir: str | Path, keep_days_getter):
        """
        Args:
            data_dir: 插件数据目录
            keep_days_getter: 返回保留天数的函数（读配置，<=0 表示永久保留）
        """
        self.base_dir = Path(data_dir) / "report_archive"
        self._keep_days_getter = keep_days_getter
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def add(
        self,
        html: str,
        *,
        group_id: str,
        group_name: str = "",
        platform_id: str = "",
        template: str = "",
        source: str = "",
        message_count: int = 0,
        participant_count: int = 0,
    ) -> str:
        """保存一份报告，返回报告 ID（同步，调用方用 asyncio.to_thread 执行）"""
        now = datetime.now()
        report_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        group_dir = _SAFE_DIR_CHARS.sub("_", str(group_id)) or "unknown"
        rel_path = f"{group_dir}/{report_id}.html"

        html = _compact_local_images(html)
        with self._lock:
            target = self.base_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html, encoding="utf-8")

            records = self._load_index()
            records.append(
                {
                    "id": report_id,
                    "group_id": str(group_id),
                    "group_name": group_name,
                    "platform_id": platform_id,
                    "created_at": now.timestamp(),
                    "template": template,
                    "source": source,
                    "message_count": int(message_count or 0),
                    "participant_count": int(participant_count or 0),
                    "file": rel_path,
                    "size": len(html.encode("utf-8")),
                }
            )
            records = self._cleanup(records)
            self._save_index(records)
        return report_id

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list(
        self,
        group_id: str = "",
        start: float | None = None,
        end: float | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """按群和时间范围筛选，倒序分页"""
        with self._lock:
            records = self._load_index()
        groups = {}
        for r in records:
            groups.setdefault(r["group_id"], r.get("group_name") or "")
            if r.get("group_name"):
                groups[r["group_id"]] = r["group_name"]

        items = [
            r
            for r in records
            if (not group_id or r["group_id"] == group_id)
            and (start is None or r["created_at"] >= start)
            and (end is None or r["created_at"] < end)
        ]
        items.sort(key=lambda r: r["created_at"], reverse=True)
        page = max(1, page)
        offset = (page - 1) * page_size
        return {
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "items": items[offset : offset + page_size],
            "groups": [{"group_id": k, "group_name": v} for k, v in groups.items()],
        }

    def get_html(self, report_id: str) -> str | None:
        """读取报告 HTML（已还原装饰图）"""
        record = self._find(report_id)
        if not record:
            return None
        path = self.base_dir / record["file"]
        if not path.is_file():
            return None
        return _expand_local_images(path.read_text(encoding="utf-8"))

    def get_record(self, report_id: str) -> dict | None:
        return self._find(report_id)

    def export_file(self, report_id: str) -> Path | None:
        """生成还原了装饰图的完整 HTML 文件供下载，返回文件路径"""
        html = self.get_html(report_id)
        if html is None:
            return None
        with self._lock:
            path = self.base_dir / EXPORT_FILE
            path.write_text(html, encoding="utf-8")
        return path

    def delete(self, report_id: str) -> bool:
        with self._lock:
            records = self._load_index()
            remaining = [r for r in records if r["id"] != report_id]
            if len(remaining) == len(records):
                return False
            for r in records:
                if r["id"] == report_id:
                    self._remove_file(r)
            self._save_index(remaining)
        return True

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _find(self, report_id: str) -> dict | None:
        with self._lock:
            return next((r for r in self._load_index() if r["id"] == report_id), None)

    def _cleanup(self, records: list[dict]) -> list[dict]:
        """删除超过保留天数的记录和文件"""
        try:
            keep_days = int(self._keep_days_getter() or 0)
        except (TypeError, ValueError):
            keep_days = 0
        if keep_days <= 0:
            return records
        cutoff = time.time() - keep_days * 86400
        kept = []
        for r in records:
            if r["created_at"] < cutoff:
                self._remove_file(r)
            else:
                kept.append(r)
        if len(kept) != len(records):
            logger.info(f"报告归档已清理 {len(records) - len(kept)} 份过期报告")
        return kept

    def _remove_file(self, record: dict) -> None:
        path = (self.base_dir / record["file"]).resolve()
        if path.is_relative_to(self.base_dir.resolve()) and path.is_file():
            path.unlink()

    def _load_index(self) -> list[dict]:
        index = self.base_dir / INDEX_FILE
        if not index.is_file():
            return []
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"读取报告归档索引失败: {e}")
            return []

    def _save_index(self, records: list[dict]) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        index = self.base_dir / INDEX_FILE
        tmp = index.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(index)


# reporting 包的 __init__ 会导入 generators（它又依赖本模块），这里在函数内导入以避免循环导入


def _compact_local_images(html: str) -> str:
    from ..reporting.templates import INLINED_LOCAL_IMAGES

    for rel_path, uri in list(INLINED_LOCAL_IMAGES.items()):
        if uri in html:
            html = html.replace(uri, _LOCAL_IMAGE_MARK + rel_path)
    return html


def _expand_local_images(html: str) -> str:
    from ..reporting.templates import local_image

    def restore(match: re.Match) -> str:
        try:
            return local_image(match.group(1))
        except Exception:
            # 新版本删掉了这张图时保留标记，只是这张图显示不出来
            return match.group(0)

    return _LOCAL_IMAGE_PATTERN.sub(restore, html)
