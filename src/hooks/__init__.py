"""
叙述 Hook 系统。

提供可扩展的 Hook 管道，在 LLM 叙述流程的关键节点自动注入逻辑。
"""

from .base import HookContext, NarrativeHook
from .pipeline import HookPipeline

__all__ = ["HookContext", "NarrativeHook", "HookPipeline"]
