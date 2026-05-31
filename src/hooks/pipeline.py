"""
Hook 管道：注册、排序、执行。
"""

from __future__ import annotations

import logging

from .base import HookContext, NarrativeHook

logger = logging.getLogger(__name__)


class HookPipeline:
    """管理 NarrativeHook 注册和按优先级执行。"""

    def __init__(self):
        self._hooks: list[NarrativeHook] = []

    def register(self, hook: NarrativeHook) -> None:
        """注册 hook，按 priority 升序插入。"""
        self._hooks.append(hook)
        self._hooks.sort(key=lambda h: h.priority)
        logger.info("Hook registered: %s (priority=%d)", hook.name, hook.priority)

    def unregister(self, hook_name: str) -> bool:
        """按名称移除 hook。"""
        for i, h in enumerate(self._hooks):
            if h.name == hook_name:
                self._hooks.pop(i)
                return True
        return False

    @property
    def hooks(self) -> list[NarrativeHook]:
        return list(self._hooks)

    def execute_before_narration(self, ctx: HookContext) -> list[dict]:
        """执行所有 hook 的 on_before_narration，收集 SSE 事件。"""
        events: list[dict] = []
        for hook in self._hooks:
            try:
                hook_events = hook.on_before_narration(ctx)
                if hook_events:
                    events.extend(hook_events)
            except Exception:
                logger.warning(
                    "Hook %s.on_before_narration failed", hook.name, exc_info=True
                )
        return events

    def execute_between_phases(self, ctx: HookContext) -> list[dict]:
        """执行所有 hook 的 on_between_phases，收集 SSE 事件。"""
        events: list[dict] = []
        for hook in self._hooks:
            try:
                hook_events = hook.on_between_phases(ctx)
                if hook_events:
                    events.extend(hook_events)
            except Exception:
                logger.warning(
                    "Hook %s.on_between_phases failed", hook.name, exc_info=True
                )
        return events

    def collect_prompt_injections(self, ctx: HookContext) -> str:
        """收集所有 hook 的 prompt 注入文本，用换行连接。"""
        parts: list[str] = []
        for hook in self._hooks:
            try:
                injection = hook.get_prompt_injection(ctx)
                if injection:
                    parts.append(injection)
            except Exception:
                logger.warning(
                    "Hook %s.get_prompt_injection failed", hook.name, exc_info=True
                )
        return "\n\n".join(parts)
