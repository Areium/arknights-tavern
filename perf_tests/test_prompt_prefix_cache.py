# -*- coding: utf-8 -*-
"""回归测试：逐轮动态叙事内容不得破坏稳定提示词前缀。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from SceneManager import SceneManager  # noqa: E402


class _Overlay:
    def __init__(self):
        self.docs = {
            "plot_state.md": "第一轮剧情结构",
            "plot_log.md": "第一轮剧情日志",
        }

    def has_plot_context(self):
        return False

    def read_session_doc(self, name):
        return self.docs.get(name, "")

    def get_custom_prompt(self):
        return None


class _SessionContext:
    def __init__(self):
        self.retrieved = "第一轮按需 Wiki"

    def format_preloaded(self):
        return "稳定预加载资料"

    def format_wiki_retrieved(self):
        return self.retrieved


class _Agent:
    metadata = {
        "scenario": "稳定角色场景",
        "first_mes": "{{char}}向{{user}}打招呼。",
    }


def _build_manager():
    overlay = _Overlay()
    session_context = _SessionContext()
    manager = SceneManager(
        None,
        None,
        overlay=overlay,
        session_context=session_context,
        combat_mode="narrative",
    )
    manager._agents["阿米娅"] = _Agent()
    manager.active = "阿米娅"
    manager._build_worldbook_parts = lambda *args, **kwargs: ("稳定常驻世界书", "")
    return manager, overlay, session_context


def test_dynamic_story_context_stays_after_stable_worldbook_prefix():
    manager, overlay, session_context = _build_manager()

    first = manager._build_narration_messages(
        {"identity": "博士"},
        "位置: 舰桥",
        user_action="继续调查",
        conversation_history="第一轮历史",
        is_first_turn=False,
    )[1]["content"]

    overlay.docs["plot_state.md"] = "第二轮剧情结构"
    overlay.docs["plot_log.md"] = "第二轮剧情日志"
    session_context.retrieved = "第二轮按需 Wiki"
    second = manager._build_narration_messages(
        {"identity": "博士"},
        "位置: 走廊",
        user_action="前往医务室",
        conversation_history="第二轮历史",
        is_first_turn=False,
    )[1]["content"]

    for content in (first, second):
        assert content.index("稳定常驻世界书") < content.index("<characters>")
        assert content.index("<characters>") < content.index("<story_context>")
        assert content.index("剧情结构") < content.index("<conversation_history>")
        assert content.index("剧情日志") < content.index("<conversation_history>")
        assert content.index("按需 Wiki") < content.index("<conversation_history>")

    # 动态剧情内容变化时，直到动态层开始前的稳定前缀必须逐字节一致。
    first_prefix = first[:first.index("<story_context>")]
    second_prefix = second[:second.index("<story_context>")]
    assert first_prefix == second_prefix


def test_first_turn_opening_setup_is_after_stable_prefix():
    manager, _, _ = _build_manager()
    content = manager._build_narration_messages(
        {"identity": "博士"},
        "位置: 舰桥",
        is_first_turn=True,
    )[1]["content"]

    assert content.index("稳定常驻世界书") < content.index("<characters>")
    assert content.index("<characters>") < content.index("<opening_setup>")
    assert "阿米娅向博士打招呼。" in content
