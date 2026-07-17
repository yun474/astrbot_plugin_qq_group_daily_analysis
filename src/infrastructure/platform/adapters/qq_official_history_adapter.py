"""QQ 官方 Bot 适配器：从历史消息插件的 SQLite 缓存读取群消息。"""

from __future__ import annotations

import random
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from astrbot.core.message.components import File, Image, Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from ....domain.value_objects.platform_capabilities import PlatformCapabilities
from ....domain.value_objects.unified_group import UnifiedGroup, UnifiedMember
from ....domain.value_objects.unified_message import (
    MessageContent,
    MessageContentType,
    UnifiedMessage,
)
from ....utils.logger import logger
from ..base import PlatformAdapter


HISTORY_PLUGIN_NAME = "astrbot_plugin_quote_cache"
HISTORY_DB_FILENAME = "messages.sqlite3"


class QQOfficialHistoryAdapter(PlatformAdapter):
    """Use ``astrbot_plugin_quote_cache`` as QQ Official message history source."""

    platform_name = "qq_official"
    uses_history_cache = True

    def __init__(self, bot_instance: Any, config: dict | None = None):
        super().__init__(bot_instance, config)
        self.platform_id = str(self.config.get("platform_id") or "qq_official")
        self._context: Any | None = None
        self._history_db_path = (
            Path(get_astrbot_data_path())
            / "plugin_data"
            / HISTORY_PLUGIN_NAME
            / HISTORY_DB_FILENAME
        ).resolve()
        configured_ids = self.config.get("bot_self_ids", [])
        if isinstance(configured_ids, list):
            self.bot_self_ids = [str(item) for item in configured_ids if item]

    def set_context(self, context: Any):
        self._context = context

    def _init_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform_name="qq_official",
            platform_version="history_cache_v1",
            supports_message_history=True,
            max_message_history_days=3650,
            max_message_count=200000,
            supports_group_list=True,
            supports_group_info=True,
            supports_member_list=True,
            supports_member_info=True,
            supports_text_message=True,
            supports_image_message=True,
            supports_file_message=True,
            supports_forward_message=False,
            supports_reply_message=False,
            max_text_length=4000,
            supports_user_avatar=False,
            supports_group_avatar=False,
            avatar_needs_api_call=False,
            avatar_sizes=(100,),
        )

    @property
    def history_db_path(self) -> Path:
        return self._history_db_path

    def _connect_readonly(self) -> sqlite3.Connection:
        if not self._history_db_path.is_file():
            raise FileNotFoundError(
                "未找到历史消息缓存数据库。请先安装并启用 "
                f"{HISTORY_PLUGIN_NAME}: {self._history_db_path}"
            )
        db = sqlite3.connect(
            f"{self._history_db_path.as_uri()}?mode=ro",
            uri=True,
            timeout=5,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def _scope_key(self, group_id: str) -> str:
        return f"{self.platform_id}|group:{group_id}"

    def _row_to_message(self, row: sqlite3.Row, group_id: str) -> UnifiedMessage | None:
        content = str(row["content"] or "").strip()
        if not content:
            return None

        message_id = str(
            row["astr_message_id"]
            or row["original_message_id"]
            or f"history-cache:{row['id']}"
        )
        sender_id = str(row["sender_id"] or "")
        sender_name = str(row["sender_name"] or sender_id or "未知用户")
        contents = (MessageContent(type=MessageContentType.TEXT, text=content),)
        return UnifiedMessage(
            message_id=message_id,
            sender_id=sender_id,
            sender_name=sender_name,
            group_id=str(group_id),
            text_content=content,
            contents=contents,
            timestamp=int(row["timestamp"] or 0),
            platform="qq_official",
        )

    async def fetch_messages(
        self,
        group_id: str,
        days: int = 1,
        max_count: int = 1000,
        before_id: str | None = None,
        since_ts: int | None = None,
    ) -> list[UnifiedMessage]:
        """Read the newest matching rows, then return them in chronological order."""
        now = int(time.time())
        days = max(int(days or 1), 1)
        max_count = max(int(max_count or 1), 1)
        start_timestamp = (
            int(since_ts)
            if since_ts is not None and int(since_ts) > 0
            else now - days * 86400
        )

        clauses = [
            "scope_key=?",
            "timestamp>=?",
            "timestamp<=?",
            "expires_at>?",
            "is_bot=0",
            "content<>''",
        ]
        params: list[Any] = [
            self._scope_key(str(group_id)),
            start_timestamp,
            now,
            now,
        ]
        if before_id:
            try:
                clauses.append("id<?")
                params.append(int(before_id))
            except (TypeError, ValueError):
                logger.debug(
                    "[QQOfficialHistory] before_id 不是缓存记录 ID，忽略: %s",
                    before_id,
                )

        try:
            with closing(self._connect_readonly()) as db:
                rows = db.execute(
                    "SELECT id, astr_message_id, original_message_id, content, "
                    "sender_id, sender_name, timestamp FROM messages WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY timestamp DESC, id DESC LIMIT ?",
                    (*params, max_count),
                ).fetchall()
        except FileNotFoundError as exc:
            logger.error("[QQOfficialHistory] %s", exc)
            return []
        except sqlite3.Error:
            logger.exception(
                "[QQOfficialHistory] 读取缓存失败: db=%s scope=%s",
                self._history_db_path,
                self._scope_key(str(group_id)),
            )
            return []

        messages: list[UnifiedMessage] = []
        seen_ids: set[str] = set()
        for row in reversed(rows):
            message = self._row_to_message(row, str(group_id))
            if not message or message.message_id in seen_ids:
                continue
            messages.append(message)
            seen_ids.add(message.message_id)

        logger.info(
            "[QQOfficialHistory] 群 %s 从缓存读取 %s 条消息: days=%s max_count=%s db=%s",
            group_id,
            len(messages),
            days,
            max_count,
            self._history_db_path,
        )
        return messages

    def convert_to_raw_format(self, messages: list[UnifiedMessage]) -> list[dict]:
        return [
            {
                "message_id": message.message_id,
                "user_id": message.sender_id,
                "group_id": message.group_id,
                "time": message.timestamp,
                "sender": {
                    "user_id": message.sender_id,
                    "nickname": message.sender_name,
                    "card": message.sender_card or "",
                },
                "raw_message": message.text_content,
                "message": [{"type": "text", "data": {"text": message.text_content}}],
            }
            for message in messages
        ]

    async def get_group_list(self) -> list[str]:
        prefix = f"{self.platform_id}|group:"
        try:
            with closing(self._connect_readonly()) as db:
                rows = db.execute(
                    "SELECT DISTINCT scope_key FROM messages "
                    "WHERE scope_key LIKE ? AND expires_at>? ORDER BY scope_key",
                    (f"{prefix}%", int(time.time())),
                ).fetchall()
        except (FileNotFoundError, sqlite3.Error) as exc:
            logger.warning("[QQOfficialHistory] 读取已缓存群列表失败: %s", exc)
            return []
        return [str(row["scope_key"])[len(prefix) :] for row in rows]

    async def get_group_info(self, group_id: str) -> UnifiedGroup | None:
        members = await self.get_member_list(group_id)
        return UnifiedGroup(
            group_id=str(group_id),
            group_name=str(group_id),
            member_count=len(members),
            platform="qq_official",
        )

    async def get_member_list(self, group_id: str) -> list[UnifiedMember]:
        try:
            with closing(self._connect_readonly()) as db:
                rows = db.execute(
                    """SELECT sender_id, MAX(sender_name) AS sender_name
                    FROM messages WHERE scope_key=? AND expires_at>? AND is_bot=0
                    AND sender_id<>'' GROUP BY sender_id ORDER BY sender_id""",
                    (self._scope_key(str(group_id)), int(time.time())),
                ).fetchall()
        except (FileNotFoundError, sqlite3.Error) as exc:
            logger.warning("[QQOfficialHistory] 读取成员列表失败: %s", exc)
            return []
        return [
            UnifiedMember(
                user_id=str(row["sender_id"]),
                nickname=str(row["sender_name"] or row["sender_id"]),
            )
            for row in rows
        ]

    async def get_member_info(
        self, group_id: str, user_id: str
    ) -> UnifiedMember | None:
        try:
            with closing(self._connect_readonly()) as db:
                row = db.execute(
                    """SELECT sender_id, sender_name FROM messages
                    WHERE scope_key=? AND sender_id=? AND expires_at>?
                    ORDER BY timestamp DESC, id DESC LIMIT 1""",
                    (
                        self._scope_key(str(group_id)),
                        str(user_id),
                        int(time.time()),
                    ),
                ).fetchone()
        except (FileNotFoundError, sqlite3.Error):
            return None
        if not row:
            return None
        return UnifiedMember(
            user_id=str(row["sender_id"]),
            nickname=str(row["sender_name"] or row["sender_id"]),
        )

    def _session(self, group_id: str) -> str:
        return f"{self.platform_id}:GroupMessage:{group_id}"

    def _can_use_astrbot_proactive_send(self, group_id: str) -> bool:
        """Avoid Context.send_message's false-positive return on old QQ adapters."""
        manager = getattr(self._context, "platform_manager", None)
        platforms = getattr(manager, "platform_insts", None)
        if platforms is None:
            get_insts = getattr(manager, "get_insts", None)
            platforms = get_insts() if callable(get_insts) else []
        for platform in list(platforms or []):
            try:
                metadata = platform.meta()
                platform_id = str(getattr(metadata, "id", "") or "")
            except Exception:
                continue
            if platform_id != self.platform_id:
                continue
            scene_map = getattr(platform, "_session_scene", {})
            return bool(
                getattr(platform, "_allow_group_proactive_send", False)
                and isinstance(scene_map, dict)
                and scene_map.get(str(group_id)) == "group"
            )
        return False

    async def _send_chain(self, group_id: str, chain: MessageChain) -> bool:
        if self._context is None or not self._can_use_astrbot_proactive_send(group_id):
            return False
        try:
            return bool(
                await self._context.send_message(self._session(group_id), chain)
            )
        except NotImplementedError:
            return False
        except Exception:
            logger.exception(
                "[QQOfficialHistory] AstrBot 主动发送失败: group=%s", group_id
            )
            return False

    async def _send_text_direct(self, group_id: str, text: str) -> bool:
        api = getattr(self.bot, "api", None)
        post_group_message = getattr(api, "post_group_message", None)
        if not callable(post_group_message):
            return False
        try:
            result = await post_group_message(
                group_openid=str(group_id),
                msg_type=0,
                content=str(text),
                msg_seq=random.randint(1, 10000),
            )
            return result is not None
        except Exception:
            logger.exception(
                "[QQOfficialHistory] QQ 官方主动文本发送失败: group=%s", group_id
            )
            return False

    async def send_text(
        self, group_id: str, text: str, reply_to: str | None = None
    ) -> bool:
        if await self._send_text_direct(str(group_id), str(text)):
            return True
        return await self._send_chain(str(group_id), MessageChain([Plain(str(text))]))

    @staticmethod
    def _image_component(image_path: str) -> Image:
        source = str(image_path)
        if source.startswith(("http://", "https://")):
            return Image.fromURL(source)
        if source.startswith("base64://"):
            return Image.fromBase64(source[len("base64://") :])
        return Image.fromFileSystem(source)

    async def send_image(
        self, group_id: str, image_path: str, caption: str = ""
    ) -> bool:
        chain = [self._image_component(image_path)]
        if caption:
            chain.append(Plain(str(caption)))
        return await self._send_chain(str(group_id), MessageChain(chain))

    async def send_file(
        self, group_id: str, file_path: str, filename: str | None = None
    ) -> bool:
        name = filename or Path(file_path).name or "群分析报告"
        return await self._send_chain(
            str(group_id),
            MessageChain([File(name=name, file=str(file_path))]),
        )

    async def get_user_avatar_url(self, user_id: str, size: int = 100) -> str | None:
        return None

    async def get_user_avatar_data(self, user_id: str, size: int = 100) -> str | None:
        return None

    async def get_group_avatar_url(self, group_id: str, size: int = 100) -> str | None:
        return None

    async def batch_get_avatar_urls(
        self, user_ids: list[str], size: int = 100
    ) -> dict[str, str | None]:
        return {str(user_id): None for user_id in user_ids}
