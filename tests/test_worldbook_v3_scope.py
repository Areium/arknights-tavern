"""v3 依赖图解析：条件起点、requires 闭包、related 不扩张、环终止与可解释问题。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from worldbook_scope import (
    ACTIVATION_ALWAYS, ACTIVATION_MANUAL, ACTIVATION_ROSTER_ANY,
    EXPANSION_LEGACY_DEPTH, EXPANSION_NONE, EXPANSION_REQUIRES_CLOSURE,
    MAX_CLOSURE_NODES, resolve_v3_scope, validate_v3_rules, v2_rules_from_import_config,
)


class E:
    """最小条目替身：只需要 resolve_v3_scope 读取的字段。"""

    def __init__(self, uid, name="", enabled=True, content=None):
        self.uid = uid
        self.name = name or uid
        self.enabled = enabled
        self.content = f"content-{uid}" if content is None else content


def resolve(entries, roots, requires=(), related=(), roster=(), **kwargs):
    rules, req, rel = validate_v3_rules({e.uid for e in entries}, {
        "roots": roots,
        "requires_edges": [{"from_uid": a, "to_uid": b} for a, b in requires],
        "related_edges": [{"from_uid": a, "to_uid": b} for a, b in related],
    })
    return resolve_v3_scope(entries, rules, req, rel, roster_character_ids=list(roster), **kwargs)


def always(uid, expansion=EXPANSION_REQUIRES_CLOSURE, **kw):
    return {"entry_uid": uid, "activation": ACTIVATION_ALWAYS, "expansion": expansion, **kw}


def roster_root(uid, chars, expansion=EXPANSION_REQUIRES_CLOSURE):
    return {"entry_uid": uid, "activation": ACTIVATION_ROSTER_ANY,
            "expansion": expansion, "character_ids": list(chars)}


def test_single_character_does_not_activate_other_characters():
    """入队 A 只带出 A 自己的起点与它 requires 的内容，不激活 B 的整组。"""
    entries = [E("base"), E("a1"), E("a2"), E("b1"), E("b2")]
    result = resolve(
        entries,
        [always("base"), roster_root("a1", ["A"]), roster_root("b1", ["B"])],
        requires=[("a1", "a2"), ("b1", "b2")],
        roster=["A"],
    )
    assert set(result["resolved_entry_uids"]) == {"base", "a1", "a2"}
    assert "b1" not in result["resolved_entry_uids"]
    assert "b2" not in result["resolved_entry_uids"]
    assert result["selection_reasons"]["a2"] == ["requires"]
    assert result["selection_reasons"]["a1"] == ["roster:A"]


def test_dependency_pull_does_not_activate_that_characters_whole_group():
    """被依赖带入某个未入队角色的条目，不因此激活那位角色的整组条目。"""
    entries = [E("base"), E("a1"), E("b_bio"), E("b_secret"), E("b_group")]
    result = resolve(
        entries,
        [always("base"), roster_root("a1", ["A"]), roster_root("b_secret", ["B"])],
        requires=[("base", "b_bio"), ("b_secret", "b_group")],
        roster=["A"],
    )
    assert "b_bio" in result["resolved_entry_uids"]        # 作为依赖被补齐
    assert "b_secret" not in result["resolved_entry_uids"]  # 但不激活 B 的起点
    assert "b_group" not in result["resolved_entry_uids"]   # 也不带出 B 的整组
    assert result["selection_reasons"]["b_bio"] == ["requires"]


def test_shared_dependency_selected_once_and_leaving_roster_keeps_it():
    """共享依赖只选一次；移除某角色不会删掉另一角色仍然需要的内容。"""
    entries = [E("a1"), E("b1"), E("shared")]
    roots = [roster_root("a1", ["A"]), roster_root("b1", ["B"])]
    requires = [("a1", "shared"), ("b1", "shared")]

    both = resolve(entries, roots, requires=requires, roster=["A", "B"])
    assert both["resolved_entry_uids"].count("shared") == 1

    only_b = resolve(entries, roots, requires=requires, roster=["B"])
    assert set(only_b["resolved_entry_uids"]) == {"b1", "shared"}
    assert only_b["selection_reasons"]["shared"] == ["requires"]


def test_related_edges_never_expand_the_closure():
    """related 只浏览：不参与遍历，也不改变候选。"""
    entries = [E("root"), E("related_only"), E("requires_one")]
    result = resolve(
        entries,
        [always("root")],
        requires=[("root", "requires_one")],
        related=[("root", "related_only"), ("requires_one", "related_only")],
    )
    assert set(result["resolved_entry_uids"]) == {"root", "requires_one"}
    assert "related_only" not in result["resolved_entry_uids"]
    relations = {(e["from_uid"], e["to_uid"]): e["relation"] for e in result["resolved_edges"]}
    assert relations[("root", "related_only")] == "related"
    assert relations[("root", "requires_one")] == "requires"


def test_cycle_terminates_and_reports_cross_reference():
    entries = [E("a"), E("b"), E("c")]
    result = resolve(entries, [always("a")], requires=[("a", "b"), ("b", "c"), ("c", "a")])
    assert set(result["resolved_entry_uids"]) == {"a", "b", "c"}
    assert result["cross_references"] == [{"from_uid": "c", "to_uid": "a"}]
    # 树上每个节点恰好有一个父（环上不再重复挂载）
    parents = [n["parent_uid"] for n in result["display_tree"] if n["parent_uid"]]
    assert sorted(parents) == ["a", "b"]


def test_expansion_none_and_legacy_depth_keep_v2_semantics():
    entries = [E("x"), E("y"), E("z")]
    requires = [("x", "y"), ("y", "z")]

    none = resolve(entries, [always("x", EXPANSION_NONE)], requires=requires)
    assert set(none["resolved_entry_uids"]) == {"x"}

    depth0 = resolve(entries, [always("x", EXPANSION_LEGACY_DEPTH, max_depth=0)], requires=requires)
    assert set(depth0["resolved_entry_uids"]) == {"x"}

    depth1 = resolve(entries, [always("x", EXPANSION_LEGACY_DEPTH, max_depth=1)], requires=requires)
    assert set(depth1["resolved_entry_uids"]) == {"x", "y"}

    depth2 = resolve(entries, [always("x", EXPANSION_LEGACY_DEPTH, max_depth=2)], requires=requires)
    assert set(depth2["resolved_entry_uids"]) == {"x", "y", "z"}


def test_requires_closure_is_not_silently_truncated():
    """新必要闭包不按深度截断：链路任意长也完整展开。"""
    length = 60
    entries = [E(f"n{i}") for i in range(length)]
    requires = [(f"n{i}", f"n{i + 1}") for i in range(length - 1)]
    result = resolve(entries, [always("n0")], requires=requires)
    assert len(result["resolved_entry_uids"]) == length
    assert result["issues"] == []


def test_oversized_closure_reports_error_instead_of_truncating(monkeypatch):
    """超限时给出结构化问题并放弃解析，而不是悄悄截断成"看起来完整"。"""
    import worldbook_scope as module
    monkeypatch.setattr(module, "MAX_CLOSURE_NODES", 5)
    entries = [E(f"n{i}") for i in range(10)]
    requires = [(f"n{i}", f"n{i + 1}") for i in range(9)]
    rules, req, rel = validate_v3_rules(
        {e.uid for e in entries},
        {"roots": [always("n0")],
         "requires_edges": [{"from_uid": a, "to_uid": b} for a, b in requires]})
    result = module.resolve_v3_scope(entries, rules, req, rel)
    assert result["resolved_entry_uids"] == []
    assert result["issues"][0]["code"] == "closure_too_large"
    assert result["issues"][0]["severity"] == "error"


def test_manual_roots_are_never_auto_activated():
    entries = [E("auto"), E("manual_only")]
    result = resolve(entries, [always("auto"), {"entry_uid": "manual_only",
                                                "activation": ACTIVATION_MANUAL,
                                                "expansion": EXPANSION_REQUIRES_CLOSURE}])
    assert result["resolved_entry_uids"] == ["auto"]
    assert result["active_roots"] == [
        {"entry_uid": "auto", "activation": ACTIVATION_ALWAYS,
         "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": []}]


def test_disabled_and_empty_entries_are_reported_not_silently_complete():
    entries = [E("root"), E("off", enabled=False), E("blank", content="   ")]
    result = resolve(entries, [always("root")], requires=[("root", "off"), ("root", "blank")])
    codes = {i["code"]: i["uid"] for i in result["issues"]}
    assert codes["disabled_entry"] == "off"
    assert codes["empty_content"] == "blank"
    # 候选仍保留它们，由注入层按停用/空正文过滤——问题必须可解释
    assert "off" in result["resolved_entry_uids"]


def test_display_tree_has_single_root_per_branch_and_is_deterministic():
    entries = [E("r1"), E("r2"), E("shared"), E("leaf")]
    roots = [always("r1"), always("r2")]
    requires = [("r1", "shared"), ("r2", "shared"), ("shared", "leaf")]
    first = resolve(entries, roots, requires=requires)
    second = resolve(entries, roots, requires=requires)
    assert first["display_tree"] == second["display_tree"]
    assert [n["uid"] for n in first["display_tree"]].count("shared") == 1
    node = next(n for n in first["display_tree"] if n["uid"] == "shared")
    assert node["is_root"] is False and node["depth"] == 1
    assert node["root_uid"] in ("r1", "r2")
    # 子节点挂在唯一的父上
    assert node["child_uids"] == ["leaf"]


@pytest.mark.parametrize("bad", [
    {"roots": [{"entry_uid": "missing", "activation": ACTIVATION_ALWAYS}]},
    {"roots": [{"entry_uid": "a", "activation": "sometimes"}]},
    {"roots": [{"entry_uid": "a", "activation": ACTIVATION_ALWAYS, "expansion": "deep"}]},
    {"roots": [{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY}]},
    {"roots": [{"entry_uid": "a", "activation": ACTIVATION_ALWAYS, "character_ids": ["A"]}]},
    {"roots": [always("a"), always("a")]},
    {"roots": [always("a", EXPANSION_LEGACY_DEPTH, max_depth=33)]},
    {"roots": [always("a", EXPANSION_LEGACY_DEPTH, max_depth=None)]},
    {"roots": [always("a", EXPANSION_LEGACY_DEPTH, max_depth=True)]},
    {"roots": [always("a")], "requires_edges": [{"from_uid": "a", "to_uid": "a"}]},
    {"roots": [always("a")], "requires_edges": [{"from_uid": "a", "to_uid": "missing"}]},
    {"roots": [always("a")], "requires_edges": [{"from_uid": "a", "to_uid": "b"}] * 2},
    {"roots": [always("a")], "requires_edges": [{"from_uid": "a", "to_uid": "b"}],
     "related_edges": [{"from_uid": "a", "to_uid": "b"}]},
    {"roots": [always("a")], "root_rule": {"entry_uids": ["missing"]}},
    [],
])
def test_v3_validation_rejects_bad_shapes(bad):
    with pytest.raises(ValueError):
        validate_v3_rules({"a", "b"}, bad)


def test_v2_config_maps_to_v3_roots_losslessly():
    """旧 fixed → always+none；旧 sources → always+legacy_depth。"""
    rules, requires, related = v2_rules_from_import_config(
        {"fixed_entry_uids": ["f"], "dependency_sources": [{"entry_uid": "s", "max_depth": 3}]},
        [{"from_uid": "s", "to_uid": "t"}])
    by_uid = {r["entry_uid"]: r for r in rules["roots"]}
    assert by_uid["f"]["activation"] == ACTIVATION_ALWAYS
    assert by_uid["f"]["expansion"] == EXPANSION_NONE
    assert by_uid["s"]["expansion"] == EXPANSION_LEGACY_DEPTH
    assert by_uid["s"]["max_depth"] == 3
    assert requires == [{"from_uid": "s", "to_uid": "t"}]
    assert related == []
    assert MAX_CLOSURE_NODES > 0
