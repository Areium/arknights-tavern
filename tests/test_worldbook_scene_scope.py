"""角色入队 / 离队时世界书范围刷新 —— 走**真实 SceneManager 入口**。

审核反证：`SceneManager._refresh_worldbook_scope` 原本调用 v2 的
`resolve_import_scope(实际阵容)`，会把 v3 会话快照覆盖成一份 v2 结果：
绑定的不可变规则版本、手动追加、显式全量兼容、选用原因与参与边全部丢失。

这里不测「快照帮助函数」，也不测 FakeSession：直接构造真实
`SceneManager` + 真实 `WorldBookManager` + 真实 `SessionOverlay`，
调用 `load_character` / `unload_character`，断言快照没有被降级。
"""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from world_book import DEFAULT_CATEGORIES, WorldBook, WorldBookEntry, WorldBookManager
from worldbook_scope import (
    ACTIVATION_ALWAYS, ACTIVATION_ROSTER_ANY, EXPANSION_REQUIRES_CLOSURE,
)


def entry(uid, content=None, **kwargs):
    return WorldBookEntry(uid, content=content or f"content-{uid}",
                          always_active=True, **kwargs)


def book_fixture():
    return WorldBook("book", "测试书", [
        entry("world", "泰拉世界的基础设定，源石与天灾。", name="世界设定",
              category_id="worldview"),
        entry("a", "角色A：罗德岛干员。他使用源石技艺。", name="角色A",
              category_id="characters", character_id="A"),
        entry("b", "角色B：与角色A同属罗德岛。", name="角色B",
              category_id="characters", character_id="B"),
        entry("tech", "源石技艺的定义与规则。", name="源石技艺", category_id="other"),
    ], categories=copy.deepcopy(DEFAULT_CATEGORIES))


class StubCharacter:
    """替身只顶掉「读角色文件」这一层；SceneManager 的刷新逻辑是真实代码。"""

    def __init__(self, *args, **kwargs):
        self.character = object()


@pytest.fixture
def scene(tmp_path, monkeypatch):
    import session_overlay as overlay_module
    import SceneManager as scene_module

    monkeypatch.setattr(overlay_module, "_SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(scene_module, "CharacterAgent", StubCharacter)

    manager = WorldBookManager(tmp_path / "books")
    manager.save(book_fixture())

    overlay = overlay_module.SessionOverlay("s1", "free")
    manager_instance = manager
    scene_manager = scene_module.SceneManager(
        llm=None, registry=None, overlay=overlay,
        worldbook_manager=manager_instance)
    # 角色目录：直接注入，避免依赖真实角色文件
    overlay.set_worldbook_id("book")
    return scene_manager, overlay, manager


def make_v3(manager, roots, requires=None, related=None):
    book = manager.load("book")
    book.dependency_rules = {"roots": roots,
                             "root_rule": {"entry_uids": sorted(r["entry_uid"] for r in roots)}}
    book.dependency_edges = list(requires or [])
    book.related_edges = list(related or [])
    book.schema_version = 3
    book.import_config["revision"] = 2
    book.record_policy_revision()
    manager.save(book)
    return manager.load("book")


def test_load_character_keeps_bound_rule_version_and_reasons(scene):
    """入队后仍按**绑定版本**重算，规则被书改过也不跟着变，且解释不退化。"""
    scene_manager, overlay, manager = scene
    make_v3(manager, [
        {"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
         "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]},
        {"entry_uid": "b", "activation": ACTIVATION_ROSTER_ANY,
         "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["B"]},
    ], requires=[{"from_uid": "a", "to_uid": "tech"}])
    book = manager.load("book")
    bound = book.session_scope_snapshot(["A"], ["world"])
    overlay.set_worldbook_scope(bound)
    assert set(bound["resolved_entry_uids"]) == {"a", "tech", "world"}

    # 书随后被改成「不再需要 tech」——会话不该跟着变
    edited = manager.load("book")
    edited.dependency_edges = []
    edited.import_config["revision"] = 3
    edited.record_policy_revision()
    manager.save(edited)

    assert scene_manager.load_character("A") is True
    scope = overlay.get_worldbook_scope()
    assert scope["policy_revision"] == bound["policy_revision"], "入队把绑定版本换成了最新版本"
    assert scope["manual_entry_uids"] == ["world"], "入队丢了手动追加"
    assert "tech" in scope["resolved_entry_uids"], "入队后按最新规则重算，丢了绑定版本的内容"
    assert scope["selection_reasons"]["tech"] == ["requires"], "入队丢了选用原因"
    assert scope["resolved_edges"], "入队丢了参与边"
    assert scope["display_tree"], "入队丢了展示树"
    assert scope["rules"], "入队丢了绑定的规则本体"

    # 阵容继续变化（新增 B）时同样按绑定版本重算，而不是回落到最新规则
    assert scene_manager.load_character("B") is True
    scope = overlay.get_worldbook_scope()
    assert scope["policy_revision"] == bound["policy_revision"]
    assert set(scope["resolved_entry_uids"]) == {"a", "b", "tech", "world"}
    assert scope["selection_reasons"]["b"] == ["roster:B"]


def test_unload_character_keeps_manual_append_and_reasons(scene):
    """离队同样不能把快照降级成 v2 的 UID 列表。"""
    scene_manager, overlay, manager = scene
    make_v3(manager, [
        {"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
         "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]},
    ], requires=[{"from_uid": "a", "to_uid": "tech"}])
    book = manager.load("book")
    overlay.set_worldbook_scope(book.session_scope_snapshot(["A"], ["world"]))
    assert scene_manager.load_character("A") is True
    assert scene_manager.unload_character("A") is True

    scope = overlay.get_worldbook_scope()
    assert scope["schema_version"] == 3
    assert scope["manual_entry_uids"] == ["world"], "离队丢了手动追加"
    assert "world" in scope["resolved_entry_uids"]
    assert scope["selection_reasons"]["world"] == ["manual"], "离队丢了选用原因"
    assert "rules" in scope and scope["rules"], "离队把 v3 快照降级了"


def test_load_character_keeps_full_scope_flag(scene):
    """显式全量兼容不会被一次角色入队悄悄取消。"""
    scene_manager, overlay, manager = scene
    make_v3(manager, [
        {"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
         "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]},
    ])
    book = manager.load("book")
    overlay.set_worldbook_scope(book.session_scope_snapshot(["A"], [], None, True))
    assert scene_manager.load_character("B") is True
    scope = overlay.get_worldbook_scope()
    assert scope["full_scope"] is True, "入队把显式全量兼容取消了"
    assert set(scope["resolved_entry_uids"]) == {"world", "a", "b", "tech"}


def test_v2_session_still_uses_legacy_semantics(scene):
    """v2 会话保持旧语义：不因为角色入队就悄悄升级成 v3。"""
    scene_manager, overlay, manager = scene
    book = manager.load("book")
    assert not book.v3_enabled
    overlay.set_worldbook_scope(book.resolve_import_scope(["A"]))
    assert scene_manager.load_character("B") is True
    scope = overlay.get_worldbook_scope()
    assert "schema_version" not in scope or scope.get("schema_version") != 3
    assert scope["resolved_entry_uids"], "v2 会话入队后候选变空了"


def test_v2_explicit_full_scope_and_manual_fields_survive_roster_changes(scene):
    """v2 会话的显式全量覆盖是会话字段，入/离队不能把它换成当前书解析。"""
    scene_manager, overlay, manager = scene
    book = manager.load("book")
    scope = book.resolve_import_scope([])
    all_uids = sorted(entry.uid for entry in book.entries if entry.enabled and entry.content.strip())
    scope.update({"resolved_entry_uids": all_uids,
                  "selection_reasons": {uid: ["full_scope"] for uid in all_uids},
                  "full_scope": True, "legacy_full_scope": True,
                  "manual_entry_uids": ["tech"]})
    overlay.set_worldbook_scope(scope)
    assert scene_manager.load_character("A") is True
    after_load = overlay.get_worldbook_scope()
    assert after_load["full_scope"] is True
    assert after_load["manual_entry_uids"] == ["tech"]
    assert after_load["resolved_entry_uids"] == all_uids
    assert scene_manager.unload_character("A") is True
    after_unload = overlay.get_worldbook_scope()
    assert after_unload["full_scope"] is True
    assert after_unload["manual_entry_uids"] == ["tech"]
    assert after_unload["resolved_entry_uids"] == all_uids


def test_restore_does_not_recompute(scene):
    """恢复会话时不重算：磁盘上的快照就是真相。"""
    scene_manager, overlay, manager = scene
    make_v3(manager, [
        {"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
         "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]},
    ])
    book = manager.load("book")
    snapshot = book.session_scope_snapshot(["A"], ["world"])
    overlay.set_worldbook_scope(snapshot)
    scene_manager._restoring_scope = True
    try:
        scene_manager._refresh_worldbook_scope()
    finally:
        scene_manager._restoring_scope = False
    assert overlay.get_worldbook_scope() == snapshot


def test_scope_survives_overlay_roundtrip(scene, tmp_path):
    """快照经磁盘往返后仍是同一份（related 边、证据元数据都不能丢）。"""
    scene_manager, overlay, manager = scene
    make_v3(manager, [
        {"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
         "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]},
    ], requires=[{"from_uid": "a", "to_uid": "tech"}],
        related=[{"from_uid": "b", "to_uid": "a"}])
    book = manager.load("book")
    snapshot = book.session_scope_snapshot(["A"])
    overlay.set_worldbook_scope(snapshot)

    import session_overlay as overlay_module
    reloaded = overlay_module.SessionOverlay("s1", "free")
    assert reloaded.get_worldbook_scope() == snapshot
    assert reloaded.get_worldbook_scope()["related_edges"] == snapshot["related_edges"]
