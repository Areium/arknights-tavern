# -*- coding: utf-8 -*-
"""世界书注入链路集成测试：SceneManager 叙述 prompt 中的实际注入。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from SceneManager import SceneManager  # noqa: E402
from world_book import WorldBook, WorldBookEntry, WorldBookManager  # noqa: E402


def _entry(uid, content, position=0, **kw):
    return WorldBookEntry(uid=uid, content=content, position=position, **kw)


def test_narration_messages_inject_worldbook(tmp_path):
    mgr = WorldBookManager(data_dir=tmp_path)
    mgr.create_book("注入测试", entries=[
        # 常驻 position=0 → 稳定层；触发型 position=0 → 动态层（前缀缓存纪律）
        _entry("1", "凯尔希是罗德岛的医生。", position=0, always_active=True),
        _entry("2", "泰拉大陆存在源石病。", position=1, always_active=True),
        _entry("3", "这是触发型条目。", position=0, trigger_keys=["凯尔希"]),
    ])
    mgr.set_default_book_id(mgr.list_books()[0]["id"])

    sm = SceneManager(None, None, overlay=None, worldbook_manager=mgr,
                      combat_mode="narrative")
    messages = sm._build_narration_messages(
        {}, "", user_action="凯尔希走进办公室",
        conversation_history="博士：今天要谈矿石病的事。",
    )
    user_content = messages[1]["content"]

    # 三个条目都被注入
    assert "凯尔希是罗德岛的医生。" in user_content
    assert "泰拉大陆存在源石病。" in user_content
    assert "这是触发型条目。" in user_content

    # 常驻 position=0 在 <reference> 稳定层（位于 <characters> 之前）
    assert "<reference>" in user_content
    assert user_content.index("凯尔希是罗德岛的医生。") < user_content.index("<characters>")

    # position=1 与触发型 position=0 都在 <world_book> 动态层
    assert "<world_book>" in user_content
    wb = user_content.index("<world_book>")
    assert user_content.index("泰拉大陆存在源石病。") > wb
    assert user_content.index("这是触发型条目。") > wb


def test_narration_messages_no_worldbook_when_unbound(tmp_path):
    mgr = WorldBookManager(data_dir=tmp_path)
    sm = SceneManager(None, None, overlay=None, worldbook_manager=mgr,
                      combat_mode="narrative")
    messages = sm._build_narration_messages({}, "", user_action="凯尔希")
    user_content = messages[1]["content"]
    assert "【世界书】" not in user_content
    assert "<world_book>" not in user_content


def test_chat_mode_passes_worldbook_to_agent(tmp_path):
    """chat 模式下 SceneManager 解析世界书并传给 agent（假 agent 验证参数）。"""
    mgr = WorldBookManager(data_dir=tmp_path)
    mgr.create_book("聊天注入", entries=[
        _entry("1", "聊天场景条目。", position=0, trigger_keys=["凯尔希"]),
    ])
    mgr.set_default_book_id(mgr.list_books()[0]["id"])

    sm = SceneManager(None, None, overlay=None, worldbook_manager=mgr,
                      combat_mode="narrative")

    captured = {}

    class FakeAgent:
        metadata = {}

        def chat(self, *args, **kwargs):
            captured.update(kwargs)
            return "回复", {}, None

    sm._agents["阿米娅"] = FakeAgent()
    sm.active = "阿米娅"

    response, _env, _usage = sm.chat("凯尔希在哪", {"identity": "博士"}, "")
    assert response == "回复"
    assert captured.get("worldbook") is not None
    assert captured["worldbook"].id == mgr.list_books()[0]["id"]
    # 触发扫描文本包含当前输入
    matched = captured["worldbook"].collect_matches(captured["recent_text"], "凯尔希在哪")
    assert [e.uid for e in matched] == ["1"]
