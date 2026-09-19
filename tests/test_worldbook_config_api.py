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
from worldbook_builder import AnalysisCache, DependencyJobStore, content_hash
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
            entry_lines = [line for line in prompt.splitlines() if line.startswith("<entry uid=")]
            uids = [line.split('uid="')[1].split('"')[0] for line in entry_lines]
            chunk_ids = [line.split('chunk_id="')[1].split('"')[0] for line in entry_lines]
            return {"type": "text", "content": json.dumps({"cards": [
                {"uid": uid, "chunk_id": chunk_id, "summary": "", "entities": [], "defined_concepts": [],
                 "unexplained_concepts": [], "candidate_characters": [], "evidence": []}
                for uid, chunk_id in zip(uids, chunk_ids)]}, ensure_ascii=False)}
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


def adopt_v3(client, roots=None, **extra):
    """v2 → v3 显式迁移（等价保留旧来源），可选地再收窄起点。

    两步都是真实用户路径：先显式启用按需规则（不能丢内容），
    再按需要收窄。返回第二次保存的响应。
    """
    body = {"expected_revision": 1, "adopt_v3": True, "roots": [], "requires_edges": []}
    first = client.put("/api/worldbook/book/configuration", json=body)
    assert first.status_code == 200, first.json
    if roots is None and not extra:
        return first
    revision = first.json["policy_revision"]
    payload = {"expected_revision": revision, "roots": roots if roots is not None else [], **extra}
    response = client.put("/api/worldbook/book/configuration", json=payload)
    assert response.status_code == 200, response.json
    return response


def run_job(client, book_id="book", body=None):
    """跑一次真实的 AI 构建任务并返回 job_id（AI 建议必须能被服务端复核）。"""
    created = client.post(f"/api/worldbook/{book_id}/dependency-proposals", json=body or {})
    assert created.status_code == 202, created.json
    job_id = created.json["job"]["job_id"]
    final = wait_for(client, book_id, job_id)
    assert final["stage"] == "done", final
    return job_id, final


# ── 统一配置写入 ──

def test_put_configuration_applies_v3_rules_atomically(api):
    client, manager, _ = api
    body = {
        "expected_revision": 1,
        "adopt_v3": True,
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
    assert response.status_code == 200, response.json
    assert response.json["policy_revision"] == 2
    stored = manager.load("book")
    assert stored.schema_version == 3 and stored.v3_enabled
    roots = {r["entry_uid"]: r for r in stored.dependency_rules["roots"]}
    # 显式迁移：客户端草稿优先，旧来源按等价映射补齐（角色 B 不会因为迁移被丢下）
    assert roots["world"]["expansion"] == EXPANSION_REQUIRES_CLOSURE
    assert roots["a"]["expansion"] == EXPANSION_REQUIRES_CLOSURE
    assert roots["b"]["activation"] == ACTIVATION_ROSTER_ANY
    assert stored.related_edges == [{"from_uid": "b", "to_uid": "a"}]
    # v2 字段与 v3 起点保持同步，旧消费者仍可读
    assert stored.import_config["revision"] == 2
    assert stored.policy_revisions and stored.policy_revisions[-1]["revision"] == 2


def test_v2_ordinary_save_never_changes_scope_and_never_enables_v3(api):
    """普通保存（改分类 / 改边）不得隐式切到 v3，更不得把候选清空。

    预装书就是这种形态：selective + fixed/sources 都为空，候选完全由
    世界观分类与角色关联决定。旧实现里任何一次保存都会发 roots，
    于是「保存一次」= 启用 v3 且起点为空 = 候选变空集。
    """
    client, manager, _ = api
    before = manager.load("book")
    scope_before = before.resolve_import_scope(["A"])
    assert set(scope_before["resolved_entry_uids"]) == {"world", "a"}

    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1,
        "categories": before.categories,
        "entry_moves": {"tech": "other"},
        "entry_updates": {},
        "scope_mode": "selective",
        # 前端统一草稿总会带上这三项：它们**不能**触发隐式迁移
        "roots": [],
        "requires_edges": [],
        "related_edges": [],
    })
    assert response.status_code == 200, response.json
    stored = manager.load("book")
    assert stored.dependency_rules is None, "普通保存不该隐式启用 v3"
    assert stored.schema_version == 2
    scope_after = stored.resolve_import_scope(["A"])
    assert set(scope_after["resolved_entry_uids"]) == {"world", "a"}, "普通保存改变了候选范围"


def test_legacy_book_save_keeps_full_scope_and_legacy_mode(api):
    """legacy 书（全量兼容）保存后仍然是全量：不能被隐式切成空候选。"""
    client, manager, _ = api
    book = manager.load("book")
    book.scope_mode = "legacy"
    book.import_config["fixed_entry_uids"] = []
    book.import_config["dependency_sources"] = []
    manager.save(book)
    before = set(manager.load("book").resolve_import_scope([])["resolved_entry_uids"])
    assert before == {"world", "a", "b", "tech"}

    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": manager.load("book").import_config["revision"],
        "scope_mode": "legacy", "roots": [], "requires_edges": [], "related_edges": [],
    })
    assert response.status_code == 200, response.json
    stored = manager.load("book")
    assert stored.dependency_rules is None and stored.scope_mode == "legacy"
    assert set(stored.resolve_import_scope([])["resolved_entry_uids"]) == before


def test_explicit_adoption_preserves_all_old_sources(api):
    """显式启用按需规则时，旧来源必须逐条等价保留（世界观 / 角色 / 固定 / 导入源）。"""
    client, manager, _ = api
    book = manager.load("book")
    book.import_config["fixed_entry_uids"] = ["tech"]
    book.import_config["dependency_sources"] = [{"entry_uid": "b", "max_depth": 1}]
    manager.save(book)
    revision = manager.load("book").import_config["revision"]
    before = set(manager.load("book").resolve_import_scope(["A"])["resolved_entry_uids"])

    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": revision, "adopt_v3": True, "roots": [],
    })
    assert response.status_code == 200, response.json
    stored = manager.load("book")
    assert stored.v3_enabled
    after = set(stored.resolve_v3_import_scope(["A"])["resolved_entry_uids"])
    assert before <= after, f"迁移后丢条目：{sorted(before - after)}"
    roots = {r["entry_uid"]: r for r in stored.dependency_rules["roots"]}
    assert roots["world"]["activation"] == ACTIVATION_ALWAYS          # 世界观分类
    assert roots["a"]["activation"] == ACTIVATION_ROSTER_ANY          # 角色关联
    assert roots["tech"]["activation"] == ACTIVATION_ALWAYS           # 固定导入
    assert roots["b"]["expansion"] == "legacy_depth"                  # 导入源保留深度


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
        {"adopt_v3": True, "roots": [{"entry_uid": "missing", "activation": ACTIVATION_ALWAYS}]},
        {"adopt_v3": True, "roots": [{"entry_uid": "a", "activation": "sometimes"}]},
        {"adopt_v3": True, "roots": [{"entry_uid": "a", "activation": ACTIVATION_ALWAYS}],
         "requires_edges": [{"from_uid": "a", "to_uid": "a"}]},
        {"adopt_v3": True, "roots": [{"entry_uid": "a", "activation": ACTIVATION_ALWAYS}],
         "requires_edges": [{"from_uid": "a", "to_uid": "b"}],
         "related_edges": [{"from_uid": "a", "to_uid": "b"}]},
        {"entry_moves": {"missing": "other"}},
        {"scope_mode": "nonsense"},
        # AI 建议缺少任务身份：不接受客户端自说自话的 accepted
        {"proposal": {"accepted": [{"from_uid": "a", "to_uid": "tech",
                                    "relation": "requires"}]}},
        {"proposal": {"job_id": "nope", "accepted_pairs": [["a", "tech"]]}},
    ):
        assert client.put("/api/worldbook/book/configuration", json=body).status_code == 400, body
    assert manager._path("book").read_bytes() == before


def test_put_configuration_applies_ai_proposal_in_one_write(api):
    """AI 建议必须能通过服务端复核（job 身份 + 正文哈希 + 证据），一次写入。"""
    client, manager, _ = api
    job_id, final = run_job(client)
    record = final["result"]["records"][0]
    assert record["from_uid"] == "a" and record["to_uid"] == "tech"

    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1,
        "adopt_v3": True,
        "proposal": {"job_id": job_id,
                     "accepted_pairs": [[record["from_uid"], record["to_uid"]]]},
    })
    assert response.status_code == 200, response.json
    stored = manager.load("book")
    assert {"from_uid": "a", "to_uid": "tech"} in stored.dependency_edges
    # 角色条目成为 roster 起点，而不是全局源
    roots = {r["entry_uid"]: r for r in stored.dependency_rules["roots"]}
    assert roots["a"]["activation"] == ACTIVATION_ROSTER_ANY
    assert roots["a"]["character_ids"] == ["A"]
    # 边的来源与证据被持久化，重载后仍查得到
    meta = stored.dependency_rules["edge_meta"]["a|tech"]
    assert meta["origin"] == "llm" and meta["evidence_hash"]


def test_stale_ai_proposal_is_refused_by_the_server(api):
    """正文变了 → 旧建议必须被服务端拒绝，不能靠前端自觉。"""
    client, manager, _ = api
    job_id, final = run_job(client)
    record = final["result"]["records"][0]
    stored = manager.load("book")
    for entry in stored.entries:
        if entry.uid == record["to_uid"]:
            entry.content = "源石技艺的正文被彻底改写了。"
    manager.save(stored)

    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": stored.import_config["revision"],
        "adopt_v3": True,
        "proposal": {"job_id": job_id,
                     "accepted_pairs": [[record["from_uid"], record["to_uid"]]]},
    })
    assert response.status_code == 400, response.json
    assert "过期" in response.json["error"] or "已变化" in response.json["error"]
    assert not manager.load("book").v3_enabled


def test_deleted_ai_edge_does_not_resurrect_after_save_and_reload(api):
    """应用 AI 边 → 删掉 → 保存 → 重载 → 再应用：删掉的边不能复活。"""
    client, manager, _ = api
    job_id, final = run_job(client)
    record = final["result"]["records"][0]
    pair = [record["from_uid"], record["to_uid"]]
    applied = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1, "adopt_v3": True,
        "proposal": {"job_id": job_id, "accepted_pairs": [pair]}})
    assert applied.status_code == 200, applied.json
    revision = applied.json["policy_revision"]
    assert manager.load("book").dependency_edges

    # 人工删掉这条边（草稿里去掉 + 记为 rejected），再次带上同一条 AI 建议
    removed = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": revision, "roots": [], "requires_edges": [],
        "rejected": [{"from_uid": pair[0], "to_uid": pair[1]}],
        "proposal": {"job_id": job_id, "accepted_pairs": [pair]}})
    assert removed.status_code == 200, removed.json
    stored = manager.load("book")
    assert {"from_uid": pair[0], "to_uid": pair[1]} not in stored.dependency_edges
    # 重载后拒绝决定仍在
    reloaded = manager.load("book")
    assert {"from_uid": pair[0], "to_uid": pair[1]} in [
        {"from_uid": r["from_uid"], "to_uid": r["to_uid"]}
        for r in reloaded.dependency_rules["rejected"]]


def test_scope_preview_returns_v3_explanations_and_is_read_only(api):
    client, manager, _ = api
    adopt_v3(client, roots=[{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                             "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]}],
             requires_edges=[{"from_uid": "a", "to_uid": "tech"}])
    before = manager._path("book").read_bytes()
    response = client.post("/api/worldbook/book/scope-preview",
                           json={"roster_character_ids": ["A"]})
    assert response.status_code == 200
    body = response.json
    assert set(body["scope"]["resolved_entry_uids"]) == {"a", "tech"}
    assert body["active_roots"][0]["entry_uid"] == "a"
    assert body["selection_reasons"]["tech"] == ["requires"]
    assert body["display_tree"] and body["display_tree"][0]["uid"] == "a"
    assert body["draft_hash"] and body["policy_revision"] == 3
    assert body["content_revision"] and body["resolver_version"] == 3
    assert manager._path("book").read_bytes() == before


def test_scope_preview_reports_single_character_and_manual_additions(api):
    client, _, _ = api
    adopt_v3(client, roots=[
        {"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
         "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]},
        {"entry_uid": "b", "activation": ACTIVATION_ROSTER_ANY,
         "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["B"]}])
    single = client.post("/api/worldbook/book/scope-preview",
                         json={"roster_character_ids": ["A"]}).json
    assert set(single["scope"]["resolved_entry_uids"]) == {"a"}
    manual = client.post("/api/worldbook/book/scope-preview",
                         json={"roster_character_ids": ["A"], "manual_entry_uids": ["tech"]}).json
    assert set(manual["scope"]["resolved_entry_uids"]) == {"a", "tech"}
    assert manual["selection_reasons"]["tech"] == ["manual"]


def test_manual_append_expands_its_required_closure(api):
    """手动追加是**临时起点**：它需要的必要依赖也要一起带进来，并且可解释。

    旧实现是「解析完之后并集 UID」，所以空阵容下追加 A（A requires B）
    只会得到 A：既没有 B，也没有树和原因。
    """
    client, _, _ = api
    adopt_v3(client, roots=[],
             requires_edges=[{"from_uid": "a", "to_uid": "tech"}])
    empty = client.post("/api/worldbook/book/scope-preview",
                        json={"roster_character_ids": []}).json
    assert empty["scope"]["resolved_entry_uids"] == []

    manual = client.post("/api/worldbook/book/scope-preview",
                         json={"roster_character_ids": [], "manual_entry_uids": ["a"]}).json
    resolved = set(manual["scope"]["resolved_entry_uids"])
    assert resolved == {"a", "tech"}, "手动追加没有展开它需要的必要依赖"
    assert manual["selection_reasons"]["a"] == ["manual"]
    assert manual["selection_reasons"]["tech"] == ["requires"]
    tree = {node["uid"]: node for node in manual["display_tree"]}
    assert tree["a"]["is_root"] is True and tree["tech"]["parent_uid"] == "a"


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


def test_proposal_reading_mode_defaults_validates_and_persists(api):
    client, _, _ = api
    invalid = client.post("/api/worldbook/book/dependency-proposals",
                          json={"reading_mode": "adaptiv"})
    assert invalid.status_code == 400
    created = client.post("/api/worldbook/book/dependency-proposals", json={})
    assert created.status_code == 202
    assert created.json["job"]["reading_mode"] == "adaptive"
    final = wait_for(client, "book", created.json["job"]["job_id"])
    assert final["reading_mode"] == "adaptive"


def test_retry_rejects_reading_mode_change(api):
    client, _, _ = api
    job_id, _ = run_job(client)
    import blueprints.worldbook as module
    job = module._JOB_STORE.get(job_id)
    job.resumable = True
    job.failed_batches = [{"stage": "cards", "uids": ["a"], "code": "probe"}]
    job.pending_card_uids = ["a"]
    job.save()
    response = client.post(f"/api/worldbook/book/dependency-proposals/{job_id}/retry",
                           json={"reading_mode": "full"})
    assert response.status_code == 409
    assert module._JOB_STORE.get(job_id).reading_mode == "adaptive"


@pytest.mark.parametrize("request_kwargs", [
    {"headers": {"Content-Type": "application/json"}},
    {"json": ["not-an-object"]},
], ids=["frontend-empty-body", "non-object-json"])
def test_retry_accepts_optional_object_body(api, request_kwargs):
    """续跑请求体可省略；非对象 JSON 也不应导致框架级 400/500。"""
    client, _, _ = api
    job_id, _ = run_job(client)
    import blueprints.worldbook as module
    job = module._JOB_STORE.get(job_id)
    job.stage = "failed"
    job.resumable = True
    job.failed_batches = [{"stage": "cards", "uids": ["a"], "code": "probe"}]
    job.pending_card_uids = ["a"]
    job.save()

    response = client.post(
        f"/api/worldbook/book/dependency-proposals/{job_id}/retry",
        **request_kwargs,
    )

    assert response.status_code == 202, response.get_data(as_text=True)
    assert response.is_json
    assert wait_for(client, "book", job_id)["stage"] == "done"


def test_proposal_job_can_be_cancelled_and_retried(api):
    client, _, _ = api
    job_id = client.post("/api/worldbook/book/dependency-proposals", json={}).json["job"]["job_id"]
    assert client.post(f"/api/worldbook/book/dependency-proposals/{job_id}/cancel").status_code == 200
    cancelled = client.get(f"/api/worldbook/book/dependency-proposals/{job_id}").json["job"]
    assert cancelled["cancelled"] is True
    assert cancelled["stage"] in ("cancelled", "done")
    import blueprints.worldbook as module
    job = module._JOB_STORE.get(job_id)
    deadline = time.time() + 5
    while job.running and time.time() < deadline:
        time.sleep(0.01)
    assert not job.running
    pending = bool(job.pending_pairs or job.pending_card_uids or job.failed_batches or job.resumable)
    retry = client.post(f"/api/worldbook/book/dependency-proposals/{job_id}/retry", json={})
    assert retry.status_code == (202 if pending else 400), retry.json
    if pending:
        assert wait_for(client, "book", job_id)["stage"] == "done"


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
    adopt_v3(client, roots=[{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                             "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]}],
             requires_edges=[{"from_uid": "a", "to_uid": "tech"}])
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
    adopt_v3(client, roots=[{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                             "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]}],
             requires_edges=[{"from_uid": "a", "to_uid": "tech"}])
    created = client.post("/api/sessions",
                          json={"worldbook_id": "book", "roster_character_ids": ["A"]})
    bound = created.json["worldbook_scope"]
    assert set(bound["resolved_entry_uids"]) == {"a", "tech"}

    # 书改成不再依赖 tech
    revision = books.load("book").import_config["revision"]
    client.put("/api/worldbook/book/configuration", json={
        "expected_revision": revision, "requires_edges": []})
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
    job_id, final = run_job(client)
    record = final["result"]["records"][0]
    pair = [record["from_uid"], record["to_uid"]]

    first = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1, "adopt_v3": True,
        "roots": [{"entry_uid": "tech", "activation": ACTIVATION_ALWAYS,
                   "expansion": EXPANSION_REQUIRES_CLOSURE}],
        "related_edges": [{"from_uid": "world", "to_uid": "tech"}],
    })
    assert first.status_code == 200, first.json
    revision = first.json["policy_revision"]

    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": revision,
        # 草稿里的起点与边（人工）
        "roots": [{"entry_uid": "tech", "activation": ACTIVATION_ALWAYS,
                   "expansion": EXPANSION_REQUIRES_CLOSURE}],
        "requires_edges": [],
        "related_edges": [{"from_uid": "world", "to_uid": "tech"}],
        # 同时应用 AI 建议
        "proposal": {"job_id": job_id, "accepted_pairs": [pair]},
    })
    assert response.status_code == 200, response.json
    stored = manager.load("book")
    roots = {r["entry_uid"]: r for r in stored.dependency_rules["roots"]}
    # 人工起点保留
    assert roots["tech"]["activation"] == ACTIVATION_ALWAYS
    # AI 派生起点并入（角色条目 → roster 起点），而不是替换整份配置
    assert roots["a"]["activation"] == ACTIVATION_ROSTER_ANY
    assert {"from_uid": pair[0], "to_uid": pair[1]} in stored.dependency_edges
    assert {"from_uid": "world", "to_uid": "tech"} in stored.related_edges
    # 同一条边不会因为重复提交而出现两次
    assert len(stored.dependency_edges) == len(
        {(e["from_uid"], e["to_uid"]) for e in stored.dependency_edges})


def test_full_scope_preview_and_session_creation_are_explicit_and_consistent(session_api):
    """显式全量兼容：预览与创建一致，只影响本会话，不改这本书的规则。"""
    client, _, books, _ = session_api
    adopt_v3(client, roots=[{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                             "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]}])
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
    adopt_v3(client, roots=[{"entry_uid": "a", "activation": ACTIVATION_ROSTER_ANY,
                             "expansion": EXPANSION_REQUIRES_CLOSURE, "character_ids": ["A"]}])
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

def test_old_entry_route_and_configuration_share_transaction_lock(api, monkeypatch):
    import threading
    import blueprints.worldbook as module
    client, manager, _ = api
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = module._entry_from_payload
    def paused(payload, uid=None):
        entered.set()
        assert release.wait(5)
        return original(payload, uid)
    monkeypatch.setattr(module, '_entry_from_payload', paused)
    responses = {}
    def old_write():
        with client.application.test_client() as c:
            responses['entry'] = c.put('/api/worldbook/book/entries/tech', json={'content':'new definition'})
    def config_write():
        with client.application.test_client() as c:
            responses['config'] = c.put('/api/worldbook/book/configuration', json={
                'expected_revision':2, 'adopt_v3':True,
                'roots':[{'entry_uid':'tech','activation':'always','expansion':'none'}]})
            finished.set()
    a=threading.Thread(target=old_write); b=threading.Thread(target=config_write)
    a.start(); assert entered.wait(3); b.start()
    assert not finished.wait(.1), 'configuration must wait for old entry transaction'
    release.set(); a.join(5); b.join(5)
    assert responses['entry'].status_code == responses['config'].status_code == 200
    stored=manager.load('book')
    assert next(e for e in stored.entries if e.uid=='tech').content == 'new definition'
    assert any(r['entry_uid']=='tech' for r in stored.dependency_rules['roots'])


def test_materialized_proposal_does_not_readd_deleted_edge(api):
    client, manager, _ = api
    job_id, final = run_job(client)
    pair = ['a','tech']
    saved = client.put('/api/worldbook/book/configuration', json={
        'expected_revision':1,'adopt_v3':True,'roots':[], 'requires_edges':[], 'related_edges':[],
        'proposal':{'job_id':job_id,'accepted_pairs':[pair],'materialized':True}})
    assert saved.status_code==200, saved.json
    assert not manager.load('book').dependency_edges
    assert {'from_uid':'a','to_uid':'tech'} in manager.load('book').dependency_rules['rejected']


def test_empty_selection_and_cancelled_proposal_are_not_applied(api):
    client, manager, _ = api
    job_id, _ = run_job(client)
    response=client.put('/api/worldbook/book/configuration',json={
        'adopt_v3':True,'proposal':{'job_id':job_id,'accepted_pairs':[]}})
    assert response.status_code==200
    assert not manager.load('book').dependency_edges
    client.post(f'/api/worldbook/book/dependency-proposals/{job_id}/cancel')
    response=client.put('/api/worldbook/book/configuration',json={
        'proposal':{'job_id':job_id,'accepted_pairs':[['a','tech']]}})
    assert response.status_code==400


def test_materialized_frontend_shape_keeps_full_root_plan_and_expands_requires(api):
    """真实面板请求形状保存完整根计划；v2 的 none 根不会吞掉 AI requires 闭包。"""
    client, manager, _ = api
    job_id, final = run_job(client)
    result = final["result"]
    roots = result["configuration_roots"]
    accepted = [item for item in result["accepted"] if item["relation"] == "requires"]
    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1, "adopt_v3": True, "scope_mode": "selective",
        "roots": roots,
        "requires_edges": [{"from_uid": item["from_uid"], "to_uid": item["to_uid"]}
                           for item in accepted],
        "related_edges": [],
        "proposal": {"materialized": True, "job_id": job_id,
                     "materialized_root_uids": [root["entry_uid"] for root in roots],
                     "accepted": accepted,
                     "accepted_pairs": [[item["from_uid"], item["to_uid"]] for item in accepted]},
    })
    assert response.status_code == 200, response.json
    stored = manager.load("book")
    root = next(root for root in stored.dependency_rules["roots"] if root["entry_uid"] == "a")
    assert root["expansion"] == EXPANSION_REQUIRES_CLOSURE
    preview = client.post("/api/worldbook/book/scope-preview",
                          json={"roster_character_ids": ["A"]}).json
    assert {"a", "tech"} <= set(preview["scope"]["resolved_entry_uids"])


def test_materialized_fabricated_ai_root_is_rejected_by_real_route(api):
    """materialized 不是信任边界：真实 UI 形状也不能把伪 AI 根写入配置。"""
    client, manager, _ = api
    job_id, _ = run_job(client)
    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1, "adopt_v3": True,
        "roots": [{
            "entry_uid": "tech", "activation": "roster_any",
            "character_ids": ["NO_SUCH_CHARACTER"], "expansion": "requires_closure",
            "origin": "llm", "source_content_hash": content_hash("源石技艺的定义与规则。"),
            "evidence": "MADE UP QUOTE", "model": "forged", "prompt_version": "forged",
        }],
        "requires_edges": [], "related_edges": [],
        "proposal": {"materialized": True, "job_id": job_id,
                     "materialized_root_uids": ["tech"], "accepted_pairs": []},
    })
    assert response.status_code == 400
    assert "与服务端构建任务的已验证建议不一致" in response.json["error"]
    assert all(root.get("entry_uid") != "tech" or root.get("origin") != "llm"
               for root in (manager.load("book").dependency_rules or {}).get("roots", []))


def test_materialized_verified_ai_root_is_preserved_and_stamped(api):
    """合法的物化 AI 根逐字段匹配任务后保留，并由服务端写入任务身份。"""
    import blueprints.worldbook as module
    client, manager, _ = api
    job_id, _ = run_job(client)
    job = module._JOB_STORE.get(job_id)
    root = {
        "entry_uid": "tech", "activation": "always", "character_ids": [],
        "expansion": "requires_closure", "origin": "llm",
        "source_content_hash": content_hash("源石技艺的定义与规则。"),
        "evidence": "源石技艺的定义与规则", "model": job.model,
        "prompt_version": "wb-dep-v3", "review_status": "proposed",
        "reason": "分析卡建议作为基础世界设定",
    }
    job.result["roots"] = [root]
    job.save()
    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1, "adopt_v3": True, "roots": [root],
        "requires_edges": [], "related_edges": [],
        "proposal": {"materialized": True, "job_id": job_id,
                     "materialized_root_uids": ["tech"], "accepted_pairs": []},
    })
    assert response.status_code == 200, response.json
    stored = next(item for item in manager.load("book").dependency_rules["roots"]
                  if item["entry_uid"] == "tech")
    assert stored["origin"] == "llm"
    assert stored["job_id"] == job_id
    assert stored["review_status"] == "applied"
    assert stored["evidence"] == root["evidence"]


def test_materialized_human_rewrite_must_be_manual_and_uses_normal_rules(api):
    """用户可改写建议，但必须显式转 manual；此后按普通根规则校验和保存。"""
    client, manager, _ = api
    job_id, _ = run_job(client)
    manual_root = {
        "entry_uid": "tech", "activation": "manual", "character_ids": [],
        "expansion": "none", "origin": "manual", "reason": "用户改写",
    }
    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1, "adopt_v3": True, "roots": [manual_root],
        "requires_edges": [], "related_edges": [],
        "proposal": {"materialized": True, "job_id": job_id,
                     "materialized_root_uids": ["tech"], "accepted_pairs": []},
    })
    assert response.status_code == 200, response.json
    stored = next(item for item in manager.load("book").dependency_rules["roots"]
                  if item["entry_uid"] == "tech")
    assert stored["origin"] == "manual"
    assert stored["activation"] == "manual" and stored["expansion"] == "none"


def test_materialized_expansion_edit_as_manual_saves_like_real_overview_button(api):
    """“改为只含自身”保留激活语义，但转人工来源并清掉 AI 专属元数据后可保存。"""
    client, manager, _ = api
    job_id, final = run_job(client)
    roots = copy.deepcopy(final["result"]["configuration_roots"])
    edited = next(root for root in roots if root["activation"] == "always")
    edited["expansion"] = "none"
    edited["origin"] = "manual"
    for field in ("model", "prompt_version", "source_content_hash", "evidence",
                  "review_status", "job_id", "reason"):
        edited.pop(field, None)

    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1, "adopt_v3": True, "roots": roots,
        "requires_edges": [], "related_edges": [],
        "proposal": {"materialized": True, "job_id": job_id,
                     "materialized_root_uids": [root["entry_uid"] for root in roots],
                     "accepted_pairs": []},
    })
    assert response.status_code == 200, response.json
    stored = next(root for root in manager.load("book").dependency_rules["roots"]
                  if root["entry_uid"] == edited["entry_uid"])
    assert stored["activation"] == edited["activation"]
    assert stored["expansion"] == "none" and stored["origin"] == "manual"
    assert not ({"model", "prompt_version", "source_content_hash", "evidence",
                 "review_status", "job_id"} & set(stored))


def test_materialized_draft_preserves_exact_saved_ai_root_absent_from_current_job(api):
    """完整草稿可原样带回旧正式 AI root；它无需被当前 job 再次建议。"""
    client, manager, _ = api
    book = manager.load("book")
    old_root = {
        "entry_uid": "tech", "activation": "always", "character_ids": [],
        "expansion": "requires_closure", "origin": "llm",
        "source_content_hash": content_hash("源石技艺的定义与规则。"),
        "evidence": "源石技艺的定义与规则", "model": "old-model",
        "prompt_version": "old-prompt", "review_status": "applied",
        "job_id": "old-job",
    }
    book.schema_version = 3
    book.dependency_rules = {
        "roots": [copy.deepcopy(old_root)], "root_rule": {"entry_uids": ["tech"]},
        "rejected": [], "edge_meta": {},
    }
    book.dependency_edges = []
    book.related_edges = []
    manager.save(book)

    job_id, final = run_job(client)
    current_roots = copy.deepcopy(final["result"]["configuration_roots"])
    assert all(root["entry_uid"] != "tech" for root in current_roots)

    for field, value in (
        ("evidence", "伪造证据"),
        ("source_content_hash", "bad-hash"),
        ("character_ids", ["NO_SUCH_CHARACTER"]),
        ("activation", "roster_any"),
    ):
        tampered = {**old_root, field: value}
        rejected = client.put("/api/worldbook/book/configuration", json={
            "expected_revision": 1, "roots": [tampered, *current_roots],
            "requires_edges": [], "related_edges": [],
            "proposal": {"materialized": True, "job_id": job_id,
                         "materialized_root_uids": [root["entry_uid"] for root in current_roots],
                         "accepted_pairs": []},
        })
        assert rejected.status_code == 400, (field, rejected.json)

    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1, "roots": [old_root, *current_roots],
        "requires_edges": [], "related_edges": [],
        "proposal": {"materialized": True, "job_id": job_id,
                     "materialized_root_uids": [root["entry_uid"] for root in current_roots],
                     "accepted_pairs": []},
    })
    assert response.status_code == 200, response.json
    stored = next(root for root in manager.load("book").dependency_rules["roots"]
                  if root["entry_uid"] == "tech")
    assert stored == old_root


def test_server_rejects_fabricated_root_evidence_inside_persisted_job(api):
    """即使客户端或任务文件伪造 root，服务端也逐条复核而不是直接复制。"""
    import blueprints.worldbook as module
    client, manager, _ = api
    job_id, _ = run_job(client)
    job = module._JOB_STORE.get(job_id)
    job.result["roots"] = [{
        "entry_uid": "tech", "activation": "always", "expansion": "requires_closure",
        "origin": "llm", "source_content_hash": content_hash("源石技艺的定义与规则。"),
        "evidence": "MADE UP QUOTE", "review_status": "proposed",
    }]
    job.save()
    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1, "adopt_v3": True,
        "proposal": {"job_id": job_id, "accepted_pairs": []},
    })
    assert response.status_code == 200, response.json
    assert all(root["entry_uid"] != "tech"
               for root in manager.load("book").dependency_rules["roots"])


def test_locked_manual_relation_wins_over_opposite_ai_relation(api):
    """旧/恶意 materialized 请求含相反 AI 类型时不整单 400，其余建议继续应用。"""
    import blueprints.worldbook as module
    client, manager, _ = api
    job_id, final = run_job(client)
    job = module._JOB_STORE.get(job_id)
    book = manager.load("book")
    second = {
        "from_uid": "b", "to_uid": "tech", "relation": "requires", "confidence": .8,
        "reason": "测试", "evidence": "与角色A同属罗德岛",
        "evidence_hash": content_hash("与角色A同属罗德岛")[:16],
        "source_content_hash": content_hash(next(e.content for e in book.entries if e.uid == "b")),
        "target_content_hash": content_hash(next(e.content for e in book.entries if e.uid == "tech")),
        "origin": "llm", "model": job.model, "prompt_version": "test", "review_status": "proposed",
    }
    job.result["records"].append(second)
    job.result["accepted"].append({"from_uid": "b", "to_uid": "tech",
                                   "relation": "requires", "confidence": .8})
    job.save()

    book.schema_version = 3
    book.dependency_rules = {
        "roots": [], "root_rule": {"entry_uids": []}, "rejected": [],
        "edge_meta": {"a|tech": {"origin": "manual", "locked": True}},
    }
    book.related_edges = [{"from_uid": "a", "to_uid": "tech"}]
    book.dependency_edges = []
    manager.save(book)
    response = client.put("/api/worldbook/book/configuration", json={
        "expected_revision": 1,
        "roots": [],
        "requires_edges": [{"from_uid": "a", "to_uid": "tech"},
                           {"from_uid": "b", "to_uid": "tech"}],
        "related_edges": [{"from_uid": "a", "to_uid": "tech"}],
        "proposal": {"materialized": True, "job_id": job_id,
                     "accepted_pairs": [["a", "tech"], ["b", "tech"]]},
    })
    assert response.status_code == 200, response.json
    stored = manager.load("book")
    assert {"from_uid": "a", "to_uid": "tech"} in stored.related_edges
    assert {"from_uid": "a", "to_uid": "tech"} not in stored.dependency_edges
    assert {"from_uid": "b", "to_uid": "tech"} in stored.dependency_edges


def test_applied_ai_evidence_staleness_is_visible_in_detail_and_preview(api):
    client, manager, _ = api
    book = manager.load("book")
    a = next(entry for entry in book.entries if entry.uid == "a")
    tech = next(entry for entry in book.entries if entry.uid == "tech")
    book.schema_version = 3
    book.dependency_edges = [{"from_uid": "a", "to_uid": "tech"}]
    book.dependency_rules = {
        "roots": [{"entry_uid": "tech", "activation": "always", "expansion": "requires_closure",
                   "character_ids": [],
                   "origin": "llm", "source_content_hash": content_hash(tech.content),
                   "evidence": "源石技艺的定义与规则", "review_status": "applied"}],
        "root_rule": {"entry_uids": ["tech"]}, "rejected": [],
        "edge_meta": {"a|tech": {"origin": "llm",
            "source_content_hash": content_hash(a.content),
            "target_content_hash": content_hash(tech.content),
            "evidence": "他使用源石技艺", "review_status": "applied"}},
    }
    manager.save(book)
    assert client.get("/api/worldbook/book").json["evidence_issues"] == []

    changed = client.put("/api/worldbook/book/entries/tech", json={"content": "全新的正文。"})
    assert changed.status_code == 200
    detail = client.get("/api/worldbook/book").json
    codes = {issue["code"] for issue in detail["evidence_issues"]}
    assert {"ai_root_evidence_stale", "ai_edge_evidence_stale"} <= codes
    preview = client.post("/api/worldbook/book/scope-preview", json={}).json
    preview_codes = {issue["code"] for issue in preview["issues"]}
    assert {"ai_root_evidence_stale", "ai_edge_evidence_stale"} <= preview_codes


def test_v3_legacy_mode_and_v2_session_are_preserved(api):
    client, manager, _ = api
    previous=manager.load('book').resolve_import_scope(['A'])
    adopt_v3(client,roots=[])
    book=manager.load('book')
    assert book.refresh_session_scope(previous,['A'])['resolved_entry_uids']
    assert book.refresh_session_scope(previous,['A']).get('schema_version') != 3
    response=client.put('/api/worldbook/book/configuration',json={'scope_mode':'legacy','roots':[]})
    assert response.status_code==200
    book=manager.load('book')
    assert set(book.session_scope_snapshot([])['resolved_entry_uids'])=={e.uid for e in book.entries}


def test_preinstalled_ordinary_save_preserves_candidates(tmp_path):
    import blueprints.worldbook as module
    original=WorldBookManager(Path(__file__).resolve().parents[1]/'data/worldbooks').load('arknights')
    if original is None:
        pytest.skip('preinstalled book unavailable')
    manager=WorldBookManager(tmp_path/'books');manager.save(copy.deepcopy(original))
    app=Flask(__name__);module.register(app,{'worldbook':manager})
    before=manager.load(original.id).resolve_import_scope([])['resolved_entry_uids']
    response=app.test_client().put(f'/api/worldbook/{original.id}/configuration',json={
        'expected_revision':original.import_config['revision'],'categories':original.categories})
    assert response.status_code==200,response.json
    after=manager.load(original.id)
    # 普通保存**不能悄悄改变 v3 状态**。预装书本就是 v3（本地 data/worldbooks 是
    # gitignored 的运行数据），硬编码 `not after.v3_enabled` 只在书还是 v2 时成立，
    # 属于把「保存前后一致」写成了「保存后必须是 v2」。
    assert after.v3_enabled == original.v3_enabled
    assert after.resolve_import_scope([])['resolved_entry_uids']==before
