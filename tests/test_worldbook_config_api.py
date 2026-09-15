"""统一配置写入、v3 预览、AI 构建任务与创建会话的原子性/一致性。

stub LLM 只替代模型层；接口、锁、CAS、任务状态机、校验都是真实代码。
"""
import copy
import json
import sys
import time
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from world_book import DEFAULT_CATEGORIES, WorldBook, WorldBookEntry, WorldBookManager
from worldbook_builder import AnalysisCache, DependencyJobStore
from worldbook_scope import (
    ACTIVATION_ALWAYS, ACTIVATION_ROSTER_ANY, EXPANSION_REQUIRES_CLOSURE,
)


def entry(uid, content=None, **kwargs):
    return WorldBookEntry(uid, content=content or f"content-{uid}",
                          always_active=True, **kwargs)


def book_fixture():
    # 正文里带明确引用（a 提到 tech 的名称），否则候选对为空、判定阶段不会被触发。
    return WorldBook("book", "测试书", [
        entry("world", "泰拉世界的基础设定，源石与天灾。", name="世界设定",
              category_id="worldview"),
        entry("a", "角色A：罗德岛干员。他使用源石技艺。", name="角色A",
              category_id="characters", character_id="A"),
        entry("b", "角色B：与角色A同属罗德岛。", name="角色B",
              category_id="characters", character_id="B"),
        entry("tech", "源石技艺的定义与规则。", name="源石技艺", category_id="other"),
    ], categories=copy.deepcopy(DEFAULT_CATEGORIES))


class StubLLM:
    """确定性 stub：只替代模型，不替代被测逻辑。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        prompt = messages[-1]["content"]
        if "分析下面这批" in prompt:
            uids = [line.split('uid="')[1].split('"')[0]
                    for line in prompt.splitlines() if line.startswith("<entry uid=")]
            return {"type": "text", "content": json.dumps({"cards": [
                {"uid": uid, "summary": "", "entities": [], "defined_concepts": [],
                 "unexplained_concepts": [], "candidate_characters": [], "evidence": []}
                for uid in uids]}, ensure_ascii=False)}
        if "判断下列" in prompt:
            return {"type": "text", "content": json.dumps({"judgments": [
                {"from_uid": "a", "to_uid": "tech", "relation": "requires",
                 "confidence": 0.9, "evidence": "他使用源石技艺"}]}, ensure_ascii=False)}
        raise AssertionError("未预期的请求")


class Backend:
    def __init__(self, llm=None, model="stub"):
        self._llm, self._model = llm, model

    def get_llm(self):
        return self._llm, self._model


@pytest.fixture
def api(tmp_path, monkeypatch):
    import blueprints.worldbook as module
    from blueprints.worldbook import register
    manager = WorldBookManager(tmp_path)
    manager.save(book_fixture())
    # 任务与缓存必须落在 tmp，绝不能污染仓库目录
    monkeypatch.setattr(module, "_JOB_STORE", DependencyJobStore(tmp_path / "jobs"))
    monkeypatch.setattr(module, "_ANALYSIS_CACHE", AnalysisCache(tmp_path / "analysis"))
    app = Flask(__name__)
    app.config["TESTING"] = True
    managers = {"worldbook": manager, "llm_backend": Backend(StubLLM())}
    register(app, managers)
    return app.test_client(), manager, managers


def wait_for(client, book_id, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/worldbook/{book_id}/dependency-proposals/{job_id}").json["job"]
        if payload["stage"] in ("done", "failed", "cancelled"):
            return payload
        time.sleep(0.02)
    raise AssertionError("任务未在超时内结束")


# ── 统一配置写入 ──

def test_put_configuration_applies_v3_rules_atomically(api):
    client, manager, _ = api
    body = {
        "expected_revision": 1,
        "roots": [
            {"entry_uid": "world", "activation": ACTIVATION_ALWAYS,
             "expansion": EXPANSION_REQUIRES_CLOSURE},
            {"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
             "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]},
        ],
        "requires_edges": [{"from_uid": "a", "to_uid": "tech"}],
        "related_edges": [{"from_uid": "b", "to_uid": "a"}],
    }
    response = client.put("/api/worldbook/book/configuration", json=body)
    assert response.status_code == 200
    assert response.json["policy_revision"] == 2
    assert response.json["applied"]["roots"] == 2
    stored = manager.load("book")
    assert stored.schema_version == 3 and stored.v3_enabled
    assert stored.related_edges == [{"from_uid": "b", "to_uid": "a"}]
    # v2 字段与 v3 起点保持同步，旧消费者仍可读
    assert stored.import_config["revision"] == 2
    assert stored.policy_revisions and stored.policy_revisions[-1]["revision"] == 2


def test_put_configuration_conflict_returns_409_and_keeps_draft(api):
    client, manager, _ = api
    before = manager._path("book").read_bytes()
    response = client.put("/api/worldbook/book/configuration",
                          json={"expected_revision": 99, "roots": []})
    assert response.status_code == 409
    assert manager._path("book").read_bytes() == before


def test_put_configuration_rejects_invalid_and_writes_nothing(api):
    client, manager, _ = api
    before = manager._path("book").read_bytes()
    for body in (
        {"roots": [{"entry_uid": "missing", "activation": ACTIVATION_ALWAYS}]},
        {"roots": [{"entry_uid": "a", "activation": "sometimes"}]},
        {"roots": [{"entry_uid": "a", "activation": ACTIVATION_ALWAYS}],
         "requires_edges": [{"from_uid": "a", "to_uid": "a"}]},
        {"roots": [{"entry_uid": "a", "activation": ACTIVATION_ALWAYS}],
         "requires_edges": [{"from_uid": "a", "to_uid": "b"}],
         "related_edges": [{"from_uid": "a", "to_uid": "b"}]},
        {"entry_moves": {"missing": "other"}},
        {"scope_mode": "nonsense"},
    ):
        assert client.put("/api/worldbook/book/configuration", json=body).status_code == 400, body
    assert manager._path("book").read_bytes() == before


def test_put_configuration_applies_ai_proposal_in_one_write(api):
    client, manager, _ = api
    body = {
        "expected_revision": 1,
        "proposal": {"accepted": [{"from_uid": "a", "to_uid": "tech",
                                   "relation": "requires"}]},
    }
    response = client.put("/api/worldbook/book/configuration", json=body)
    assert response.status_code == 200
    stored = manager.load("book")
    assert {"from_uid": "a", "to_uid": "tech"} in stored.dependency_edges
    # 角色条目成为 roster 起点，而不是全局源
    roots = {r["entry_uid"]: r for r in stored.dependency_rules["roots"]}
    assert roots["a"]["activation"] == ACTIVATION_ROSTER_ANY
    assert roots["a"]["character_ids"] == ["A"]


def test_scope_preview_returns_v3_explanations_and_is_read_only(api):
    client, manager, _ = api
    client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1,
        "roots": [{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                   "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]}],
        "requires_edges": [{"from_uid": "a", "to_uid": "tech"}],
    })
    before = manager._path("book").read_bytes()
    response = client.post("/api/worldbook/book/scope-preview",
                           json={"roster_character_ids": ["A"]})
    assert response.status_code == 200
    body = response.json
    assert set(body["scope"]["resolved_entry_uids"]) == {"a", "tech"}
    assert body["active_roots"][0]["entry_uid"] == "a"
    assert body["selection_reasons"]["tech"] == ["requires"]
    assert body["display_tree"] and body["display_tree"][0]["uid"] == "a"
    assert body["draft_hash"] and body["policy_revision"] == 2
    assert body["content_revision"] and body["resolver_version"] == 3
    assert manager._path("book").read_bytes() == before


def test_scope_preview_reports_single_character_and_manual_additions(api):
    client, _, _ = api
    client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1,
        "roots": [{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                   "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]},
                  {"entry_uid": "b", "activation": ACTIVATION_ROSTER_ANY,
                   "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["B"]}],
    })
    single = client.post("/api/worldbook/book/scope-preview",
                         json={"roster_character_ids": ["A"]}).json
    assert set(single["scope"]["resolved_entry_uids"]) == {"a"}
    manual = client.post("/api/worldbook/book/scope-preview",
                         json={"roster_character_ids": ["A"], "manual_entry_uids": ["tech"]}).json
    assert set(manual["scope"]["resolved_entry_uids"]) == {"a", "tech"}
    assert manual["selection_reasons"]["tech"] == ["manual"]


def test_scope_preview_draft_hash_is_stable_and_roster_sensitive(api):
    client, _, _ = api
    body = {"roster_character_ids": ["A"], "fixed_entry_uids": ["tech"]}
    first = client.post("/api/worldbook/book/scope-preview", json=body).json["draft_hash"]
    again = client.post("/api/worldbook/book/scope-preview", json=body).json["draft_hash"]
    other = client.post("/api/worldbook/book/scope-preview",
                        json={**body, "roster_character_ids": ["B"]}).json["draft_hash"]
    assert first == again and first != other


# ── AI 构建任务 ──

def test_proposal_without_llm_returns_503_for_settings_handoff(api):
    client, _, managers = api
    managers["llm_backend"] = Backend(None)
    response = client.post("/api/worldbook/book/dependency-proposals", json={})
    assert response.status_code == 503
    assert "设置" in response.json["error"]


def test_proposal_job_runs_polls_and_paginates(api):
    client, _, _ = api
    created = client.post("/api/worldbook/book/dependency-proposals", json={})
    assert created.status_code == 202
    job_id = created.json["job"]["job_id"]
    final = wait_for(client, "book", job_id)
    assert final["stage"] == "done" and final["error"] is None
    assert final["result"]["stats"]["requires"] == 1
    assert final["result"]["records_total"] == 1
    assert final["stale"] is False
    paged = client.get(
        f"/api/worldbook/book/dependency-proposals/{job_id}?offset=1&limit=1").json["job"]
    assert paged["result"]["records"] == [] and paged["result"]["records_total"] == 1
    assert client.get("/api/worldbook/book/dependency-proposals").json["jobs"]


def test_proposal_job_can_be_cancelled_and_retried(api):
    client, _, _ = api
    job_id = client.post("/api/worldbook/book/dependency-proposals", json={}).json["job"]["job_id"]
    assert client.post(f"/api/worldbook/book/dependency-proposals/{job_id}/cancel").status_code == 200
    cancelled = client.get(f"/api/worldbook/book/dependency-proposals/{job_id}").json["job"]
    assert cancelled["cancelled"] is True
    assert cancelled["stage"] in ("cancelled", "done")
    # 没有失败批次时重试给出明确拒绝，而不是假装成功
    retry = client.post(f"/api/worldbook/book/dependency-proposals/{job_id}/retry")
    assert retry.status_code == 400


def test_proposal_result_is_flagged_stale_after_book_changes(api):
    """任务绑定输入快照 hash；书变了旧结果不得被当成当前结果。"""
    client, manager, _ = api
    job_id = client.post("/api/worldbook/book/dependency-proposals", json={}).json["job"]["job_id"]
    wait_for(client, "book", job_id)
    assert client.get(f"/api/worldbook/book/dependency-proposals/{job_id}").json["job"]["stale"] is False
    stored = manager.load("book")
    stored.entries[0].content = "彻底不同的正文"
    manager.save(stored)
    assert client.get(f"/api/worldbook/book/dependency-proposals/{job_id}").json["job"]["stale"] is True


def test_unknown_job_and_wrong_book_return_404(api):
    client, _, _ = api
    assert client.get("/api/worldbook/book/dependency-proposals/nope").status_code == 404
    assert client.post("/api/worldbook/book/dependency-proposals/nope/cancel").status_code == 404
    assert client.post("/api/worldbook/book/dependency-proposals/nope/retry").status_code == 404


# ── 创建会话：零 LLM 调用 + 预览/创建一致 ──

@pytest.fixture
def session_api(tmp_path, monkeypatch):
    import session_manager as module
    from blueprints.sessions import register as register_sessions
    from blueprints.worldbook import register as register_worldbook
    book_manager = WorldBookManager(tmp_path)
    book_manager.save(book_fixture())
    llm = StubLLM()

    class FakeSession:
        def __init__(self, sid, backend, **kwargs):
            self.id, self.name = sid, kwargs["name"]
            self.mode = kwargs.get("mode", "free")
            self.overlay = type("O", (), {
                "_scope": None,
                "get_worldbook_scope": lambda s: copy.deepcopy(s._scope),
                "set_worldbook_scope": lambda s, v: setattr(s, "_scope", copy.deepcopy(v)),
                "get_worldbook_id": lambda s: None,
                "set_worldbook_id": lambda s, v: None,
            })()
            self.characters = []
            def load(name):
                if name not in ("A", "B"):
                    return False
                if name not in self.characters:
                    self.characters.append(name)
                return True
            self.scene_manager = type("S", (), {
                "load_character": staticmethod(load),
                "get_scene_characters": lambda s: self.characters,
            })()

        def to_dict(self):
            return {"id": self.id, "characters": self.characters,
                    "worldbook_scope": self.overlay.get_worldbook_scope()}

    monkeypatch.setattr(module, "Session", FakeSession)
    monkeypatch.setattr(module.SessionOverlay, "delete_session_overlays", lambda *a: None)
    import threading as _threading
    manager = object.__new__(module.SessionManager)
    manager._lock, manager._sessions, manager._next_id = _threading.Lock(), {}, 0
    manager._llm_backend = manager._wiki_manager = None
    manager._worldbook_manager = book_manager
    manager._save_session_meta = lambda session: None
    app = Flask(__name__)
    app.config["TESTING"] = True
    managers = {"worldbook": book_manager, "session": manager,
                "llm_backend": Backend(llm)}
    # 两个 blueprint 都要注册：会话创建依赖 worldbook 的 /configuration 写入 v3 规则
    register_worldbook(app, managers)
    register_sessions(app, managers)
    return app.test_client(), manager, book_manager, llm


def test_session_creation_uses_v3_snapshot_and_calls_no_llm(session_api):
    client, manager, books, llm = session_api
    client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1,
        "roots": [{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                   "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]}],
        "requires_edges": [{"from_uid": "a", "to_uid": "tech"}],
    })
    calls_before = llm.calls
    response = client.post("/api/sessions",
                           json={"worldbook_id": "book", "roster_character_ids": ["A"]})
    assert response.status_code == 201
    scope = response.json["worldbook_scope"]
    assert set(scope["resolved_entry_uids"]) == {"a", "tech"}
    assert scope["resolver_version"] == 3
    assert scope["rules"] and scope["requires_edges"]
    assert scope["roster_character_ids"] == ["A"]
    assert scope["active_roots"][0]["entry_uid"] == "a"
    assert scope["selection_reasons"]["tech"] == ["requires"]
    assert scope["display_tree"]
    assert llm.calls == calls_before          # 创建会话不调用 LLM


def test_session_creation_snapshot_restores_bound_rules_after_book_edit(session_api):
    """会话绑定完整规则版本：书后来改了，会话仍能恢复它创建时的规则。"""
    client, _, books, _ = session_api
    client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1,
        "roots": [{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                   "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]}],
        "requires_edges": [{"from_uid": "a", "to_uid": "tech"}],
    })
    created = client.post("/api/sessions",
                          json={"worldbook_id": "book", "roster_character_ids": ["A"]})
    bound = created.json["worldbook_scope"]
    assert set(bound["resolved_entry_uids"]) == {"a", "tech"}

    # 书改成不再依赖 tech
    client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 2, "requires_edges": []})
    stored = books.load("book")
    assert "tech" not in stored.resolve_v3_import_scope(["A"])["resolved_entry_uids"]
    # 用绑定版本重算，仍得到创建时的结果
    restored = stored.resolve_v3_import_scope(["A"], revision=bound["policy_revision"])
    assert set(restored["resolved_entry_uids"]) == {"a", "tech"}


def test_session_creation_failure_leaves_no_partial_session(session_api):
    client, manager, _, _ = session_api
    assert client.post("/api/sessions",
                       json={"worldbook_id": "book", "roster_character_ids": ["A", "missing"]}
                       ).status_code == 400
    assert not manager._sessions


def test_ai_proposal_merges_into_manual_draft_instead_of_replacing_it(api):
    """应用 AI 结果不能把人工配好的起点与依赖冲掉。"""
    client, manager, _ = api
    client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1,
        "roots": [{"entry_uid": "tech", "activation": ACTIVATION_ALWAYS,
                   "expansion": EXPANSION_REQUIRES_CLOSURE}],
        "related_edges": [{"from_uid": "world", "to_uid": "tech"}],
    })
    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 2,
        # 草稿里的起点与边（人工）
        "roots": [{"entry_uid": "tech", "activation": ACTIVATION_ALWAYS,
                   "expansion": EXPANSION_REQUIRES_CLOSURE}],
        "requires_edges": [],
        "related_edges": [{"from_uid": "world", "to_uid": "tech"}],
        # 同时应用 AI 建议
        "proposal": {"accepted": [{"from_uid": "a", "to_uid": "tech",
                                   "relation": "requires"}]},
    })
    assert response.status_code == 200, response.json
    stored = manager.load("book")
    roots = {r["entry_uid"]: r for r in stored.dependency_rules["roots"]}
    # 人工起点保留
    assert roots["tech"]["activation"] == ACTIVATION_ALWAYS
    # AI 派生起点并入（角色条目 → roster 起点），而不是替换整份配置
    assert roots["a"]["activation"] == ACTIVATION_ROSTER_ANY
    assert {"from_uid": "a", "to_uid": "tech"} in stored.dependency_edges
    assert {"from_uid": "world", "to_uid": "tech"} in stored.related_edges
    # 同一条边不会因为重复提交而出现两次
    assert len(stored.dependency_edges) == len(
        {(e["from_uid"], e["to_uid"]) for e in stored.dependency_edges})


def test_full_scope_preview_and_session_creation_are_explicit_and_consistent(session_api):
    """显式全量兼容：预览与创建一致，只影响本会话，不改这本书的规则。"""
    client, _, books, _ = session_api
    client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1,
        "roots": [{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                   "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]}],
    })
    before = copy.deepcopy(books.load("book").dependency_rules)

    preview = client.post("/api/worldbook/book/scope-preview",
                          json={"roster_character_ids": ["A"], "full_scope": True})
    assert preview.status_code == 200
    body = preview.json
    assert body["full_scope"] is True
    # 全量：所有启用且有正文的条目都在候选里
    assert set(body["scope"]["resolved_entry_uids"]) == {"world", "a", "b", "tech"}
    assert body["saved_estimated_tokens"] == 0

    created = client.post("/api/sessions", json={
        "worldbook_id": "book", "roster_character_ids": ["A"],
        "full_scope": True, "expected_draft_hash": body["draft_hash"]})
    assert created.status_code == 201, created.json
    scope = created.json["worldbook_scope"]
    assert scope["full_scope"] is True
    assert set(scope["resolved_entry_uids"]) == {"world", "a", "b", "tech"}
    # 规则没被改动
    assert books.load("book").dependency_rules == before


def test_full_scope_hash_differs_and_stale_preview_is_rejected(session_api):
    """指纹区分是否全量兼容；预览过期时创建直接报错，不静默换范围。"""
    client, manager, books, _ = session_api
    book = books.load("book")
    book.dependency_rules = {"roots": [{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                                        "expansion": EXPANSION_REQUIRES_CLOSURE,
                                        "character_ids": ["A"]}]}
    book.schema_version = 3
    books.save(book)

    partial = client.post("/api/worldbook/book/scope-preview",
                          json={"roster_character_ids": ["A"]}).json
    full = client.post("/api/worldbook/book/scope-preview",
                       json={"roster_character_ids": ["A"], "full_scope": True}).json
    assert partial["draft_hash"] != full["draft_hash"]

    # 用「全量」的指纹去创建一个「非全量」的会话 → 必须被拒绝
    rejected = client.post("/api/sessions", json={
        "worldbook_id": "book", "roster_character_ids": ["A"],
        "expected_draft_hash": full["draft_hash"]})
    assert rejected.status_code == 400
    assert "预览已过期" in rejected.json["error"]
    assert not manager._sessions


def test_manual_append_is_session_scoped_and_cancellable(session_api):
    """手动追加只作用于本会话：书规则不变，取消追加后新会话不再包含它。"""
    client, _, books, _ = session_api
    client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1,
        "roots": [{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                   "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]}],
    })
    before = copy.deepcopy(books.load("book").dependency_rules)

    preview = client.post("/api/worldbook/book/scope-preview",
                          json={"roster_character_ids": ["A"],
                                "manual_entry_uids": ["world"]}).json
    assert "world" in preview["scope"]["resolved_entry_uids"]
    assert preview["scope"]["selection_reasons"]["world"] == ["manual"]

    created = client.post("/api/sessions", json={
        "worldbook_id": "book", "roster_character_ids": ["A"],
        "manual_entry_uids": ["world"], "expected_draft_hash": preview["draft_hash"]})
    assert created.status_code == 201, created.json
    assert "world" in created.json["worldbook_scope"]["resolved_entry_uids"]
    assert created.json["worldbook_scope"]["manual_entry_uids"] == ["world"]
    assert books.load("book").dependency_rules == before      # 书规则没被写回

    # 取消追加（不带 manual）→ 新会话不再包含，且没有破坏书上的配置
    again = client.post("/api/sessions", json={
        "worldbook_id": "book", "roster_character_ids": ["A"]})
    assert again.status_code == 201
    assert "world" not in again.json["worldbook_scope"]["resolved_entry_uids"]
    assert books.load("book").dependency_rules == before
