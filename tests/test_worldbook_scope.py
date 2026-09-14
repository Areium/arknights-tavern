"""世界书按需载入：范围、迁移、API 原子性与两个 prompt 入口。"""
import copy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from world_book import WorldBook, WorldBookEntry, WorldBookManager, DEFAULT_CATEGORIES
from worldbook_scope import validate_categories, validate_policy


def entry(uid, **kwargs):
    return WorldBookEntry(uid, content=f"content-{uid}", always_active=True, **kwargs)


def book_fixture():
    return WorldBook("book", "测试书", [
        entry("world", category_id="worldview"),
        entry("a", category_id="squad", character_id="A"),
        entry("b", category_id="characters", character_id="B"),
        entry("x", category_id="other"), entry("y", category_id="other"),
        entry("z", category_id="other"), entry("disabled", category_id="other", enabled=False),
    ], categories=copy.deepcopy(DEFAULT_CATEGORIES) + [
        {"id": "faction", "name": "势力", "parent_id": "characters", "scope_type": "character", "sort_order": 1},
        {"id": "squad", "name": "队伍", "parent_id": "faction", "scope_type": "character", "sort_order": 1},
    ], dependency_edges=[{"from_uid": "x", "to_uid": "y"}, {"from_uid": "y", "to_uid": "z"}, {"from_uid": "z", "to_uid": "x"}])


@pytest.mark.parametrize("depth,expected", [(0, {"x"}), (1, {"x", "y"}), (2, {"x", "y", "z"}), (32, {"x", "y", "z"})])
def test_depth_and_cycle(depth, expected):
    book = book_fixture()
    book.import_config["dependency_sources"] = [{"entry_uid": "x", "max_depth": depth}]
    result = book.resolve_import_scope(["A", "A"])
    assert set(result["resolved_entry_uids"]) == {"world", "a"} | expected
    assert result["roster_character_ids"] == ["A"]
    assert "b" not in result["resolved_entry_uids"]


def test_fixed_does_not_expand_and_multiple_sources_use_best_remaining_depth():
    book = book_fixture()
    book.import_config["fixed_entry_uids"] = ["x", "disabled"]
    assert set(book.resolve_import_scope()["resolved_entry_uids"]) == {"world", "x"}
    book.import_config["dependency_sources"] = [{"entry_uid": "y", "max_depth": 0}, {"entry_uid": "x", "max_depth": 2}]
    preview = book.preview_scope()
    assert set(preview["scope"]["resolved_entry_uids"]) == {"world", "x", "y", "z"}
    assert preview["scope"]["excluded_entries"] == [{"uid": "disabled", "name": "", "reason": "条目已停用"}]
    assert preview["entry_count"] == 4
    assert [len(s["entries"]) for s in preview["source_expansions"]] == [1, 3]
    assert 0 < preview["saved_percent"] < 100


def test_preview_expands_each_source_once_not_once_per_entry(monkeypatch):
    import world_book as module
    book = book_fixture()
    book.import_config["dependency_sources"] = [
        {"entry_uid": "x", "max_depth": 2}, {"entry_uid": "y", "max_depth": 0},
    ]
    original = module.expand_sources
    traversals = []

    def counted(sources, edges):
        traversals.append(len(sources))
        return original(sources, edges)

    monkeypatch.setattr(module, "expand_sources", counted)
    preview = book.preview_scope()
    assert traversals == [2, 1, 1]
    assert [len(source["entries"]) for source in preview["source_expansions"]] == [3, 1]


@pytest.mark.parametrize("value", [-1, 33, 1.5, "2", True, None])
def test_policy_rejects_invalid_depth(value):
    with pytest.raises(ValueError, match="深度"):
        validate_policy({"a"}, {"dependency_sources": [{"entry_uid": "a", "max_depth": value}]})


@pytest.mark.parametrize("payload", [
    {"fixed_entry_uids": ["missing"]}, {"fixed_entry_uids": ["a", "a"]},
    {"dependency_sources": [{"entry_uid": "a", "max_depth": 0}] * 2},
    {"dependency_edges": [{"from_uid": "a", "to_uid": "b"}] * 2},
    {"dependency_edges": [{"from_uid": "a", "to_uid": "missing"}]},
    {"dependency_edges": [None]}, {"dependency_sources": "a"}, [],
])
def test_policy_rejects_bad_references_and_shapes(payload):
    with pytest.raises(ValueError):
        validate_policy({"a", "b"}, payload)


@pytest.mark.parametrize("kind", ["cycle", "orphan", "duplicate", "cross_type", "bad_order"])
def test_taxonomy_validation(kind):
    categories = [
        {"id": "a", "name": "a", "parent_id": None, "scope_type": "other"},
        {"id": "b", "name": "b", "parent_id": "a", "scope_type": "other"},
    ]
    if kind == "cycle": categories[0]["parent_id"] = "b"
    if kind == "orphan": categories[0]["parent_id"] = "missing"
    if kind == "duplicate": categories.append(dict(categories[0]))
    if kind == "cross_type": categories[1]["scope_type"] = "character"
    if kind == "bad_order": categories[0]["sort_order"] = "x"
    with pytest.raises(ValueError): validate_categories(categories)


def test_plain_import_is_legacy_and_roundtrip_duplicate_keep_private_metadata(tmp_path):
    manager = WorldBookManager(tmp_path)
    legacy, _ = manager.import_book("旧书", {"entries": {"a": {"content": "A", "constant": True}}})
    assert legacy.schema_version == 2 and legacy.scope_mode == "legacy"
    assert legacy.entries[0].category_id == "unclassified"
    legacy.categories = validate_categories(DEFAULT_CATEGORIES)
    assert legacy.resolve_import_scope()["resolved_entry_uids"] == ["a"]
    book = book_fixture()
    book.import_config["fixed_entry_uids"] = ["x"]
    book.import_config["dependency_sources"] = [{"entry_uid": "y", "max_depth": 1}]
    manager.save(book)
    restored, _ = manager.import_book("回灌", json.dumps(book.export_st()))
    assert restored.categories == book.categories
    assert restored.scope_mode == "selective"
    assert restored.dependency_edges == book.dependency_edges
    assert restored.import_config == book.import_config
    assert restored.entries[1].character_id == "A"
    assert restored.resolve_import_scope(["A"])["resolved_entry_uids"] == book.resolve_import_scope(["A"])["resolved_entry_uids"]
    duplicate = manager.duplicate_book(book.id)
    assert duplicate.categories == book.categories and duplicate.import_config == book.import_config
    duplicate.entries[0].content = "changed"
    duplicate.categories[0]["name"] = "changed"
    assert book.entries[0].content != "changed" and book.categories[0]["name"] != "changed"


def test_builtin_migration_uses_generator_uid_and_external_books_are_not_guessed():
    payload = {"id": "arknights", "source": "preinstalled", "entries": [
        entry("characters_A_index").to_dict(), entry("world_terra").to_dict(), entry("characters_B_index").to_dict(),
    ]}
    book = WorldBook.from_dict(payload)
    assert set(book.resolve_import_scope(["A"])["resolved_entry_uids"]) == {"characters_A_index", "world_terra"}
    payload["source"] = "imported"
    assert WorldBook.from_dict(payload).scope_mode == "legacy"


class Overlay:
    def __init__(self, scope=None): self.scope, self.book_id = copy.deepcopy(scope), None
    def get_worldbook_scope(self): return copy.deepcopy(self.scope)
    def set_worldbook_scope(self, value): self.scope = copy.deepcopy(value)
    def get_worldbook_id(self): return self.book_id
    def set_worldbook_id(self, value): self.book_id = value


def test_frozen_scope_and_explicit_no_book_do_not_fall_back(tmp_path):
    manager = WorldBookManager(tmp_path)
    book = book_fixture()
    manager.save(book)
    manager.set_default_book_id(book.id)
    overlay = Overlay(book.resolve_import_scope(["A"]))
    book.import_config["fixed_entry_uids"] = ["b"]
    assert book.eligible_uids_for(overlay) == {"world", "a"}
    assert book.eligible_uids_for(Overlay({"book_id": "different", "resolved_entry_uids": ["b"]})) == set()
    assert manager.resolve(Overlay({"book_id": None, "resolved_entry_uids": []})) is None
    book.enabled = False
    assert manager.resolve(overlay) is None


def test_legacy_session_gets_frozen_full_snapshot_and_content_stays_live():
    book = book_fixture()
    overlay = Overlay()
    before = book.eligible_uids_for(overlay)
    assert before == {e.uid for e in book.entries if e.enabled}
    assert overlay.scope["legacy_full_scope"] is True
    book.entries.append(entry("new"))
    book.entries[0].content = "updated content"
    assert book.eligible_uids_for(overlay) == before
    assert "updated content" in book.format_injection(book.collect_matches("", "", eligible_uids=before))[0]


def test_roster_changes_refresh_scope_but_restore_keeps_snapshot(tmp_path, monkeypatch):
    import SceneManager as scene_module
    manager = WorldBookManager(tmp_path)
    book = book_fixture()
    manager.save(book)
    overlay = Overlay(book.resolve_import_scope(["A"]))
    scene = scene_module.SceneManager(None, None, worldbook_manager=manager)
    scene._overlay, scene._agents, scene.active = overlay, {"A": object()}, "A"
    monkeypatch.setattr(scene, "_persist_scene", lambda: None)
    monkeypatch.setattr(overlay, "get_character_overrides", lambda _: {}, raising=False)
    monkeypatch.setattr(overlay, "get_index_config", lambda: None, raising=False)
    monkeypatch.setattr(scene_module, "CharacterAgent", lambda *args, **kwargs: SimpleNamespace(character="card"))
    assert scene.load_character("B")
    assert set(overlay.scope["resolved_entry_uids"]) == {"world", "a", "b"}
    assert scene.unload_character("A")
    assert set(overlay.scope["resolved_entry_uids"]) == {"world", "b"}
    scene._restoring_scope = True
    scene.load_character("A")
    assert set(overlay.scope["resolved_entry_uids"]) == {"world", "b"}


def test_failed_disk_save_keeps_original_file_and_cache(tmp_path, monkeypatch):
    manager = WorldBookManager(tmp_path)
    original = book_fixture()
    manager.save(original)
    before = manager._path(original.id).read_bytes()
    edited = copy.deepcopy(original)
    edited.name = "not saved"
    def fail_replace(*args, **kwargs): raise OSError("disk unavailable")
    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError): manager.save(edited)
    assert manager.load(original.id).name == original.name
    assert manager._path(original.id).read_bytes() == before
    assert not list(tmp_path.glob(".worldbook-*.tmp"))


def test_both_prompt_consumers_filter_and_keep_stable_dynamic_layers():
    from SceneManager import SceneManager
    from CharacterAgent import CharacterAgent
    book = book_fixture()
    book.entries[1].always_active = False
    book.entries[1].trigger_keys = ["trigger"]
    overlay = Overlay(book.resolve_import_scope(["A"]))
    scene = SceneManager(None, None)
    scene._overlay = overlay
    before, after = scene._build_worldbook_parts(book, "", "trigger", "博士")
    assert "content-world" in before and "content-a" in after
    assert "content-b" not in before + after
    agent = object.__new__(CharacterAgent)
    captured = []
    agent._session_context = SimpleNamespace(overlay=overlay, preloaded=False)
    agent.memory = SimpleNamespace(build_context=lambda _: "", add=lambda *_: None)
    agent.character, agent.character_name = "角色卡", "A"
    agent.registry, agent.metadata, agent._wiki_manager = None, {}, None
    agent.llm = SimpleNamespace(chat=lambda messages, **_: captured.append(messages) or {"content": "ok"})
    agent.chat("trigger", worldbook=book)
    prompt = captured[0][0]["content"]
    assert "content-world" in prompt and "content-a" in prompt and "content-b" not in prompt


@pytest.fixture
def api(tmp_path):
    from blueprints.worldbook import register
    manager = WorldBookManager(tmp_path)
    book = book_fixture()
    manager.save(book)
    app = Flask(__name__)
    app.config["TESTING"] = True
    register(app, {"worldbook": manager})
    return app.test_client(), manager, book


def test_api_preview_is_read_only_and_rejects_malformed_shapes(api):
    client, manager, book = api
    path = manager._path(book.id)
    original = path.read_bytes()
    response = client.post("/api/worldbook/book/scope-preview", json={"roster_character_ids": ["A"], "fixed_entry_uids": ["x"]})
    assert response.status_code == 200
    assert set(response.json["scope"]["resolved_entry_uids"]) == {"world", "a", "x"}
    assert path.read_bytes() == original and manager.load(book.id).import_config["fixed_entry_uids"] == []
    for body in ([], {"roster_character_ids": [{}]}, {"dependency_edges": [None]}, {"dependency_sources": [{"entry_uid": "a", "max_depth": True}]}):
        assert client.post("/api/worldbook/book/scope-preview", json=body).status_code == 400


def test_api_taxonomy_atomic_moves_and_revision_conflict(api):
    client, manager, book = api
    categories = [c for c in book.categories if c["id"] not in ("faction", "squad")]
    old = manager._path(book.id).read_bytes()
    assert client.put("/api/worldbook/book/taxonomy", json={"categories": categories}).status_code == 400
    assert manager._path(book.id).read_bytes() == old
    response = client.put("/api/worldbook/book/taxonomy", json={"categories": categories, "entry_moves": {"a": "unclassified"}})
    assert response.status_code == 200
    a = next(e for e in response.json["entries"] if e["uid"] == "a")
    assert a["content"] == "content-a" and a["character_id"] == "" and a["category_id"] == "unclassified"
    assert client.put("/api/worldbook/book/import-config", json={"expected_revision": 1, "fixed_entry_uids": ["x"]}).status_code == 409


def test_api_legacy_category_edit_does_not_activate_and_deletion_cleans_graph(api):
    client, manager, book = api
    book.scope_mode = "legacy"
    manager.save(book)
    response = client.put("/api/worldbook/book/taxonomy", json={"categories": book.categories})
    assert response.status_code == 200 and response.json["scope_mode"] == "legacy"
    assert client.put("/api/worldbook/book/import-config", json={"scope_mode": "selective", "fixed_entry_uids": ["x"], "dependency_sources": [{"entry_uid": "x", "max_depth": 2}]}).status_code == 200
    response = client.delete("/api/worldbook/book/entries/x")
    assert response.status_code == 200 and response.json["affected"] == {"dependency_edges": 2, "fixed_entries": 1, "dependency_sources": 1}
    current = manager.load(book.id)
    assert all("x" not in e.values() for e in current.dependency_edges)
    assert current.import_config["fixed_entry_uids"] == current.import_config["dependency_sources"] == []


def test_api_rejects_duplicate_uids_unknown_categories_and_keeps_zero_probability(api):
    client, _, _ = api
    assert client.post("/api/worldbook/book/entries", json={"uid": "a", "content": "duplicate"}).status_code == 400
    assert client.put("/api/worldbook/book/entries/a", json={"category_id": "missing"}).status_code == 400
    response = client.put("/api/worldbook/book/entries/a", json={"probability": 0, "depth": 0})
    assert response.status_code == 200
    assert response.json["entry"]["probability"] == response.json["entry"]["depth"] == 0
    assert response.json["entry"]["character_id"] == "A"


@pytest.fixture
def session_api(tmp_path, monkeypatch):
    import session_manager as module
    from blueprints.sessions import register
    book_manager = WorldBookManager(tmp_path)
    book_manager.save(book_fixture())
    cleaned, persisted = [], []

    class FakeSession:
        def __init__(self, sid, backend, **kwargs):
            self.id, self.name, self.mode = sid, kwargs["name"], kwargs["mode"]
            self.overlay = Overlay()
            self.player_identity = kwargs["player_identity"]
            self.characters = []
            def load(name):
                if name not in ("A", "B"): return False
                if name not in self.characters: self.characters.append(name)
                return True
            self.scene_manager = SimpleNamespace(load_character=load, get_scene_characters=lambda: self.characters)
        def to_dict(self):
            return {"id": self.id, "characters": self.characters, "worldbook_scope": self.overlay.get_worldbook_scope()}

    monkeypatch.setattr(module, "Session", FakeSession)
    monkeypatch.setattr(module.SessionOverlay, "delete_session_overlays", lambda sid, mode: cleaned.append(sid))
    manager = object.__new__(module.SessionManager)
    manager._lock, manager._sessions, manager._next_id = threading.Lock(), {}, 0
    manager._llm_backend = manager._wiki_manager = None
    manager._worldbook_manager = book_manager
    manager._save_session_meta = lambda session: persisted.append(session.id)
    app = Flask(__name__)
    app.config["TESTING"] = True
    register(app, {"worldbook": book_manager, "session": manager})
    return app.test_client(), manager, book_manager, cleaned, persisted


def test_creation_publishes_only_after_scope_and_roster_are_ready(session_api):
    client, manager, _, cleaned, persisted = session_api
    response = client.post("/api/sessions", json={"worldbook_id": "book", "roster_character_ids": ["A"]})
    assert response.status_code == 201 and response.json["characters"] == ["A"]
    assert set(response.json["worldbook_scope"]["resolved_entry_uids"]) == {"world", "a"}
    assert len(manager._sessions) == len(persisted) == 1 and not cleaned
    def initialize(session):
        assert session.id not in manager._sessions and session.id not in persisted
    manager.create_session(initializer=initialize)


def test_failed_creation_never_leaves_partial_session(session_api):
    client, manager, _, cleaned, persisted = session_api
    assert client.post("/api/sessions", json={"worldbook_id": "missing"}).status_code == 404
    assert not manager._sessions and not cleaned
    assert client.post("/api/sessions", json={"worldbook_id": "book", "roster_character_ids": ["A", "missing"]}).status_code == 400
    assert not manager._sessions and not persisted and len(cleaned) == 1


def test_new_explicit_unbound_and_legacy_client_default(session_api):
    client, _, books, _, _ = session_api
    books.set_default_book_id("book")
    response = client.post("/api/sessions", json={"worldbook_id": "", "roster_character_ids": ["A"]})
    assert response.status_code == 201 and response.json["worldbook_scope"]["book_id"] is None
    response = client.post("/api/sessions", json={"roster_character_ids": ["A"]})
    assert response.status_code == 201 and response.json["worldbook_scope"]["book_id"] == "book"
