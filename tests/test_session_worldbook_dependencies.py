import copy
import json
import sys
import threading
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blueprints.sessions import register
from session_worldbook_dependencies import (
    apply_inheritance_update, change_relation, effective_graph, ensure_editable_scope,
    preview_inheritance_update, restore_inheritance,
)
from world_book import DEFAULT_CATEGORIES, WorldBook, WorldBookEntry, WorldBookManager
from worldbook_builder import AnalysisCache, DependencyJobStore, run_scoped_build


def make_book():
    return WorldBook("book", "会话测试书", [
        WorldBookEntry("a", name="角色A", content="角色A使用源石技艺。",
                       category_id="characters", character_id="A", always_active=True),
        WorldBookEntry("b", name="角色B", content="角色B的记录。",
                       category_id="characters", character_id="B", always_active=True),
        WorldBookEntry("tech", name="源石技艺", content="源石技艺的定义。",
                       category_id="other", always_active=True),
    ], categories=copy.deepcopy(DEFAULT_CATEGORIES))


def v3_book():
    book = make_book().adopt_v2_as_v3()
    for root in book.dependency_rules["roots"]:
        if root["entry_uid"] == "a":
            root["expansion"] = "requires_closure"
    book.dependency_edges = [{"from_uid": "a", "to_uid": "tech"}]
    book.import_config["revision"] = 3
    book.policy_revisions = []
    book.record_policy_revision()
    return book


def test_local_override_delete_restore_and_refresh_are_stable():
    book = v3_book()
    scope = book.session_scope_snapshot(["A"], ["b"])
    changed = change_relation(scope, "a", "tech", None, 1)
    refreshed = book.refresh_session_scope(changed, ["A"])
    assert ("a", "tech") not in {(e["from_uid"], e["to_uid"])
                                   for e in effective_graph(refreshed)["requires_edges"]}
    assert refreshed["manual_entry_uids"] == ["b"]
    assert refreshed["scope_revision"] == 2
    restored = restore_inheritance(refreshed, 2, "a", "tech")
    restored = book.refresh_session_scope(restored, ["A"])
    assert {"from_uid": "a", "to_uid": "tech"} in restored["requires_edges"]


def test_pair_suppression_survives_global_relation_change():
    book = v3_book()
    scope = change_relation(book.session_scope_snapshot(["A"]), "a", "tech", None, 1)
    book.dependency_edges = []
    book.related_edges = [{"from_uid": "a", "to_uid": "tech"}]
    preview = preview_inheritance_update(scope, book)
    updated = apply_inheritance_update(scope, preview, 2, preview["preview_hash"])
    graph = effective_graph(updated)
    assert graph["requires_edges"] == [] and graph["related_edges"] == []


def test_global_update_keeps_local_relation_and_reports_conflict():
    book = v3_book()
    scope = change_relation(book.session_scope_snapshot(["A"]), "a", "tech", "related", 1)
    book.dependency_edges = [{"from_uid": "a", "to_uid": "tech"}]
    book.related_edges = []
    book.import_config["revision"] = 4
    preview = preview_inheritance_update(scope, book)
    updated = apply_inheritance_update(scope, preview, 2, preview["preview_hash"])
    assert preview["conflicts"][0]["resolution"] == "local_wins"
    assert effective_graph(updated)["related_edges"] == [{"from_uid": "a", "to_uid": "tech"}]


def test_schema2_session_upgrade_is_local_and_range_equivalent():
    book = make_book()
    old = book.resolve_import_scope(["A"])
    upgraded = ensure_editable_scope(old, book, ["A"])
    assert upgraded["schema_version"] == 3
    assert upgraded["session_migrated_from"] == 2
    assert set(upgraded["resolved_entry_uids"]) == set(old["resolved_entry_uids"])
    assert book.schema_version == 2 and book.dependency_rules is None


class Overlay:
    def __init__(self):
        self.scope = None
        self.book_id = None
        self.lock = threading.RLock()
    def get_worldbook_scope(self): return copy.deepcopy(self.scope)
    def set_worldbook_scope(self, value): self.scope = copy.deepcopy(value)
    def update_worldbook_scope(self, updater):
        with self.lock:
            self.scope = copy.deepcopy(updater(copy.deepcopy(self.scope)))
            return copy.deepcopy(self.scope)
    def get_worldbook_id(self): return self.book_id
    def set_worldbook_id(self, value): self.book_id = value


class FakeSession:
    def __init__(self, sid, backend, **kwargs):
        self.id, self.name, self.mode = sid, kwargs["name"], kwargs.get("mode", "free")
        self.overlay, self.characters = Overlay(), []
        self.scene_manager = type("Scene", (), {
            "load_character": lambda _s, name: self.characters.append(name) is None,
            "get_scene_characters": lambda _s: list(self.characters),
        })()
    def to_dict(self):
        return {"id": self.id, "worldbook_scope": self.overlay.get_worldbook_scope(),
                "characters": self.characters}


class StubLLM:
    def __init__(self): self.calls = []
    def chat(self, messages, **_kwargs):
        self.calls.append(messages)
        prompt = messages[-1]["content"]
        if "分析下面这批" in prompt:
            lines = [line for line in prompt.splitlines() if line.startswith("<entry uid=")]
            cards = [{"uid": line.split('uid="')[1].split('"')[0],
                      "chunk_id": line.split('chunk_id="')[1].split('"')[0],
                      "summary": "", "entities": [], "defined_concepts": [],
                      "unexplained_concepts": [], "candidate_characters": [],
                      "evidence": [], "needs_more_context": False} for line in lines]
            return {"type": "text", "content": json.dumps({"cards": cards})}
        pairs = []
        for line in prompt.splitlines():
            if line.startswith("<pair from="):
                parts = dict(item.split("=", 1) for item in line.strip("<>").split() if "=" in item)
                a, b = parts["from"].strip('"'), parts["to"].strip('"')
                pairs.append({"from_uid": a, "to_uid": b, "relation": "requires",
                              "confidence": .9, "evidence": "源石技艺"})
        return {"type": "text", "content": json.dumps({"judgments": pairs}, ensure_ascii=False)}


class Backend:
    def __init__(self, llm): self.llm = llm
    def get_llm(self): return self.llm, "stub"


@pytest.fixture
def session_api(tmp_path, monkeypatch):
    import blueprints.sessions as route_module
    import session_manager as manager_module
    books = WorldBookManager(tmp_path / "books")
    books.save(make_book())
    llm = StubLLM()
    monkeypatch.setattr(manager_module, "Session", FakeSession)
    monkeypatch.setattr(manager_module.SessionOverlay, "delete_session_overlays", lambda *_: None)
    manager = object.__new__(manager_module.SessionManager)
    manager._lock, manager._sessions, manager._next_id = threading.Lock(), {}, 0
    manager._llm_backend = manager._wiki_manager = None
    manager._worldbook_manager = books
    manager._save_session_meta = lambda _session: None
    monkeypatch.setattr(route_module, "_SESSION_JOB_STORE", DependencyJobStore(tmp_path / "jobs"))
    monkeypatch.setattr(route_module, "_SESSION_ANALYSIS_CACHE", AnalysisCache(tmp_path / "cache"))
    app = Flask(__name__); app.config["TESTING"] = True
    register(app, {"session": manager, "worldbook": books, "llm_backend": Backend(llm)})
    return app.test_client(), manager, books, llm


def test_api_schema2_snapshot_override_and_cross_session_isolation(session_api):
    client, manager, books, llm = session_api
    first = client.post("/api/sessions", json={"worldbook_id": "book", "roster_character_ids": ["A"]})
    second = client.post("/api/sessions", json={"worldbook_id": "book", "roster_character_ids": ["A"]})
    assert first.status_code == second.status_code == 201 and llm.calls == []
    one, two = first.json["id"], second.json["id"]
    deps = client.get(f"/api/sessions/{one}/worldbook-dependencies").json
    changed = client.patch(f"/api/sessions/{one}/worldbook-dependencies", json={
        "from_uid": "a", "to_uid": "tech", "relation": "requires",
        "enable_source_expansion": True,
        "expected_scope_revision": deps["scope_revision"]})
    assert changed.status_code == 200, changed.json
    assert "tech" in changed.json["resolved_entry_uids"]
    other = client.get(f"/api/sessions/{two}/worldbook-dependencies").json
    assert other["local_overrides"]["requires_edges"] == []
    assert books.load("book").dependency_edges == []
    preview = client.post(
        f"/api/sessions/{one}/worldbook-dependencies/inheritance-preview")
    assert preview.status_code == 200, preview.json


def test_api_job_becomes_stale_after_session_change(session_api):
    client, manager, _books, _llm = session_api
    created = client.post("/api/sessions", json={"worldbook_id": "book", "roster_character_ids": ["A"]}).json
    sid = created["id"]
    deps = client.get(f"/api/sessions/{sid}/worldbook-dependencies").json
    job = client.post(f"/api/sessions/{sid}/worldbook-dependency-jobs", json={"max_calls": 50})
    assert job.status_code == 202, job.json
    jid = job.json["job"]["job_id"]
    client.patch(f"/api/sessions/{sid}/worldbook-dependencies", json={
        "from_uid": "a", "to_uid": "b", "relation": "related",
        "expected_scope_revision": deps["scope_revision"]})
    payload = client.get(f"/api/sessions/{sid}/worldbook-dependency-jobs/{jid}").json["job"]
    assert payload["stale"] is True
    assert client.post(f"/api/sessions/{sid}/worldbook-dependency-jobs/{jid}/apply",
                       json={"accepted_pairs": []}).status_code == 409


def test_scoped_runner_expands_only_requires_frontier(tmp_path):
    book = make_book()
    next(e for e in book.entries if e.uid == "tech").content = "源石技艺由角色B记录。"
    llm = StubLLM()
    store = DependencyJobStore(tmp_path / "jobs")
    job = store.create(book.id, "input", "stub", reading_mode="adaptive")
    job.context = {}
    run_scoped_build(job, book, llm, model="stub",
                     cache=AnalysisCache(tmp_path / "cache"), max_calls=100,
                     source_uids=["a"])
    assert job.context["scoped_complete"] is True
    assert set(job.context["expanded_source_uids"]) == {"a", "tech", "b"}
    assert job.outcome == "success"


def test_scoped_runner_reuses_known_edge_with_zero_llm_calls(tmp_path):
    book, llm = make_book(), StubLLM()
    job = DependencyJobStore(tmp_path / "jobs").create(
        book.id, "input", "stub", reading_mode="adaptive")
    job.context = {}
    run_scoped_build(job, book, llm, model="stub",
                     cache=AnalysisCache(tmp_path / "cache"), max_calls=20,
                     source_uids=["a"], known_pairs=[("a", "tech")])
    assert llm.calls == []
    assert job.outcome == "success"
    assert job.context["scoped_complete"] is True
    assert job.workload["entries"] == 0
    assert job.workload["estimated_calls"] == 0


def test_scoped_runner_estimates_only_candidate_endpoints(tmp_path):
    book = make_book()
    book.entries.append(WorldBookEntry(
        "unrelated", name="无关条目", content="这段正文不引用任何其他条目。",
        category_id="other", always_active=True))
    llm = StubLLM()
    job = DependencyJobStore(tmp_path / "jobs").create(
        book.id, "input", "stub", reading_mode="adaptive")
    job.context = {}
    run_scoped_build(job, book, llm, model="stub",
                     cache=AnalysisCache(tmp_path / "cache"), max_calls=100,
                     source_uids=["a"])
    assert job.outcome == "success"
    assert job.workload["entries"] < len(book.entries)
    assert "unrelated" not in job.cards


def test_scoped_runner_follows_known_requires_from_new_frontier(tmp_path):
    book = WorldBook("chain", "链", [
        WorldBookEntry("s", name="起始条目", content="源石技艺：起始条目引用目标条目。", always_active=True),
        WorldBookEntry("t", name="目标条目", content="源石技艺：目标条目引用中转条目。", always_active=True),
        WorldBookEntry("u", name="中转条目", content="源石技艺：中转条目引用末端条目。", always_active=True),
        WorldBookEntry("v", name="末端条目", content="源石技艺：末端条目的定义。", always_active=True),
    ], categories=copy.deepcopy(DEFAULT_CATEGORIES))
    llm = StubLLM()
    job = DependencyJobStore(tmp_path / "jobs").create(
        book.id, "input", "stub", reading_mode="adaptive")
    job.context = {}
    run_scoped_build(job, book, llm, model="stub",
                     cache=AnalysisCache(tmp_path / "cache"), max_calls=100,
                     source_uids=["s"], known_pairs=[("t", "u")],
                     known_requires=[("t", "u")])
    assert job.outcome == "success"
    assert set(job.context["expanded_source_uids"]) == {"s", "t", "u", "v"}
    accepted = {(item["from_uid"], item["to_uid"])
                for item in job.result["accepted"]}
    assert ("s", "t") in accepted and ("u", "v") in accepted
    assert ("t", "u") not in accepted  # 继承边复用，没有重复判定


def test_cancelled_running_job_cannot_retry_concurrently(session_api):
    client, _manager, _books, _llm = session_api
    sid = client.post("/api/sessions", json={
        "worldbook_id": "book", "roster_character_ids": ["A"]}).json["id"]
    created = client.post(f"/api/sessions/{sid}/worldbook-dependency-jobs",
                          json={"max_calls": 50})
    jid = created.json["job"]["job_id"]
    client.post(f"/api/sessions/{sid}/worldbook-dependency-jobs/{jid}/cancel")
    retry = client.post(f"/api/sessions/{sid}/worldbook-dependency-jobs/{jid}/retry")
    # worker 若尚未退出，409 防止并发；已退出则可从取消点重新开始。
    assert retry.status_code in (202, 409)


def test_session_overlay_scope_survives_reload(tmp_path, monkeypatch):
    import session_overlay as overlay_module
    monkeypatch.setattr(overlay_module, "_SESSIONS_DIR", tmp_path / "sessions")
    first = overlay_module.SessionOverlay("session-1", "free")
    scope = v3_book().session_scope_snapshot(["A"])
    changed = change_relation(scope, "a", "tech", None, 1)
    first.set_worldbook_scope(changed)
    restored = overlay_module.SessionOverlay("session-1", "free").get_worldbook_scope()
    assert restored["scope_revision"] == 2
    assert restored["suppressed_edges"] == changed["suppressed_edges"]
    assert effective_graph(restored)["requires_edges"] == []


def test_budget_interruption_reloads_and_resumes_same_job(tmp_path):
    book, llm = make_book(), StubLLM()
    jobs_path = tmp_path / "jobs"
    store = DependencyJobStore(jobs_path)
    job = store.create(book.id, "input", "stub", reading_mode="adaptive")
    job.context = {}
    run_scoped_build(job, book, llm, model="stub",
                     cache=AnalysisCache(tmp_path / "cache"), max_calls=1,
                     source_uids=["a"])
    assert job.resumable and job.context["scoped_complete"] is False
    reloaded = DependencyJobStore(jobs_path).get(job.id)
    assert reloaded is not None and reloaded.resumable
    reloaded.cancelled = False
    run_scoped_build(reloaded, book, llm, model="stub",
                     cache=AnalysisCache(tmp_path / "cache"), max_calls=50,
                     source_uids=["a"])
    assert reloaded.outcome == "success"
    assert reloaded.context["scoped_complete"] is True


def test_running_done_job_rejects_apply_and_duplicate_create(session_api):
    import blueprints.sessions as route_module
    client, _manager, books, _llm = session_api
    sid = client.post("/api/sessions", json={
        "worldbook_id": "book", "roster_character_ids": ["A"]}).json["id"]
    scope = client.get(f"/api/sessions/{sid}/worldbook-dependencies").json
    job = route_module._SESSION_JOB_STORE.create("book", "input", "stub")
    job.context = {"session_id": sid, "book_id": "book",
                   "scope_revision": scope["scope_revision"]}
    job.stage, job.outcome, job.result, job.running = "done", "success", {"records": []}, True
    job.save()
    assert client.post(
        f"/api/sessions/{sid}/worldbook-dependency-jobs/{job.id}/apply",
        json={"accepted_pairs": []}).status_code == 409
    assert client.post(
        f"/api/sessions/{sid}/worldbook-dependency-jobs",
        json={"max_calls": 20}).status_code == 409
