# 平台适配器
from .discord_adapter import DiscordAdapter
from .lark_adapter import LarkAdapter
from .onebot_adapter import OneBotAdapter
from .qq_official_history_adapter import QQOfficialHistoryAdapter

__all__ = [
    "OneBotAdapter",
    "DiscordAdapter",
    "LarkAdapter",
    "QQOfficialHistoryAdapter",
]
