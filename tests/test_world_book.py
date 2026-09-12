# -*- coding: utf-8 -*-
"""世界书模块测试：解析器（4 源）+ 触发语义 + 注入 + 管理器。

注意：tests/ 目录被 .gitignore 忽略（仓库约定），仅本地运行。
运行：python -m pytest tests/test_world_book.py -v
"""

import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from world_book import (  # noqa: E402
    SOURCE_CARD,
    SOURCE_JSONL,
    SOURCE_V1,
    SOURCE_V2,
    WorldBook,
    WorldBookEntry,
    WorldBookManager,
    parse_lorebook,
)

IDENTITY = "博士"


# ─────────────────────────── 解析器 ───────────────────────────

def test_parse_v1_full_mapping():
    data = {
        "entries": {
            "0": {
                "uid": 1,
                "key": ["凯尔希", "Kalt'sit"],
                "keysecondary": ["罗德岛"],
                "comment": "凯尔希设定",
                "content": "凯尔希是罗德岛的医生。",
                "constant": False,
                "selective": True,
                "insertion_order": 0,
                "enabled": True,
                "position": 0,
                "depth": 3,
                "scanDepth": 6,
                "probability": 50,
                "useProbability": True,
                "group": "罗德岛",
                "groupWeight": 120,
                "caseSensitive": True,
                "matchWholeWords": True,
                "excludeRecursion": True,
                "extensions": {"automationId": "auto_1"},
            }
        }
    }
    entries, report = parse_lorebook(data)
    assert report.source_format == SOURCE_V1
    assert report.imported == 1
    e = entries[0]
    assert e.uid == "1"
    assert e.trigger_keys == ["凯尔希", "Kalt'sit"]
    assert e.secondary_keys == ["罗德岛"]
    assert e.name == "凯尔希设定"
    assert e.selective is True and e.always_active is False
    assert e.position == 0 and e.depth == 3 and e.scan_depth == 6
    assert e.probability == 50
    assert e.group == "罗德岛" and e.group_weight == 120
    assert e.case_sensitive is True and e.match_whole_words is True
    assert e.raw.get("extensions", {}).get("automationId") == "auto_1"


def test_parse_v1_position_strings_and_string_keys():
    data = {"entries": {"0": {"key": "A, B", "content": "x", "position": "after_char"}}}
    entries, _ = parse_lorebook(data)
    assert entries[0].position == 1
    assert entries[0].trigger_keys == ["A", "B"]


def test_parse_v2_spec():
    data = {
        "entries": [
            {
                "keys": ["源石"],
                "secondary_keys": ["矿石病"],
                "comment": "源石",
                "content": "源石是泰拉大陆的能源。",
                "constant": False,
                "insertion_order": 1,
                "enabled": True,
                "position": "after_char",
                "extensions": {"position": 1, "depth": 2, "probability": 80},
                "case_sensitive": False,
                "match_whole_words": False,
            }
        ]
    }
    entries, report = parse_lorebook(data)
    assert report.source_format == SOURCE_V2
    e = entries[0]
    assert e.trigger_keys == ["源石"] and e.secondary_keys == ["矿石病"]
    assert e.position == 1 and e.depth == 2 and e.probability == 80


def test_parse_character_card_v2():
    card = {
        "spec": "chara_card_v2",
        "data": {
            "name": "测试角色",
            "character_book": {
                "name": "内嵌世界书",
                "entries": [{"keys": ["龙"], "content": "龙族设定。"}],
            },
        },
    }
    entries, report = parse_lorebook(card)
    assert report.source_format == SOURCE_CARD
    assert len(entries) == 1 and entries[0].trigger_keys == ["龙"]


def test_parse_character_card_v1_extensions_world():
    card = {
        "data": {
            "extensions": {
                "world": {"entries": {"5": {"key": ["雪原"], "content": "雪原设定。"}}}
            }
        }
    }
    entries, report = parse_lorebook(card)
    assert report.source_format == SOURCE_CARD
    assert len(entries) == 1 and entries[0].trigger_keys == ["雪原"]


def test_parse_jsonl_backup():
    text = (
        json.dumps({"name": "user", "mes": "hi", "world": {
            "entries": {"1": {"key": ["A"], "content": "a"}}}}) + "\n"
        + json.dumps({"name": "assistant", "mes": "hello"}) + "\n"
        + json.dumps({"name": "user", "mes": "x", "world": {
            "entries": {"1": {"key": ["A"], "content": "a"},
                        "2": {"key": ["B"], "content": "b"}}}}) + "\n"
    )
    entries, report = parse_lorebook(text)
    assert report.source_format == SOURCE_JSONL
    assert len(entries) == 2  # uid 1 去重


def test_parse_skip_empty_and_warn():
    data = {"entries": {
        "0": {"key": ["A"], "content": "  "},
        "1": {"key": ["B"], "content": "有效"},
    }}
    entries, report = parse_lorebook(data)
    assert report.imported == 1 and report.skipped == 1
    assert entries[0].trigger_keys == ["B"]
    assert any("内容为空" in w for w in report.warnings)


def test_parse_single_entry_object():
    entries, _ = parse_lorebook({"key": ["风"], "content": "风起。"})
    assert len(entries) == 1 and entries[0].trigger_keys == ["风"]


def test_parse_legacy_disable_field():
    """旧版酒馆用 disable 表示停用（无 enabled 字段）。"""
    data = {"entries": {
        "0": {"key": ["A"], "content": "停用的", "disable": True},
        "1": {"key": ["B"], "content": "启用的", "disable": False},
        "2": {"key": ["C"], "content": "默认启用"},
    }}
    entries, _ = parse_lorebook(data)
    by_uid = {e.uid: e for e in entries}
    assert by_uid["0"].enabled is False
    assert by_uid["1"].enabled is True
    assert by_uid["2"].enabled is True


def test_export_st_legacy_disable_roundtrip():
    """raw 使用 disable 的条目，导出时保持 disable 写法。"""
    raw = {"uid": 5, "key": ["A"], "content": "x", "disable": True}
    entry = WorldBookEntry(uid="5", content="x", trigger_keys=["A"],
                           enabled=False, raw=raw)
    out = WorldBook("t", "x", [entry]).export_st()["entries"]["5"]
    assert out["disable"] is True and "enabled" not in out


def test_parse_empty_returns_report():
    entries, report = parse_lorebook('{"foo": 1}')
    assert entries == [] and report.imported == 0
    assert report.warnings


# ─────────────────────────── 触发语义 ───────────────────────────

def _book(entries):
    return WorldBook("t", "测试", entries)


def _e(uid="1", content="内容", **kw):
    return WorldBookEntry(uid=uid, content=content, **kw)


def test_constant_always_matches():
    book = _book([_e(always_active=True)])
    assert len(book.collect_matches("", "任何输入")) == 1


def test_selective_requires_primary_and_secondary():
    e = _e(trigger_keys=["凯尔希"], secondary_keys=["罗德岛"], selective=True)
    assert len(_book([e]).collect_matches("", "凯尔希今天不在")) == 0
    assert len(_book([e]).collect_matches("", "凯尔希在罗德岛等你")) == 1


def test_selective_without_secondary_only_needs_primary():
    e = _e(trigger_keys=["阿米娅"], secondary_keys=[], selective=True)
    assert len(_book([e]).collect_matches("", "阿米娅来了")) == 1


def test_non_selective_secondary_acts_as_primary():
    e = _e(trigger_keys=["A"], secondary_keys=["B"], selective=False)
    assert len(_book([e]).collect_matches("", "只有 B 出现")) == 1


def test_case_sensitive():
    e = _e(trigger_keys=["Doctor"], case_sensitive=True)
    assert len(_book([e]).collect_matches("", "doctor is here")) == 0
    assert len(_book([e]).collect_matches("", "Doctor is here")) == 1


def test_match_whole_words():
    e = _e(trigger_keys=["cat"], match_whole_words=True)
    assert len(_book([e]).collect_matches("", "a cat sat")) == 1
    assert len(_book([e]).collect_matches("", "concatenate")) == 0


def test_regex_key_and_invalid_regex_fallback():
    e1 = _e(uid="1", trigger_keys=["源石\\d+"])
    e2 = _e(uid="2", trigger_keys=["broken[key"], content="字面量")
    book = _book([e1, e2])
    assert [e.uid for e in book.collect_matches("", "我拿到源石3号")] == ["1"]
    assert [e.uid for e in book.collect_matches("", "这是 broken[key 文本")] == ["2"]


def _rng_first_ge(value: float) -> random.Random:
    """返回首个 random() >= value 的确定性随机源。"""
    for seed in range(2000):
        rng = random.Random(seed)
        if rng.random() >= value:
            return random.Random(seed)
    raise AssertionError("未找到合适种子")


def test_probability_roll():
    e = _e(probability=50)
    rng = _rng_first_ge(0.5)
    assert _book([e]).collect_matches("", "x", rng=rng) == []


def test_disabled_entry_not_matched():
    e = _e(trigger_keys=["A"], enabled=False)
    assert _book([e]).collect_matches("", "A") == []


def test_sorting_order():
    a = _e(uid="a", position=0, group_weight=100, depth=4, trigger_keys=["x"])
    b = _e(uid="b", position=0, group_weight=200, depth=9, trigger_keys=["x"])
    c = _e(uid="c", position=1, group_weight=300, depth=1, trigger_keys=["x"])
    book = _book([c, a, b])
    matched = book.collect_matches("", "x")
    assert [e.uid for e in matched] == ["b", "a", "c"]


# ─────────────────────────── 注入格式化 ───────────────────────────

def test_format_split_by_position_and_macros():
    before_e = _e(uid="1", position=0,
                  content="{{user}}是{{char}}的医生。", name="关系",
                  always_active=True)
    after_e = _e(uid="2", position=1, content="只含 user：{{user}}", name="后置",
                 trigger_keys=["x"])
    book = _book([after_e, before_e])
    before, after = book.format_injection(
        book.collect_matches("", "x"), identity=IDENTITY, active_char="凯尔希")
    assert "【世界书】" in before and "### 关系" in before
    assert "博士是凯尔希的医生" in before
    assert "### 后置" in after and "只含 user：博士" in after
    assert "{{char}}" not in before + after


def test_format_triggered_position0_forced_to_dynamic_layer():
    """前缀缓存纪律：触发型条目即使声明 position=0 也进动态层。"""
    triggered = _e(uid="1", position=0, content="触发内容", trigger_keys=["x"])
    constant = _e(uid="2", position=0, content="常驻内容", always_active=True)
    book = _book([triggered, constant])
    before, after = book.format_injection(book.collect_matches("", "x"),
                                          identity=IDENTITY)
    assert "常驻内容" in before
    assert "触发内容" not in before
    assert "触发内容" in after


def test_format_char_empty_in_narrative():
    e = _e(position=0, content="他看向{{char}}。", always_active=True)
    book = _book([e])
    before, _ = book.format_injection(book.collect_matches("", "x"),
                                      identity=IDENTITY, active_char=None)
    assert "他看向。" in before


def test_budget_truncation_keeps_first():
    long_e1 = _e(uid="1", position=0, content="字" * 100, always_active=True)
    long_e2 = _e(uid="2", position=0, content="字" * 100, always_active=True)
    book = _book([long_e1, long_e2])
    book.budget_tokens = 60
    before, _ = book.format_injection(book.collect_matches("", "x"),
                                      identity=IDENTITY)
    assert len(before) < 200  # 第二条被截断


def test_export_st_roundtrip():
    raw = {"uid": 9, "key": ["A"], "comment": "原始", "content": "旧内容",
           "constant": False, "enabled": True, "insertion_order": 1,
           "automationId": "auto_9"}
    entry = WorldBookEntry(uid="9", content="新内容", trigger_keys=["A"],
                           name="原始", position=1, raw=raw)
    book = _book([entry])
    out = book.export_st()
    st_entry = out["entries"]["9"]
    assert st_entry["content"] == "新内容"
    assert st_entry["automationId"] == "auto_9"  # raw 字段保留
    assert st_entry["key"] == ["A"]


# ─────────────────────────── 管理器 ───────────────────────────

class _FakeOverlay:
    def __init__(self, book_id=None):
        self._book_id = book_id

    def get_worldbook_id(self):
        return self._book_id

    def set_worldbook_id(self, book_id):
        self._book_id = book_id


def test_manager_crud_and_resolve(tmp_path):
    mgr = WorldBookManager(data_dir=tmp_path)
    book = mgr.create_book("测试书", entries=[_e(uid="1")])
    assert mgr.load(book.id).name == "测试书"
    assert len(mgr.list_books()) == 1

    # 无绑定无默认 → None
    assert mgr.resolve(_FakeOverlay()) is None

    # 默认书回落
    mgr.set_default_book_id(book.id)
    assert mgr.resolve(_FakeOverlay()) is not None

    # 会话绑定优先于默认书
    book2 = mgr.create_book("第二本")
    overlay = _FakeOverlay(book2.id)
    assert mgr.resolve(overlay).id == book2.id

    # 删除默认书清空默认
    mgr.delete_book(book.id)
    assert mgr.get_default_book_id() is None
    assert len(mgr.list_books()) == 1


def test_import_book_via_manager(tmp_path):
    mgr = WorldBookManager(data_dir=tmp_path)
    book, report = mgr.import_book(
        "导入", {"entries": {"0": {"key": ["A"], "content": "内容"}}})
    assert report.imported == 1 and report.source_format == SOURCE_V1
    assert book.name == "导入"
