"""LLM 自动构建依赖：候选检索、证据校验、任务持久化/取消/重试与失败语义。

本文件用 **stub LLM** 做确定性验证；真实 LLM 的端到端验证另见
`scripts/verify_worldbook_builder_llm.py`（需 `config/llm_config.json`）。
stub 只替代「模型这一层」，其余（分块、候选检索、校验、缓存、任务状态机）
都是被测的真实代码。
"""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from load_llm import LLMConnectError, LLMError
from world_book import DEFAULT_CATEGORIES, WorldBook, WorldBookEntry
from worldbook_builder import (
    ANALYSIS_BATCH, MAX_FANOUT, PROMPT_VERSION, REL_NONE, REL_RELATED, REL_REQUIRES,
    REL_UNSURE, AnalysisCache, DependencyBuildJob, DependencyJobStore, build_metadata_index,
    build_to_v3_rules, explicit_reference_pairs, extract_json, run_build, split_sections,
    validate_proposal,
)


def entry(uid, content, name="", character_id="", category_id="unclassified"):
    return WorldBookEntry(uid, content=content, name=name or uid,
                          character_id=character_id, category_id=category_id,
                          always_active=True)


def fixture_book():
    return WorldBook("bk", "构建测试书", [
        entry("world", "泰拉世界的基础设定，源石与天灾。", name="世界设定", category_id="worldview"),
        entry("a", "角色A：罗德岛干员。他使用源石技艺。", name="角色A", character_id="A",
              category_id="characters"),
        entry("b", "角色B：与角色A同属罗德岛。", name="角色B", character_id="B",
              category_id="characters"),
        entry("tech", "源石技艺的定义与规则。", name="源石技艺"),
    ], categories=copy.deepcopy(DEFAULT_CATEGORIES))


class StubLLM:
    """按请求内容分派的确定性 stub：只替代模型，不替代被测逻辑。"""

    def __init__(self, cards=None, judgments=None, fail_on=None, raw=None,
                 echo_pairs=False):
        self.cards = cards
        self.judgments = judgments if judgments is not None else []
        self.fail_on = fail_on or set()
        self.raw = raw
        # echo_pairs：对「被问到的每一对」都给出判定，用于验证缓存能整批命中
        self.echo_pairs = echo_pairs
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        prompt = messages[-1]["content"]
        if "分析下面这批" in prompt:
            if "cards" in self.fail_on:
                raise LLMConnectError("stub 分析阶段失败")
            if self.raw is not None:
                return {"type": "text", "content": self.raw}
            entry_lines = [line for line in prompt.splitlines() if line.startswith("<entry uid=")]
            uids = [line.split('uid="')[1].split('"')[0] for line in entry_lines]
            chunk_ids = [line.split('chunk_id="')[1].split('"')[0] for line in entry_lines]
            payload = {"cards": [{"uid": uid, "chunk_id": chunk_id,
                                  "summary": f"摘要-{uid}", "entities": [],
                                  "defined_concepts": [], "unexplained_concepts": [],
                                  "candidate_characters": [], "evidence": []}
                                 for uid, chunk_id in zip(uids, chunk_ids)]}
            if self.cards:
                payload["cards"].extend(self.cards)
            return {"type": "text", "content": json.dumps(payload, ensure_ascii=False)}
        if "判断下列" in prompt:
            if "judgments" in self.fail_on:
                raise LLMConnectError("stub 判定阶段失败")
            if self.echo_pairs:
                echoed = []
                for line in prompt.splitlines():
                    if line.startswith("<pair from="):
                        parts = dict(part.split("=", 1) for part in
                                     line.strip("<>").split(" ") if "=" in part)
                        echoed.append({"from_uid": parts.get("from", "").strip('"'),
                                       "to_uid": parts.get("to", "").strip('"'),
                                       "relation": REL_RELATED, "confidence": 0.6,
                                       "evidence": "与角色A同属罗德岛"})
                return {"type": "text", "content": json.dumps({"judgments": echoed},
                                                              ensure_ascii=False)}
            return {"type": "text", "content": json.dumps(
                {"judgments": self.judgments}, ensure_ascii=False)}
        raise AssertionError("未预期的请求")


@pytest.fixture
def cache(tmp_path):
    return AnalysisCache(tmp_path / "analysis")


@pytest.fixture
def store(tmp_path):
    return DependencyJobStore(tmp_path / "jobs")


def build(book, llm, cache, store, max_calls=400):
    job = store.create(book.id, "hash-1", "stub-model")
    return run_build(job, book, llm, model="stub-model", cache=cache, max_calls=max_calls)


def test_metadata_index_uses_deterministic_classification_without_llm():
    book = fixture_book()
    metadata = build_metadata_index(book.entries)
    assert set(metadata["entries"]) == {"world", "a", "b", "tech"}
    assert metadata["entries"]["a"]["character_id"] == "A"
    assert metadata["entries"]["a"]["content_hash"] != metadata["entries"]["b"]["content_hash"]
    assert "角色A" in metadata["entries"]["a"]["aliases"]


def test_explicit_references_are_found_and_not_dropped():
    book = fixture_book()
    metadata = build_metadata_index(book.entries)
    pairs = explicit_reference_pairs(metadata, {e.uid: e for e in book.entries})
    found = {(p["from_uid"], p["to_uid"]) for p in pairs}
    # 角色B 正文明确提到「角色A」
    assert ("b", "a") in found
    assert all(p["kind"] == "explicit" for p in pairs)


def test_single_character_mentions_do_not_create_reference_noise():
    book = WorldBook("bk", "噪声", [entry("x", "甲。"), entry("y", "乙。")])
    metadata = build_metadata_index(book.entries)
    assert explicit_reference_pairs(metadata, {e.uid: e for e in book.entries}) == []


def test_split_sections_chunks_long_entries():
    short = "很短的一段"
    assert split_sections(short) == [short]
    long_text = "\n".join(f"## 章节{i}\n" + "内容" * 400 for i in range(6))
    parts = split_sections(long_text)
    assert len(parts) > 1
    assert "".join(parts) == long_text


@pytest.mark.parametrize("text,expected", [
    ('{"a":1}', {"a": 1}),
    ('```json\n{"a":1}\n```', {"a": 1}),
    ('好的，结果如下：{"a":1} 完毕', {"a": 1}),
    ('[1,2]', [1, 2]),
    ('完全不是 JSON', None),
])
def test_extract_json_tolerates_wrappers(text, expected):
    assert extract_json(text) == expected


def test_full_build_produces_validated_proposal(cache, store):
    book = fixture_book()
    llm = StubLLM(judgments=[
        {"from_uid": "a", "to_uid": "tech", "relation": REL_REQUIRES, "confidence": 0.9,
         "reason": "A 使用源石技艺", "evidence": "他使用源石技艺"},
        {"from_uid": "b", "to_uid": "a", "relation": REL_RELATED, "confidence": 0.7,
         "reason": "同组织", "evidence": "与角色A同属罗德岛"},
    ])
    job = build(book, llm, cache, store)
    assert job.stage == "done"
    assert job.error is None
    result = job.result
    assert result["stats"]["requires"] == 1
    assert result["stats"]["related"] == 1
    assert all(r["origin"] == "llm" and r["model"] == "stub-model" for r in result["records"])
    assert all(r["prompt_version"] == PROMPT_VERSION for r in result["records"])
    assert all(r["source_content_hash"] and r["target_content_hash"] for r in result["records"])
    assert result["expansion_probe"]["requires_edges"] == 1


def test_unsupported_evidence_is_downgraded_not_accepted(cache, store):
    """证据无法在原文定位 → 降级为待复核，绝不当作已确认关系。"""
    book = fixture_book()
    llm = StubLLM(judgments=[
        {"from_uid": "a", "to_uid": "tech", "relation": REL_REQUIRES, "confidence": 0.95,
         "reason": "编造的", "evidence": "这句话在原文里根本不存在"},
    ])
    job = build(book, llm, cache, store)
    record = job.result["records"][0]
    assert record["relation"] == REL_UNSURE
    assert record["review_status"] == "needs_review"
    assert job.result["accepted"] == []
    assert any(i["code"] == "evidence_not_found" for i in job.result["issues"])


def test_validation_rejects_unknown_uid_self_loop_and_duplicates():
    book = fixture_book()
    metadata = build_metadata_index(book.entries)
    proposal = validate_proposal(book, {}, [
        {"from_uid": "a", "to_uid": "missing", "relation": REL_REQUIRES},
        {"from_uid": "a", "to_uid": "a", "relation": REL_REQUIRES},
        {"from_uid": "a", "to_uid": "tech", "relation": "bogus"},
        {"from_uid": "a", "to_uid": "tech", "relation": REL_REQUIRES,
         "evidence": "他使用源石技艺"},
        {"from_uid": "a", "to_uid": "tech", "relation": REL_REQUIRES,
         "evidence": "他使用源石技艺"},
    ], metadata, "m")
    codes = [i["code"] for i in proposal["issues"]]
    assert "unknown_uid" in codes and "self_loop" in codes
    assert "bad_relation" in codes and "duplicate_pair" in codes
    assert len(proposal["accepted"]) == 1


def test_validation_reports_cycles_and_high_fanout():
    book = fixture_book()
    metadata = build_metadata_index(book.entries)
    cyclic = [
        {"from_uid": "a", "to_uid": "b", "relation": REL_REQUIRES, "evidence": "与角色A同属罗德岛"},
        {"from_uid": "b", "to_uid": "a", "relation": REL_REQUIRES, "evidence": "他使用源石技艺"},
    ]
    proposal = validate_proposal(book, {}, cyclic, metadata, "m")
    assert proposal["cycles"] and any(i["code"] == "cycle" for i in proposal["issues"])

    # 扇出保护需要足够多的**不同**目标：同一对重复会被去重成 1 条边。
    many = WorldBook("big", "扇出", [entry("world", "这是全书的总体概述与基础说明。")] +
                     [entry(f"n{i}", f"内容{i}") for i in range(MAX_FANOUT + 5)],
                     categories=copy.deepcopy(DEFAULT_CATEGORIES))
    fan = [{"from_uid": "world", "to_uid": f"n{i}", "relation": REL_REQUIRES,
            "evidence": "总体概述与基础说明"}
           for i in range(MAX_FANOUT + 5)]
    proposal = validate_proposal(many, {}, fan, build_metadata_index(many.entries), "m")
    assert proposal["fanout"]["world"] == MAX_FANOUT + 5
    assert any(i["code"] == "high_fanout" for i in proposal["issues"])


def test_confidence_only_orders_and_never_claims_accuracy(cache, store):
    book = fixture_book()
    llm = StubLLM(judgments=[
        {"from_uid": "a", "to_uid": "tech", "relation": REL_REQUIRES, "confidence": "0.4",
         "evidence": "他使用源石技艺"},
        {"from_uid": "b", "to_uid": "a", "relation": REL_RELATED, "confidence": "not-a-number",
         "evidence": "与角色A同属罗德岛"},
    ])
    job = build(book, llm, cache, store)
    values = {r["from_uid"]: r["confidence"] for r in job.result["records"]}
    assert values["a"] == 0.4 and values["b"] == 0.0
    assert "accuracy" not in json.dumps(job.result).lower()


def test_analysis_cards_are_cached_by_content_model_and_prompt_version(cache, store):
    book = fixture_book()
    first = StubLLM(judgments=[])
    build(book, first, cache, store)
    card_calls_first = len([c for c in first.calls if "分析下面这批" in c[-1]["content"]])

    second = StubLLM(judgments=[])
    build(book, second, cache, store)
    card_calls_second = len([c for c in second.calls if "分析下面这批" in c[-1]["content"]])
    assert card_calls_first > 0 and card_calls_second == 0

    # 正文变了 → 缓存失效，重新分析
    book.entries[0].content = "完全不同的正文"
    third = StubLLM(judgments=[])
    build(book, third, cache, store)
    assert len([c for c in third.calls if "分析下面这批" in c[-1]["content"]]) > 0


def test_judgment_cache_key_binds_target_hash(cache):
    assert cache.judgment_key("h1", "h2", "m") == cache.judgment_key("h1", "h2", "m")
    assert cache.judgment_key("h1", "h2", "m") != cache.judgment_key("h1", "h3", "m")
    assert cache.judgment_key("h1", "h2", "m") != cache.judgment_key("h1", "h2", "other")
    assert cache.card_key("c", "m") != cache.card_key("c", "m2")


def test_judgment_cache_is_actually_used_at_runtime(cache, store):
    """判定也走缓存：第二次构建不再为同一批候选对调用模型。"""
    book = fixture_book()
    first = StubLLM(echo_pairs=True)
    build(book, first, cache, store)
    judge_calls_first = len([c for c in first.calls if "判断下列" in c[-1]["content"]])
    assert judge_calls_first > 0

    second = StubLLM(echo_pairs=True)
    job = build(book, second, cache, store)
    judge_calls_second = len([c for c in second.calls if "判断下列" in c[-1]["content"]])
    assert judge_calls_second == 0, "判定阶段没有命中缓存，重复付费"
    # 命中缓存的结果仍然进入最终建议，而不是变成空结果
    assert job.stage == "done"
    assert len(job.judgments) > 0
    assert job.result["stats"]["records"] == len(job.judgments)

    # 目标条目正文变了 → 相关判定失效，必须重新问模型
    book.entries[1].content = "角色A：正文完全改写了。"
    third = StubLLM(echo_pairs=True)
    build(book, third, cache, store)
    assert len([c for c in third.calls if "判断下列" in c[-1]["content"]]) > 0


def test_llm_failure_is_structured_and_never_fake_success(cache, store):
    book = fixture_book()
    llm = StubLLM(fail_on={"cards"})
    job = build(book, llm, cache, store)
    # 分析阶段全失败 → 候选为空 → 仍然正常收尾，但批次失败被如实记录
    assert job.failed_batches and all(b["stage"] == "cards" for b in job.failed_batches)
    assert all(b["code"] == "connect" for b in job.failed_batches)

    book2 = fixture_book()
    job2 = store.create(book2.id, "h", "stub-model")

    class Exploding:
        def chat(self, messages, **kwargs):
            raise LLMConnectError("模型不可用")

    from worldbook_builder import run_build as rb
    def boom(*args, **kwargs):
        raise LLMConnectError("模型不可用")
    import worldbook_builder as module
    original = module.build_metadata_index
    module.build_metadata_index = boom
    try:
        result = rb(job2, book2, Exploding(), model="m", cache=cache)
    finally:
        module.build_metadata_index = original
    assert result.stage == "failed"
    assert result.error["code"] == "connect"
    assert result.result is None


def test_job_cancel_is_cooperative_and_persisted(cache, store, tmp_path):
    book = fixture_book()
    job = store.create(book.id, "h", "m")
    job.cancelled = True
    llm = StubLLM(judgments=[])
    run_build(job, book, llm, model="m", cache=cache)
    assert job.stage == "cancelled"
    reloaded = DependencyBuildJob.load(job.id, tmp_path / "jobs")
    assert reloaded is not None and reloaded.cancelled is True
    assert llm.calls == []


def test_job_persists_progress_and_survives_reload(cache, store, tmp_path):
    book = fixture_book()
    llm = StubLLM(judgments=[{"from_uid": "a", "to_uid": "tech",
                              "relation": REL_REQUIRES, "evidence": "他使用源石技艺"}])
    job = build(book, llm, cache, store)
    reloaded = DependencyBuildJob.load(job.id, tmp_path / "jobs")
    assert reloaded is not None
    assert reloaded.stage == "done"
    assert reloaded.result["stats"]["requires"] == 1
    assert reloaded.cards and reloaded.judgments
    assert reloaded.input_hash == "hash-1"
    assert store.list_for_book(book.id)[0]["job_id"] == job.id


def test_failed_batches_can_be_retried_without_rerunning_cards(cache, store):
    book = fixture_book()
    failing = StubLLM(judgments=[], fail_on={"judgments"})
    job = build(book, failing, cache, store)
    assert any(b["stage"] == "adjudication" for b in job.failed_batches)

    retry_llm = StubLLM(judgments=[{"from_uid": "a", "to_uid": "tech",
                                    "relation": REL_REQUIRES, "evidence": "他使用源石技艺"}])
    pairs = []
    for batch in job.failed_batches:
        for a, b in batch.get("pairs", []):
            pairs.append({"from_uid": a, "to_uid": b})
    job.cancelled = False
    job.failed_batches = []
    run_build(job, book, retry_llm, model="stub-model", cache=cache, only_pairs=pairs)
    card_calls = len([c for c in retry_llm.calls if "分析下面这批" in c[-1]["content"]])
    assert card_calls == 0                      # 分析卡走缓存，不重跑
    assert job.result["stats"]["requires"] == 1


def test_call_budget_is_enforced(cache, store):
    book = fixture_book()
    job = store.create(book.id, "h", "m")
    llm = StubLLM(judgments=[])
    result = run_build(job, book, llm, model="m", cache=cache, max_calls=0)
    assert result.stage == "failed"
    assert result.error["code"] == "budget_exceeded"


def test_build_to_v3_rules_separates_requires_from_related_and_respects_human_edits():
    book = fixture_book()
    proposal = {"accepted": [
        {"from_uid": "a", "to_uid": "tech", "relation": REL_REQUIRES},
        {"from_uid": "b", "to_uid": "a", "relation": REL_RELATED},
        {"from_uid": "world", "to_uid": "b", "relation": REL_NONE},
    ]}
    rules = build_to_v3_rules(book, proposal)
    requires = {(e["from_uid"], e["to_uid"]) for e in rules["requires_edges"]}
    related = {(e["from_uid"], e["to_uid"]) for e in rules["related_edges"]}
    assert requires == {("a", "tech")}
    assert related == {("b", "a")}

    # 人工锁定的起点与已拒绝的建议必须受保护
    protected = build_to_v3_rules(book, proposal, existing_rules={
        "roots": [{"entry_uid": "world", "locked": True}],
        "rejected": [{"from_uid": "a", "to_uid": "tech"}],
    })
    assert {(e["from_uid"], e["to_uid"]) for e in protected["requires_edges"]} == set()
    assert any(r["entry_uid"] == "world" for r in protected["roots"])


def test_character_entries_become_roster_roots_not_global_sources():
    """基础概述提到某角色不应引入整组：只有带 character_id 的条目成为 roster 起点。"""
    book = fixture_book()
    rules = build_to_v3_rules(book, {"accepted": []})
    by_uid = {r["entry_uid"]: r for r in rules["roots"]}
    assert by_uid["a"]["activation"] == "roster_any"
    assert by_uid["a"]["character_ids"] == ["A"]
    assert by_uid["world"]["activation"] == "always"
    assert "tech" not in by_uid          # 未分类条目不会被自动设为全局源
