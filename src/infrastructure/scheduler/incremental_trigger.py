"""
按群消息条数触发增量分析

每个增量群维护一个「待处理消息数」，攒够 incremental_min_messages 条就触发一次增量分析。
- 计数存进插件 KV，延迟 5 秒合并写入，重启后接着数
- 同一个群同时只跑一个增量任务
- 分析成功才扣掉计数；失败保留计数，冷却一段时间后由新消息重新触发
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

from ...utils.logger import logger
from ..config.config_manager import ConfigManager

AnalyzeCallback = Callable[[str, str], Awaitable[dict | None]]


class IncrementalTrigger:
    """维护每个群的待处理消息计数，并在达到阈值时触发增量分析"""

    KV_KEY = "incremental_trigger_counts_v1"
    SEEN_EVENT_LIMIT = 8192
    FLUSH_DELAY_SECONDS = 5
    # 分析失败后的冷却时间，避免模型故障时每来一条消息就重试一次
    FAILURE_COOLDOWN_SECONDS = 300

    def __init__(
        self,
        config_manager: ConfigManager,
        plugin,
        analyze_callback: AnalyzeCallback,
    ) -> None:
        self.config_manager = config_manager
        self.plugin = plugin
        self.analyze_callback = analyze_callback
        # key: platform_id:GroupMessage:group_id
        self._states: dict[str, dict] = {}
        self._loaded = False
        self._lock = asyncio.Lock()
        self._seen_event_ids: OrderedDict[str, None] = OrderedDict()
        self._tasks: dict[str, asyncio.Task] = {}
        self._cooldown_until: dict[str, float] = {}
        self._flush_task: asyncio.Task | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # 目标群判定
    # ------------------------------------------------------------------

    def is_target_group(self, umo: str) -> bool:
        """与定时调度的分层名单判定保持一致：准入名单 → 定时名单 → 增量名单"""
        cm = self.config_manager
        if not cm.get_incremental_enabled() or not cm.is_group_allowed(umo):
            return False
        if not cm.is_group_in_filtered_list(
            umo, cm.get_scheduled_group_list_mode(), cm.get_scheduled_group_list()
        ):
            return False
        return cm.is_group_in_filtered_list(
            umo, cm.get_incremental_group_list_mode(), cm.get_incremental_group_list()
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """恢复持久化的计数，并为已达到阈值的群安排分析"""
        await self._ensure_loaded()
        threshold = self.config_manager.get_incremental_min_messages()
        ready = [
            key
            for key, state in self._states.items()
            if state["count"] >= threshold and self.is_target_group(key)
        ]
        for key in ready:
            self._schedule_analysis(key)
        if self._states:
            logger.info(
                f"增量计数已恢复: {len(self._states)} 个群，立即触发 {len(ready)} 个"
            )

    async def close(self) -> None:
        """停止后台任务并保存尚未消费的计数"""
        self._closed = True
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        if self._loaded:
            await self.flush()

    # ------------------------------------------------------------------
    # 计数
    # ------------------------------------------------------------------

    async def record_message(
        self, platform_id: str, group_id: str, umo: str, message_id: str = ""
    ) -> None:
        """记录一条群消息，达到阈值时安排增量分析"""
        if self._closed or not platform_id or not group_id:
            return
        if not self.is_target_group(umo):
            return

        if message_id:
            # 同一条消息可能被重复投递，按消息 ID 去重
            event_key = f"{platform_id}:{group_id}:{message_id}"
            if event_key in self._seen_event_ids:
                return
            self._seen_event_ids[event_key] = None
            if len(self._seen_event_ids) > self.SEEN_EVENT_LIMIT:
                self._seen_event_ids.popitem(last=False)

        await self._ensure_loaded()
        key = f"{platform_id}:GroupMessage:{group_id}"
        async with self._lock:
            state = self._states.setdefault(
                key, {"platform_id": platform_id, "group_id": group_id, "count": 0}
            )
            state["count"] += 1
            count = state["count"]

        self._schedule_flush()
        if count >= self.config_manager.get_incremental_min_messages():
            self._schedule_analysis(key)

    def snapshot(self) -> list[dict]:
        """当前各群的计数状态，供 /增量状态 和 WebUI 展示"""
        threshold = self.config_manager.get_incremental_min_messages()
        now = time.monotonic()
        result = []
        for key, state in sorted(self._states.items()):
            cooldown = max(0, int(self._cooldown_until.get(key, 0) - now))
            result.append(
                {
                    "platform_id": state["platform_id"],
                    "group_id": state["group_id"],
                    "count": state["count"],
                    "threshold": threshold,
                    "running": key in self._tasks,
                    "cooldown_seconds": cooldown,
                    "enabled": self.is_target_group(key),
                }
            )
        return result

    async def ensure_loaded(self) -> None:
        """供状态查询使用：确保已从 KV 恢复计数"""
        await self._ensure_loaded()

    # ------------------------------------------------------------------
    # 分析调度
    # ------------------------------------------------------------------

    def _schedule_analysis(self, key: str) -> None:
        """同一个群同时只安排一个分析任务，失败冷却期内不重复触发"""
        if self._closed or key in self._tasks:
            return
        if time.monotonic() < self._cooldown_until.get(key, 0):
            return
        task = asyncio.create_task(self._run_analysis(key), name=f"incremental_{key}")
        self._tasks[key] = task

    async def _run_analysis(self, key: str) -> None:
        continue_after = False
        try:
            async with self._lock:
                state = self._states.get(key)
                if not state or not self.is_target_group(key):
                    return
                count_at_start = state["count"]
                platform_id = state["platform_id"]
                group_id = state["group_id"]

            if self._semaphore is None:
                self._semaphore = asyncio.Semaphore(
                    max(1, self.config_manager.get_max_concurrent_tasks())
                )
            async with self._semaphore:
                logger.info(
                    f"群 {group_id} 新消息已达 {count_at_start} 条，触发增量分析"
                )
                result = await self.analyze_callback(group_id, platform_id)

            result = result if isinstance(result, dict) else {}
            consumed = int(result.get("messages_count") or 0)
            reason = str(result.get("reason") or "")
            success = bool(result.get("success"))

            async with self._lock:
                state = self._states.get(key)
                if state:
                    new_arrivals = max(0, state["count"] - count_at_start)
                    if success:
                        state["count"] = max(0, state["count"] - consumed)
                        # 成功消费后如果还有积压，继续排空
                        continue_after = consumed > 0
                    elif reason == "below_threshold":
                        # 计数包含了指令等会被清理掉的消息，用实际可分析的条数校正
                        state["count"] = consumed + new_arrivals
                    elif reason == "no_messages":
                        state["count"] = new_arrivals
                    else:
                        self._cooldown_until[key] = (
                            time.monotonic() + self.FAILURE_COOLDOWN_SECONDS
                        )
                        logger.warning(
                            f"群 {group_id} 增量分析未成功（{reason or '未知原因'}），"
                            f"保留 {state['count']} 条计数，"
                            f"{self.FAILURE_COOLDOWN_SECONDS // 60} 分钟后由新消息重新触发"
                        )
            self._schedule_flush()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._cooldown_until[key] = time.monotonic() + self.FAILURE_COOLDOWN_SECONDS
            logger.error(f"按消息量触发增量分析失败: {e}", exc_info=True)
        finally:
            if self._tasks.get(key) is asyncio.current_task():
                self._tasks.pop(key, None)

        if continue_after and not self._closed:
            state = self._states.get(key)
            if state and state["count"] >= (
                self.config_manager.get_incremental_min_messages()
            ):
                self._schedule_analysis(key)

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            data = await self.plugin.get_kv_data(self.KV_KEY, {})
            states = data.get("states", {}) if isinstance(data, dict) else {}
            for key, raw in states.items():
                try:
                    self._states[str(key)] = {
                        "platform_id": str(raw["platform_id"]),
                        "group_id": str(raw["group_id"]),
                        "count": max(0, int(raw.get("count", 0))),
                    }
                except (KeyError, TypeError, ValueError):
                    continue
            self._loaded = True

    def _schedule_flush(self) -> None:
        """合并短时间内的计数更新，避免每条消息都写一次 KV"""
        if self._closed or (self._flush_task and not self._flush_task.done()):
            return
        self._flush_task = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self) -> None:
        try:
            await asyncio.sleep(self.FLUSH_DELAY_SECONDS)
            await self.flush()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"保存增量消息计数失败: {e}")

    async def flush(self) -> None:
        """立即保存当前计数"""
        async with self._lock:
            states = {k: dict(v) for k, v in self._states.items() if v["count"] > 0}
        await self.plugin.put_kv_data(
            self.KV_KEY, {"updated_at": time.time(), "states": states}
        )
