import logging
import traceback

from astrbot.api import logger as astrbot_logger

from ..shared.trace_context import TraceContext
from .log_buffer import log_buffer


class PluginLogger:
    """
    日志代理类：插件级统一日志装饰器

    自动向所有通过该实例输出的日志信息前缀添加 `[群分析插件]` 标签，
    以便用户在 AstrBot 混合日志流中快速定位属于本插件的输出。
    不直接继承 logging.LoggerAdapter 以符合框架规范。
    同时把日志复制一份到插件日志缓冲区，供 WebUI 插件日志页查看。
    """

    def __init__(self, prefix: str = "[群分析插件]"):
        self.prefix = prefix

    def _log(self, level: int, msg: str, *args, **kwargs):
        if not astrbot_logger.isEnabledFor(level):
            return
        trace_id = TraceContext.get()
        astrbot_logger.log(level, f"[{trace_id}] {self.prefix} {msg}", *args, **kwargs)
        try:
            text = str(msg) % args if args else str(msg)
            if kwargs.get("exc_info"):
                text += "\n" + traceback.format_exc().rstrip()
            log_buffer.append(logging.getLevelName(level), trace_id, text)
        except Exception:
            pass

    def info(self, msg: str, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        kwargs.setdefault("exc_info", True)
        self._log(logging.ERROR, msg, *args, **kwargs)


# 导出带前缀的 logger
logger = PluginLogger()
