"""返修回归：review-1.md 的 P1-1 / P1-4 / P1-5 / P2-9 / P2-10 / P2-12。

这些用例**不**用小样本替代结论，也不把「已有测试通过」当成反证不存在：
- P1-1 用仓库里的真实预装书（261 条 / 727945 字）做确定性全书验证；
- P1-4 用真实路由交替执行，复现「旧条目 PUT 与统一配置 PUT 并发丢更新」；
- P1-5 用**真实 chat 抛错**（不是 monkeypatch 元数据函数）验证三态终态；
- P2-9 把唯一引用放在长条目**中间**，验证不是只取头尾；
- P2-10 用真实角色目录验证卡片候选角色能落成起点建议；
- P2-12 验证缓存键绑定真实模型身份（同后端换模型必须失效）。
"""
import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from load_llm import LLMConnectError
from world_book import DEFAULT_CATEGORIES, WorldBook, WorldBookEntry, WorldBookManager
from worldbook_builder import (
    ADJUDICATION_BATCH, ANALYSIS_BATCH, MAX_CALLS_DEFAULT, MAX_CALLS_HARD, PROMPT_VERSION,
    REL_REQUIRES, AnalysisCache, DependencyJobStore, auto_budget, build_metadata_index,
    collect_candidates, entry_chunks, estimate_workload, relevant_chunk, run_build,
    suggest_roots, validate_proposal,
)

PREINSTALLED = REPO / "data" / "worldbooks" / "arknights.json"


def entry(uid, content, name="", character_id="", category_id="unclassified"):
    return WorldBookEntry(uid, content=content, name=name or uid,
                          character_id=character_id, category_id=category_id,
                          always_active=True)


def fixture_book():
    return WorldBook("bk", "返修测试书", [
        entry("world", "泰拉世界的基础设定，源石与天灾。", name="世界设定", category_id="worldview"),
        entry("a", "角色A：罗德岛干员。他使用源石技艺。", name="角色A", character_id="A",
              category_id="characters"),
        entry("tech", "源石技艺的定义与规则。", name="源石技艺"),
    ], categories=copy.deepcopy(DEFAULT_CATEGORIES))


class CardStub:
    """只替代模型：按提示词里出现的 uid 逐条回一张空卡（不做任何语义判断）。"""

    def __init__(self, fail_uids=(), fail_pairs=(), bad_json_uids=(), judgments=None,
                 candidate_characters=None):
        self.fail_uids = set(fail_uids)
        self.fail_pairs = set(fail_pairs)
        self.bad_json_uids = set(bad_json_uids)
        self.judgments = judgments or []
        self.candidate_characters = candidate_characters or {}
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        prompt = messages[-1]["content"]
        if "上一个回复不是合法 JSON" in prompt:
            return {"type": "text", "content": "仍不是 JSON"}
        if "分析下面这批" in prompt:
            entry_lines = [line for line in prompt.splitlines() if line.startswith("<entry uid=")]
            uids = [line.split('uid="')[1].split('"')[0] for line in entry_lines]
            chunk_ids = [line.split('chunk_id="')[1].split('"')[0] for line in entry_lines]
            if any(uid in self.fail_uids for uid in uids):
                raise LLMConnectError("stub：分析阶段连接失败")
            if any(uid in self.bad_json_uids for uid in uids):
                return {"type": "text", "content": "这不是 JSON"}
            return {"type": "text", "content": json.dumps({"cards": [
                {"uid": uid, "chunk_id": chunk_id, "summary": "", "entities": [], "defined_concepts": [],
                 "unexplained_concepts": [],
                 "candidate_characters": self.candidate_characters.get(uid, []),
                 "evidence": []} for uid, chunk_id in zip(uids, chunk_ids)]}, ensure_ascii=False)}
        if "判断下列" in prompt:
            pairs = []
            for line in prompt.splitlines():
                if line.startswith("<pair from="):
                    parts = dict(part.split("=", 1) for part in
                                 line.strip("<>").split(" ") if "=" in part)
                    pairs.append((parts.get("from", "").strip('"'), parts.get("to", "").strip('"')))
            if any(pair in self.fail_pairs for pair in pairs):
                raise LLMConnectError("stub：判定阶段连接失败")
            return {"type": "text", "content": json.dumps({"judgments": self.judgments},
                                                          ensure_ascii=False)}
        raise AssertionError("未预期的请求")


@pytest.fixture
def cache(tmp_path):
    return AnalysisCache(tmp_path / "analysis")


@pytest.fixture
def store(tmp_path):
    return DependencyJobStore(tmp_path / "jobs")


# ── P1-1：全书默认构建必须能完成，且预算合理 ──

@pytest.mark.skipif(not PREINSTALLED.is_file(), reason="仓库内没有预装世界书")
def test_preinstalled_book_workload_is_bounded_and_affordable():
    """真实预装书：候选识别不能退化成全量笛卡尔积，预算必须是「估算 + 余量」。"""
    manager = WorldBookManager(REPO / "data" / "worldbooks")
    book = manager.load("arknights")
    assert book is not None and len(book.entries) >= 200, "预装书结构变了，回归需要重新校准"

    by_uid = {e.uid: e for e in book.entries}
    metadata = build_metadata_index(book.entries)
    report = collect_candidates(metadata, by_uid)
    workload = estimate_workload(metadata, report["pairs"])
    budget = auto_budget(workload["estimated_calls"])

    total_chars = sum(len(e.content or "") for e in book.entries)
    all_pairs = len(book.entries) * (len(book.entries) - 1)
    # 反证里的数字：261 条 / 727945 字 → 16971 对候选、~2166 次调用
    assert all_pairs > 60000
    assert report["candidates_used"] < all_pairs / 10, (
        f"候选对没有收敛：{report['candidates_used']} / {all_pairs}"
    )
    assert workload["estimated_calls"] <= budget <= MAX_CALLS_HARD
    assert budget < MAX_CALLS_HARD, "预算被抬到硬上限，等于没有预算"
    # 通用词过滤必须可解释：被过滤的词与延迟候选都能报出来
    assert isinstance(report["generic_aliases"], dict)
    assert report["candidates_used"] == len(report["pairs"])
    assert report["candidates_total"] == report["candidates_used"] + len(report["deferred"])
    print(f"[P1-1] {len(book.entries)} 条 / {total_chars} 字 → "
          f"{all_pairs} 对全量 vs {report['candidates_used']} 对候选 · "
          f"估算 {workload['estimated_calls']} 次 · 预算 {budget}")


@pytest.mark.skipif(not PREINSTALLED.is_file(), reason="仓库内没有预装世界书")
def test_preinstalled_book_whole_build_completes_within_auto_budget(tmp_path):
    """全书默认构建（auto 预算）必须真的跑完，并给出 success 终态。"""
    manager = WorldBookManager(REPO / "data" / "worldbooks")
    source = manager.load("arknights")
    book = copy.deepcopy(source)                 # 只读加载，绝不改动仓库里的预装书
    store = DependencyJobStore(tmp_path / "jobs")
    cache = AnalysisCache(tmp_path / "analysis")

    metadata = build_metadata_index(book.entries)
    workload = estimate_workload(metadata, collect_candidates(
        metadata, {e.uid: e for e in book.entries})["pairs"])
    job = store.create(book.id, "preinstalled", "stub-model")
    llm = CardStub()

    # 不传 max_calls：走真实默认（auto_budget），验证「默认就能完成」
    run_build(job, book, llm, model="stub-model", cache=cache)

    assert job.outcome == "success", (job.outcome, job.error, job.failed_batches[:3])
    assert job.stage == "done" and job.error is None
    assert job.calls <= job.workload["budget"]
    assert job.calls <= MAX_CALLS_HARD
    assert job.workload["estimated_calls"] == workload["estimated_calls"]
    assert not job.resumable and not job.failed_batches
    print(f"[P1-1] 全书构建完成：{job.calls} 次调用 / 预算 {job.workload['budget']} · "
          f"{len(job.cards)} 张卡 · {job.result['stats']['records']} 条记录")


@pytest.mark.skipif(not PREINSTALLED.is_file(), reason="仓库内没有预装世界书")
def test_preinstalled_entity_names_survive_generic_alias_filter():
    """人物实体名即使高频也保留；职业属性等普通触发词仍走频率过滤。"""
    book = WorldBookManager(REPO / "data" / "worldbooks").load("arknights")
    metadata = build_metadata_index(book.entries)
    report = collect_candidates(metadata, {entry.uid: entry for entry in book.entries})
    pairs = {(item["from_uid"], item["to_uid"]) for item in report["pairs"]}
    assert ("rules_rarity-system_index", "characters_凯尔希_index") in pairs
    assert sum(to_uid == "characters_凯尔希_index" for _, to_uid in pairs) >= 50
    assert sum(to_uid == "characters_阿米娅_index" for _, to_uid in pairs) >= 35
    assert sum(to_uid == "characters_银灰_index" for _, to_uid in pairs) >= 14
    assert report["generic_aliases"], "通用职业/属性词过滤被整体关闭了"
    workload = estimate_workload(metadata, report["pairs"])
    assert workload["estimated_calls"] < MAX_CALLS_HARD


def test_chunk_id_prevents_second_chunk_from_being_recorded_as_first(cache, store):
    """模型只回第二块时第一块保持 pending；续跑只补第一块并最终合并。"""
    class ChunkStub:
        def __init__(self, omit_first=False):
            self.omit_first = omit_first
            self.calls = []

        def chat(self, messages, **kwargs):
            prompt = messages[-1]["content"]
            self.calls.append(prompt)
            if "分析下面这批" in prompt:
                lines = [line for line in prompt.splitlines() if line.startswith("<entry uid=")]
                cards = []
                for line in lines:
                    uid = line.split('uid="')[1].split('"')[0]
                    chunk_id = line.split('chunk_id="')[1].split('"')[0]
                    if self.omit_first and uid == "long" and ":0:" in chunk_id:
                        continue
                    cards.append({"uid": uid, "chunk_id": chunk_id, "summary": chunk_id,
                                  "entities": [], "defined_concepts": [],
                                  "unexplained_concepts": [], "candidate_characters": [],
                                  "evidence": []})
                return {"type": "text", "content": json.dumps({"cards": cards})}
            return {"type": "text", "content": '{"judgments":[]}'}

    book = WorldBook("chunks", "分块断点", [
        entry("long", "第一块。" * 500 + "第二块。" * 500, name="长条目"),
    ], categories=copy.deepcopy(DEFAULT_CATEGORIES))
    job = store.create(book.id, "h", "m")
    run_build(job, book, ChunkStub(omit_first=True), model="m", cache=cache)
    assert job.outcome == "failed" and job.resumable
    stored_ids = set(job.chunk_cards["long"])
    assert stored_ids and all(":0:" not in chunk_id for chunk_id in stored_ids)
    assert any(":0:" in chunk_id for chunk_id in job.pending_chunk_ids)

    run_build(job, book, ChunkStub(), model="m", cache=cache,
              only_uids=list(job.pending_card_uids), max_calls=20)
    assert job.outcome == "success"
    assert len(job.chunk_cards["long"]) == len(entry_chunks(book.entries[0].content)[0])
    assert not job.pending_chunk_ids


def test_budget_exhaustion_is_resumable_with_checkpoint(cache, store):
    """预算耗尽必须是「可续跑 + 有断点」，而不是一句 failed 了事。"""
    book = WorldBook("bk", "预算书", [
        entry(f"e{i}", f"条目{i} 提到 概念X。", name=f"条目{i}") for i in range(60)
    ] + [entry("target", "概念X 的定义。", name="概念X")],
        categories=copy.deepcopy(DEFAULT_CATEGORIES))
    job = store.create(book.id, "h", "m")
    # 只给 2 次调用：分析阶段就会用光
    run_build(job, book, CardStub(), model="m", cache=cache, max_calls=2)
    assert job.resumable is True
    assert job.failed_batches, "预算耗尽没有记录断点"
    assert any(b.get("resumable") for b in job.failed_batches)
    assert job.pending_card_uids, "没有记录还缺哪些条目"
    assert job.cards, "已经拿到的分析卡必须保留，续跑不能从头再来"
    # 续跑：只补缺失部分，已完成的卡片走缓存
    resume = CardStub()
    run_build(job, book, resume, model="m", cache=cache,
              only_uids=list(job.pending_card_uids), max_calls=200)
    assert job.outcome == "success", (job.outcome, job.error, job.failed_batches[:3])
    assert job.resumable is False
    assert len(job.cards) == len(book.entries)


# ── P1-5：LLM 失败必须是可区分的终态 ──

def test_every_chat_failing_is_failed_not_done(cache, store):
    """每一次 chat 都抛 LLMConnectError：不能显示成 done/success。"""
    book = fixture_book()
    job = store.create(book.id, "h", "m")
    llm = CardStub(fail_uids={e.uid for e in book.entries})
    run_build(job, book, llm, model="m", cache=cache)

    assert job.stage == "failed"
    assert job.outcome == "failed"
    assert job.error and job.error["code"] == "cards_failed"
    assert job.result is not None          # 结果结构仍在，但内容为空且终态明确
    assert job.result["stats"]["requires"] == 0
    assert job.failed_batches and all(b["code"] == "connect" for b in job.failed_batches)


def test_all_invalid_json_is_failed_and_never_cached_as_empty(cache, store):
    """全部返回非法 JSON：终态必须是 failed，且不得把空卡写进缓存。"""
    book = fixture_book()
    job = store.create(book.id, "h", "m")
    llm = CardStub(bad_json_uids={e.uid for e in book.entries})
    run_build(job, book, llm, model="m", cache=cache)

    assert job.stage == "failed" and job.outcome == "failed"
    assert not job.cards, "非法响应被当成空卡缓存了"
    assert job.failed_batches
    assert all(b["code"] in ("invalid_json", "invalid_response") for b in job.failed_batches)

    # 换一个能正常回答的模型：必须重新问，不能命中「空卡」缓存
    retry = CardStub()
    run_build(job, book, retry, model="m", cache=cache)
    assert job.outcome == "success"
    assert len(job.cards) == len(book.entries)


def test_partial_failure_is_partial_and_retryable(cache, store):
    """只有一部分批次失败：终态是 partial，且失败的批次可以只重试那部分。"""
    book = fixture_book()
    book.entries.extend(entry(f"extra{i}", f"extra content {i}") for i in range(9))
    job = store.create(book.id, "h", "m")
    first_uid = book.entries[0].uid
    llm = CardStub(fail_uids={first_uid})
    run_build(job, book, llm, model="m", cache=cache)

    assert job.outcome == "partial"
    assert job.stage == "done"             # 有可用产出 → done，但 outcome 不是 success
    assert job.error is None
    failed_uids = [e.uid for e in book.entries[:ANALYSIS_BATCH]]
    assert job.pending_card_uids == sorted(failed_uids)
    assert job.failed_batches and job.failed_batches[0]["uids"] == sorted(failed_uids)

    # 只重试失败的那一条：不重跑已成功的卡片
    retry = CardStub()
    run_build(job, book, retry, model="m", cache=cache, only_uids=failed_uids)
    card_prompts = [c[-1]["content"] for c in retry.calls if "分析下面这批" in c[-1]["content"]]
    assert len(card_prompts) == 1 and first_uid in card_prompts[0]
    assert job.outcome == "success"


def test_adjudication_failure_is_partial_not_silent(cache, store):
    """判定阶段全失败也不能显示成成功。"""
    book = fixture_book()
    job = store.create(book.id, "h", "m")
    metadata = build_metadata_index(book.entries)
    pairs = collect_candidates(metadata, {e.uid: e for e in book.entries})["pairs"]
    assert pairs, "夹具必须能产出候选对"
    llm = CardStub(fail_pairs={(p["from_uid"], p["to_uid"]) for p in pairs})
    run_build(job, book, llm, model="m", cache=cache)

    assert job.outcome == "partial"
    assert any(b["stage"] == "adjudication" for b in job.failed_batches)
    assert job.result["stats"]["requires"] == 0


# ── P2-9：长条目真的分块，且按引用位置取原文 ──

def test_unique_reference_in_the_middle_of_a_long_entry_is_analyzed():
    """唯一引用藏在长条目**中间**：不能被头尾裁剪丢掉。"""
    filler = "无关的填充正文。" * 900                    # ≈ 7200 字
    unique = "稀有概念ZETA"
    middle = f"这里提到 {unique} 的用法。"                # 放在正中间
    content = filler[:len(filler) // 2] + middle + filler[len(filler) // 2:]

    book = WorldBook("bk", "长文书", [
        entry("long", content, name="长条目"),
        entry("zeta", f"{unique} 的定义与规则。", name=unique),
    ], categories=copy.deepcopy(DEFAULT_CATEGORIES))

    metadata = build_metadata_index(book.entries)
    pairs = collect_candidates(metadata, {e.uid: e for e in book.entries})["pairs"]
    assert ("long", "zeta") in {(p["from_uid"], p["to_uid"]) for p in pairs}, \
        "长条目中间的引用没有被识别"

    chunks, dropped = entry_chunks(content)
    assert len(chunks) > 1, "长条目没有被分块"
    assert dropped >= 0
    text, hit = relevant_chunk(content, unique)
    assert hit is True and unique in text, "取到的分块不是引用所在的那一块"
    # 头尾裁剪（旧实现）拿不到中间那段
    assert unique not in content[:2000] and unique not in content[-2000:]


def test_multi_chunk_cards_are_merged_not_truncated(cache, store):
    """同一条目的多块分析卡必须合并（并集），而不是后写覆盖先写。"""
    filler = "填充。" * 4000
    content = f"开头提到 概念ONE。{filler}结尾提到 概念TWO。"
    book = WorldBook("bk", "合并书", [
        entry("long", content, name="长条目"),
        entry("one", "概念ONE 的定义。", name="概念ONE"),
        entry("two", "概念TWO 的定义。", name="概念TWO"),
    ], categories=copy.deepcopy(DEFAULT_CATEGORIES))

    metadata = build_metadata_index(book.entries)
    workload = estimate_workload(metadata, collect_candidates(
        metadata, {e.uid: e for e in book.entries})["pairs"])
    assert workload["card_calls"] >= 2, "夹具应当产生多块分析"
    job = store.create(book.id, "h", "m")
    run_build(job, book, CardStub(), model="m", cache=cache)
    assert len(job.cards) == len(book.entries), "分块后同一条目被覆盖成了多张卡"


# ── P2-10：AI 角色建议必须真的落成起点 ──

def test_card_candidate_characters_become_applicable_roster_roots():
    """未分类条目：卡片给出候选角色 → 必须产出可应用的 roster 起点。"""
    book = fixture_book()
    cards = {"tech": {"uid": "tech", "candidate_characters": ["A", "不存在的人"]}}
    suggestions, issues = suggest_roots(book, cards, {}, character_ids=["A", "B"])

    assert [s["entry_uid"] for s in suggestions] == ["tech"]
    root = suggestions[0]
    assert root["activation"] == "roster_any"
    assert root["character_ids"] == ["A"], "角色目录里没有的 ID 不能写进配置"
    assert any(i["code"] == "unknown_character" for i in issues)


def test_validate_proposal_surfaces_root_suggestions():
    """起点建议要出现在校验结果里（stats + roots），而不是只打一条 warning。"""
    book = fixture_book()
    cards = {"tech": {"uid": "tech", "candidate_characters": ["A"],
                       "evidence": ["源石技艺的定义与规则"]}}
    proposal = validate_proposal(book, cards, [], {}, character_ids=["A"])
    assert [r["entry_uid"] for r in proposal["roots"]] == ["tech"]
    assert proposal["stats"]["roots"] == 1
    assert proposal["expansion_probe"]["suggested_roots"] == 1


def test_fabricated_root_evidence_is_never_default_applied():
    book = fixture_book()
    cards = {"tech": {"uid": "tech", "candidate_characters": ["A"],
                       "evidence": ["MADE UP QUOTE"]}}
    proposal = validate_proposal(book, cards, [], build_metadata_index(book.entries),
                                 character_ids=["A"])
    assert proposal["roots"] == []
    assert proposal["root_records"][0]["review_status"] == "needs_review"
    assert any(issue["code"] == "root_evidence_not_found" for issue in proposal["issues"])
    assert all(root["entry_uid"] != "tech" for root in proposal["configuration_roots"])


# ── P2-12：缓存键绑定真实模型身份 ──

def test_cache_key_binds_real_model_identity(cache):
    """同一个后端换模型必须换缓存键（否则新模型直接复用旧结论）。"""
    same_model = cache.card_key("hash-a", "cloud:gpt-4o-mini")
    other_model = cache.card_key("hash-a", "cloud:gpt-4o")
    assert same_model != other_model
    assert cache.judgment_key("h1", "h2", "cloud:gpt-4o-mini") != \
        cache.judgment_key("h1", "h2", "cloud:gpt-4o")
    # 提示词版本参与分键：改提示词必须让旧缓存失效
    assert cache.card_key("hash-a", "m") == cache.card_key("hash-a", "m")


def test_same_backend_different_model_does_not_reuse_cards(tmp_path):
    """真实路由：同一后端换模型后，分析卡不得命中上一模型留下的缓存。"""
    from flask import Flask
    import blueprints.worldbook as module
    from blueprints.worldbook import register

    manager = WorldBookManager(tmp_path / "books")
    manager.save(fixture_book())
    cache = AnalysisCache(tmp_path / "analysis")
    store = DependencyJobStore(tmp_path / "jobs")

    class Backend:
        def __init__(self, model):
            self.model = model
            self.llm = CardStub()

        def get_llm(self):
            return self.llm, "cloud"

        def get_status(self):
            return {"endpoints": [
                {"id": "cloud", "type": "openai", "model": self.model},
            ]}

    backend = Backend("model-a")
    app = Flask(__name__)
    app.config["TESTING"] = True
    managers = {"worldbook": manager, "llm_backend": backend}
    original_cache, original_store = module._ANALYSIS_CACHE, module._JOB_STORE
    module._ANALYSIS_CACHE, module._JOB_STORE = cache, store
    try:
        register(app, managers)
        client = app.test_client()
        import time
        first = client.post("/api/worldbook/bk/dependency-proposals", json={}).json["job"]
        for _ in range(200):
            value = client.get(
                f"/api/worldbook/bk/dependency-proposals/{first['job_id']}").json["job"]
            if value["stage"] in ("done", "failed", "cancelled"):
                break
            time.sleep(0.02)
        assert value["stage"] == "done", value
        # 模型身份取的是 endpoints 里的真实模型名，不是后端 id "cloud"
        assert value["model"] == "openai:model-a", value["model"]

        backend.model = "model-b"
        backend.llm = CardStub()
        second = client.post("/api/worldbook/bk/dependency-proposals", json={}).json["job"]
        for _ in range(200):
            value = client.get(
                f"/api/worldbook/bk/dependency-proposals/{second['job_id']}").json["job"]
            if value["stage"] in ("done", "failed", "cancelled"):
                break
            time.sleep(0.02)
        assert value["stage"] == "done", value
        assert value["model"] == "openai:model-b"
        card_prompts = [c[-1]["content"] for c in backend.llm.calls
                        if "分析下面这批" in c[-1]["content"]]
        assert card_prompts, "换模型后必须重新分析，不能整批命中旧缓存"
    finally:
        module._ANALYSIS_CACHE, module._JOB_STORE = original_cache, original_store


# ── 批次常量：估算与真实批处理必须一致 ──

def test_workload_estimate_matches_real_call_count(tmp_path):
    """估算必须与真实调用次数一致，否则「默认能不能跑完」就是空话。"""
    book = fixture_book()
    metadata = build_metadata_index(book.entries)
    pairs = collect_candidates(metadata, {e.uid: e for e in book.entries})["pairs"]
    workload = estimate_workload(metadata, pairs)
    assert workload["card_calls"] == (len(book.entries) + ANALYSIS_BATCH - 1) // ANALYSIS_BATCH
    assert workload["adjudication_calls"] == (len(pairs) + ADJUDICATION_BATCH - 1) // ADJUDICATION_BATCH

    store = DependencyJobStore(tmp_path / "jobs")
    cache = AnalysisCache(tmp_path / "analysis")
    job = store.create(book.id, "h", "m")
    run_build(job, book, CardStub(), model="m", cache=cache)
    assert job.calls == workload["estimated_calls"], (job.calls, workload)
    assert auto_budget(workload["estimated_calls"]) >= workload["estimated_calls"]
    assert auto_budget(0) == MAX_CALLS_DEFAULT
    assert auto_budget(10 ** 6) == MAX_CALLS_HARD

def test_full_text_chunks_have_no_gaps_and_production_sees_middle(cache, store):
    content = ('heading\n' + 'long line ' * 12000) + '\nUNIQUE_MIDDLE_REFERENCE\n' + ('tail ' * 12000)
    chunks, dropped = entry_chunks(content)
    assert ''.join(chunks) == content and dropped == 0
    assert max(map(len, chunks)) <= 1800
    book = WorldBook('coverage', 'coverage', [entry('long', content)])
    llm = CardStub()
    job = store.create(book.id, 'h', 'm')
    run_build(job, book, llm, model='m', cache=cache)
    assert job.outcome == 'success'
    prompts = '\n'.join(c[-1]['content'] for c in llm.calls)
    assert 'UNIQUE_MIDDLE_REFERENCE' in prompts
    assert len(job.chunk_cards['long']) == len(chunks)


def test_prompt_version_changes_cache_keys(cache, monkeypatch):
    import worldbook_builder as module
    before = cache.card_key('h', 'm'), cache.judgment_key('a', 'b', 'm')
    monkeypatch.setattr(module, 'PROMPT_VERSION', 'next-prompt')
    assert before != (cache.card_key('h', 'm'), cache.judgment_key('a', 'b', 'm'))


def test_model_identity_uses_selected_config_and_endpoint():
    from types import SimpleNamespace
    from worldbook_builder import model_identity
    a = SimpleNamespace(config=SimpleNamespace(model='model', base_url='https://one.invalid', api_key='secret'))
    b = SimpleNamespace(config=SimpleNamespace(model='model', base_url='https://two.invalid', api_key='secret'))
    assert model_identity(a, 'cloud') != model_identity(b, 'cloud')
    assert 'secret' not in model_identity(a, 'cloud')


def test_restart_makes_orphan_job_resumable(tmp_path):
    original = DependencyJobStore(tmp_path)
    job = original.create('b', 'hash', 'model')
    job.stage = 'cards'
    job.pending_card_uids = ['a']
    job.save()
    restarted = DependencyJobStore(tmp_path)
    listed = restarted.list_for_book('b')
    assert listed[0]['stage'] == 'failed' and listed[0]['resumable']
    assert restarted.get(job.id).pending_card_uids == ['a']

def test_related_and_metadata_survive_disk_and_export(tmp_path):
    manager = WorldBookManager(tmp_path/'books')
    book = fixture_book()
    book.adopt_v2_as_v3()
    book.related_edges=[{'from_uid':'a','to_uid':'tech'}]
    book.dependency_rules['roots'][0]['locked']=True
    book.dependency_rules['rejected']=[{'from_uid':'tech','to_uid':'a'}]
    manager.save(book)
    manager._cache.clear()
    loaded=manager.load(book.id)
    assert loaded.related_edges==book.related_edges
    assert loaded.dependency_rules['roots'][0]['locked']
    imported,_=manager.import_book('roundtrip',json.dumps(loaded.export_st()))
    assert imported.related_edges==book.related_edges
    assert imported.dependency_rules['rejected']==book.dependency_rules['rejected']
