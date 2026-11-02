"""
当前分析任务上下文

由任务登记表（application 层）在任务开始时设置；分析流程、报告生成（infrastructure 层）
通过这里汇报阶段、读取任务来源，不需要反向依赖 application 层。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

_current_task: ContextVar[Any] = ContextVar("analysis_task_record", default=None)


def bind_task(record: Any) -> Token:
    return _current_task.set(record)


def unbind_task(token: Token) -> None:
    _current_task.reset(token)


def current_task() -> Any:
    """当前协程所属的任务记录（带 source、group_name、stage 等属性），没有时返回 None"""
    return _current_task.get()


def set_stage(stage: str) -> None:
    """汇报当前分析任务所处的阶段（不在登记的任务里调用时什么都不做）"""
    record = _current_task.get()
    if record is not None:
        record.stage = stage


def set_task_group_name(group_name: str) -> None:
    record = _current_task.get()
    if record is not None and group_name:
        record.group_name = group_name


def mark_task_result(result: dict | None) -> None:
    """按分析结果标记任务状态：成功不处理，消息不足等正常跳过记为 skipped，其余记为 failed"""
    record = _current_task.get()
    if record is None or not isinstance(result, dict) or result.get("success"):
        return
    reason = str(result.get("reason") or "unknown")
    if reason in _SKIP_REASONS:
        record.skip(reason)
    else:
        record.fail(reason)


def mark_task_failed(reason: str) -> None:
    record = _current_task.get()
    if record is not None:
        record.fail(reason)


# 不算失败的跳过原因
_SKIP_REASONS = {
    "no_messages",
    "below_threshold",
    "muted",
    "already_running",
    "bot_not_ready",
    "terminating",
    "no_batches",
}
