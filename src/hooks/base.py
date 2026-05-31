"""
叙述 Hook 抽象基类与上下文数据类。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HookContext:
    """传递给每个 hook 的上下文，包含当前叙述循环的所有相关数据。"""

    session: Any
    player_info: dict
    user_action: str
    env_context: str
    stream_id: str = ""
    narrative_text: str | None = None
    metadata: dict = field(default_factory=dict)


class NarrativeHook(ABC):
    """叙述 Hook 抽象基类。

    子类覆写一个或多个 hook 方法以在叙述流程中插入逻辑。
    所有方法默认返回空，异常由管道捕获不中断主流程。
    """

    @property
    def priority(self) -> int:
        """优先级：数字越小越先执行。默认 100。"""
        return 100

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def on_before_narration(self, ctx: HookContext) -> list[dict]:
        """两轮叙述之间执行（Round N 结束后，Round N+1 Phase 1 前）。

        Returns:
            SSE 事件列表，每个元素为可 JSON 序列化的 dict。
        """
        return []

    def on_between_phases(self, ctx: HookContext) -> list[dict]:
        """Phase 1 和 Phase 2 之间执行（ctx.narrative_text 已填充）。"""
        return []

    def get_prompt_injection(self, ctx: HookContext) -> str | None:
        """返回要注入到下一阶段 LLM prompt 的文本。

        - on_before_narration 之后：注入到 Phase 1
        - on_between_phases 之后：注入到 Phase 2
        """
        return None
