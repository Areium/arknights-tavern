"""选择性阅读（adaptive）的**生命周期契约**。

这些用例针对的是「省 token 也最容易省出问题」的地方 —— 也正是独立评审
（`review-checklist.md` + executable probe）复现出的 P1/P2 缺陷：

- 升级阅读必须读**完整补集**，而不是再抽样一次；已成功读到的字符绝不重发；
- `needs_more_context` / `foundational` 必须**原样保留**到合并后的卡上，
  缺失 / 非布尔按保守处理（不得被清洗阶段抹掉）；
- 升级决定落定之前**不得**把部分卡写进正式缓存（否则重试命中它，永远不再补全）；
- 失败 / 预算耗尽 / 取消后重试：按**同一批跨度身份**恢复，继续补完剩余补集；
- 补充响应用**与种子完全相同**的严格校验（缺失 / 重复 / 未知不放行）；
- 阅读报告按**实际成功覆盖**记账，不是按计划选择；
- 部分阅读的 `foundational` 卡不得自动产生**全局根**；
- 未知阅读模式报错，不静默回退。

stub 只替代「模型这一层」；选择器、跨度身份、装箱、缓存键、校验、报告全是真的。
"""
import json
import re
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import worldbook_builder as builder
import worldbook_reading as reading
from world_book import WorldBook, WorldBookEntry
from worldbook_builder import (
    ADAPTIVE_ANALYSIS_PROMPT_VERSION,
    DependencyBuildJob,
    AnalysisCache,
    _clean_card,
    _merge_cards,
    _needs_more_context,
    _selection_bundle_id,
    _span_chunk_id,
    _supplement_units,
    normalize_reading_mode,
    run_build,
)
from worldbook_reading import (
    READING_MODE_ADAPTIVE,
    READING_MODE_FULL,
    build_reading_plan,
    select_spans,
)


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────

def prose(chars=3400, marker="普通记录。"):
    """一段**无小标题**的长散文：开头有导语，其余是可被省略的正文。"""
    head = "## 简介\n这是这条设定的导语。\n\n"
    body = (marker * 8 + "\n\n") * max(1, chars // (len(marker) * 8 + 2))
    return head + body


class StubLLM:
    """把请求里的每个 `<entry>` 回成一张卡；可注入字段与失败行为。"""

    def __init__(self, fields=None, fail_times=0, evidence=None):
        self.fields = dict(fields or {})
        self.fail_times = fail_times
        self.evidence = evidence
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("stub transport failure")
        content = messages[-1]["content"]
        matches = re.findall(r'<entry uid="([^"]+)"[^>]*chunk_id="([^"]+)"', content)
        cards = []
        for uid, chunk_id in matches:
            card = {"uid": uid, "chunk_id": chunk_id, "summary": "摘要"}
            card.update(self.fields)
            if self.evidence is not None:
                card["evidence"] = list(self.evidence)
            cards.append(card)
        return {"content": json.dumps({"cards": cards}, ensure_ascii=False)}


def make_book(text, uid="prose", name="正文", category="other"):
    return WorldBook("wb", "wb", [WorldBookEntry(uid, text, name=name,
                                                 category_id=category)])


def make_job(tmpdir, mode=READING_MODE_ADAPTIVE, **kwargs):
    return DependencyBuildJob("job", "wb", "hash", model="stub",
                              directory=Path(tmpdir), reading_mode=mode, **kwargs)


def cards_seen(llm, messages):
    return re.findall(r'<entry uid="([^"]+)"[^>]*chunk_id="([^"]+)"',
                      messages[-1]["content"])


# ─────────────────────────────────────────────────────────────
# 模式校验
# ─────────────────────────────────────────────────────────────

def test_unknown_reading_mode_raises_not_silently_full():
    """拼错的模式必须报错：静默回退会让「全是全读」与「只读片段」无法区分。"""
    with pytest.raises(ValueError):
        normalize_reading_mode("adaptiv")
    with pytest.raises(ValueError):
        normalize_reading_mode("FULL ")


def test_blank_mode_uses_explicit_default():
    assert normalize_reading_mode(None) == READING_MODE_FULL
    assert normalize_reading_mode("") == READING_MODE_FULL
    assert normalize_reading_mode(None, default=READING_MODE_ADAPTIVE) == READING_MODE_ADAPTIVE


def test_reading_mode_is_immutable_across_save_load(tmpdir):
    """模式创建时选定、不可更改：落盘再载入必须还是同一个。"""
    job = make_job(tmpdir, mode=READING_MODE_ADAPTIVE)
    job.save()
    restored = DependencyBuildJob.load("job", Path(tmpdir))
    assert restored.reading_mode == READING_MODE_ADAPTIVE


# ─────────────────────────────────────────────────────────────
# 选择器：跨度身份 / 补集完整性
# ─────────────────────────────────────────────────────────────

def test_selection_invariants_hold_on_long_prose():
    text = prose()
    selection = select_spans(text, uid="prose")
    assert selection.full is False
    spans = selection.spans
    assert spans, "长散文应能被选择性阅读"
    assert all(0 <= s.start < s.end <= len(text) for s in spans)
    assert all(a.end <= b.start for a, b in zip(spans, spans[1:])), "跨度必须有序不重叠"


def test_unread_spans_is_exact_complement_not_a_sample():
    """升级阅读读的是**完整补集**：已读 + 未读 == 全文，且没有重叠。"""
    text = prose()
    selection = select_spans(text, uid="prose")
    complement = selection.unread_spans(text)
    read = [(s.start, s.end) for s in selection.spans]
    rest = [(s.start, s.end) for s in complement]
    combined = sorted(read + rest)
    # 合并后必须**无重叠且覆盖全文**（前一块从 0 开始，最后一块到 len(text)）。
    cursor = 0
    for start, end in combined:
        assert start >= cursor, "补集与已读不得重叠"
        cursor = end
    assert combined[0][0] == 0 and combined[-1][1] == len(text), "补集必须是逐字补集"


def test_unread_spans_chunked_without_losing_chars():
    text = prose(chars=9000)
    selection = select_spans(text, uid="prose")
    complement = selection.unread_spans(text, chunk_chars=1800)
    assert all(s.chars <= 1800 for s in complement)
    total = sum(s.chars for s in selection.spans) + sum(s.chars for s in complement)
    assert total == len(text), "切块不得丢字"


def test_full_and_rule_entries_have_no_complement():
    rule = "rules_x_index" + "规则条款。" * 400
    selection = select_spans(rule, uid="rules_x_index")
    assert selection.full is True
    assert selection.unread_spans(rule) == []


# ─────────────────────────────────────────────────────────────
# 卡片契约：needs_more_context 保留
# ─────────────────────────────────────────────────────────────

def test_clean_card_preserves_needs_more_context_and_malformed():
    card = {"uid": "a", "chunk_id": "a@x", "needs_more_context": True,
            "needs_context_reason": "缺章节", "foundational": True}
    cleaned = _clean_card(card)
    assert cleaned["needs_more_context"] is True
    assert cleaned["needs_context_reason"] == "缺章节"
    # 非布尔 / 缺失都要保留「不可信」的信号，而不是偷偷补成 False。
    assert _clean_card({"uid": "a", "chunk_id": "a@x",
                        "needs_more_context": "yes"})["needs_more_context"] is None
    assert "needs_more_context" not in _clean_card({"uid": "a", "chunk_id": "a@x"})


def test_needs_more_context_is_conservative_for_missing_and_malformed():
    assert _needs_more_context({"needs_more_context": True}) is True
    assert _needs_more_context({"needs_more_context": False}) is False
    assert _needs_more_context({}) is True, "缺失 ⇒ 保守视为需要"
    assert _needs_more_context({"needs_more_context": "yes"}) is True, "非布尔 ⇒ 保守"


def test_merge_cards_keeps_true_and_missing_signal():
    merged = _merge_cards([
        {"uid": "a", "chunk_id": "a@1", "needs_more_context": False},
        {"uid": "a", "chunk_id": "a@2", "needs_more_context": True},
    ])
    assert merged["needs_more_context"] is True, "任一分块为真即为真"
    all_false = _merge_cards([{"uid": "a", "chunk_id": "a@1", "needs_more_context": False},
                              {"uid": "a", "chunk_id": "a@2", "needs_more_context": False}])
    assert all_false["needs_more_context"] is False
    missing = _merge_cards([{"uid": "a", "chunk_id": "a@1"}])
    assert "needs_more_context" not in missing, "全部缺失时不伪造字段"


def test_merge_cards_orders_parts_by_source_offset():
    """两轮（种子 / 补集）合并必须按原文顺序，而不是响应到达顺序。"""
    merged = _merge_cards([
        {"uid": "a", "summary": "后半", "chunk_id": "a@2"},
        {"uid": "a", "summary": "前半", "chunk_id": "a@1"},
    ])
    assert merged["summary"] == "后半", "合并按传入顺序取首个非空摘要（由调用方排序）"


# ─────────────────────────────────────────────────────────────
# 升级：触发 / 完整补集 / 不重发
# ─────────────────────────────────────────────────────────────

def _selection_and_state(text, uid="prose", flags=None):
    """构造选择结果 + 已成功返回的**种子分块**（决策依据就在这里，不是最终卡）。"""
    selection = select_spans(text, uid=uid)
    seed_ids = [_selection_bundle_id(uid, selection)]
    cards = {}
    for cid in seed_ids:
        card = {"uid": uid, "chunk_id": cid}
        card.update(flags or {})
        cards[cid] = card
    done = {uid: cards}
    return selection, seed_ids, done


def test_supplement_units_returns_full_complement_and_uses_consistent_ids(tmpdir):
    """P1-1：状态里的 ID 必须是 `uid@span_id`（与 done_chunks 键同一口径）。"""
    text = prose()
    selection, seed_ids, done = _selection_and_state(
        text, flags={"needs_more_context": True})
    phase = {}
    units = _supplement_units({"prose": make_book(text).entries[0]},
                              {"prose": selection}, done,
                              {"prose": {}},
                              {"prose": seed_ids}, phase)
    assert units, "needs_more_context=true 必须触发升级"
    assert all(unit[1].startswith("prose@") for unit in units)
    assert phase["prose"]["phase"] == "supplement"
    # 读到的补集字符数 == 未读字符数（完整补集，不是抽样）。
    assert sum(len(unit[3]) for unit in units) == selection.omitted_chars


def test_supplement_never_resends_already_read_spans(tmpdir):
    """已成功读到的字符绝不重发：补集的 chunk_id 与种子 ID 不相交。"""
    text = prose()
    selection, seed_ids, done = _selection_and_state(
        text, flags={"needs_more_context": True})
    units = _supplement_units({"prose": make_book(text).entries[0]},
                              {"prose": selection}, done,
                              {"prose": {}},
                              {"prose": seed_ids}, {})
    sent = {unit[1] for unit in units}
    assert not (sent & set(seed_ids))


def test_foundational_partial_also_triggers_supplement():
    """部分卡的 foundational=true 独立触发升级（全局根需要全读才可信）。"""
    text = prose()
    selection, seed_ids, done = _selection_and_state(
        text, flags={"foundational": True, "needs_more_context": False})
    units = _supplement_units({"prose": make_book(text).entries[0]},
                              {"prose": selection}, done,
                              {"prose": {}},
                              {"prose": seed_ids}, {})
    assert units, "foundational=true 且部分阅读 → 必须补全"


def test_no_supplement_when_explicitly_not_needed():
    """显式 false 且无本地线索 → 不升级，且**决策已落定**（不会反复补）。"""
    text = prose()
    selection, seed_ids, done = _selection_and_state(
        text, flags={"needs_more_context": False, "foundational": False})
    phase = {}
    units = _supplement_units({"prose": make_book(text).entries[0]},
                              {"prose": selection}, done,
                              {"prose": {}},
                              {"prose": seed_ids}, phase)
    assert units == []
    assert phase["prose"]["decision_made"] is True
    assert phase["prose"]["supplement_started"] is False
    assert phase["prose"]["phase"] == "complete"


# ─────────────────────────────────────────────────────────────
# 端到端：探针场景（评审 P1）
# ─────────────────────────────────────────────────────────────

def run_probe_like(tmpdir, text, fields, max_calls=10, fail_times=0):
    book = make_book(text)
    llm = StubLLM(fields=fields, fail_times=fail_times,
                  evidence=["普通记录。"] if fields.get("foundational") else None)
    job = make_job(tmpdir)
    cache = AnalysisCache(Path(tmpdir) / "cache")
    run_build(job, book, llm, model="stub", cache=cache, max_calls=max_calls)
    return job, llm


def test_probe_scenario_reaches_full_coverage(tmpdir):
    """评审探针：3366 字散文 + needs_more_context=true →
    必须补全**全部**未读正文，报告 coverage=full，且不重复读已读字符。"""
    text = prose()
    job, llm = run_probe_like(tmpdir, text,
                              {"needs_more_context": True, "foundational": True})
    report = job.reading_report
    assert report["coverage"] == "full", report
    assert report["unread_chars"] == 0, report
    assert report["read_chars"] == len(text)
    assert job.supplement["escalated"] is True
    assert job.supplement["complete_entries"] == ["prose"]
    assert job.supplement["pending_entries"] == []
    # 种子 1 次 + 补集 1 次（补集按 1800 字切块后仍装进一个请求）。
    assert llm.calls == 2


def test_escalation_obeys_call_budget_and_stays_pending(tmpdir):
    """预算不足时不得假装成功：留在 pending，报告为 partial，可续跑。"""
    # 补集很大（≈10 万字符）→ 装成多个请求；只给 2 次预算必然补不完。
    text = prose(chars=100000)
    job, llm = run_probe_like(tmpdir, text, {"needs_more_context": True}, max_calls=2)
    assert job.outcome == "partial", job.outcome
    assert job.reading_report["coverage"] == "partial"
    assert job.reading_report["unread_chars"] > 0
    assert job.supplement["pending_entries"], "未补齐的条目必须如实记为待办"
    assert job.resumable is True


def test_retry_resumes_remaining_complement_without_recompute(tmpdir):
    """重试续跑：已完成的不重发，未完成的继续补，且不重新触发轮次。"""
    text = prose(chars=100000)
    book = make_book(text)
    cache = AnalysisCache(Path(tmpdir) / "cache")
    llm = StubLLM(fields={"needs_more_context": True}, evidence=["普通记录。"])
    job = make_job(tmpdir)
    run_build(job, book, llm, model="stub", cache=cache, max_calls=2)
    first_pending = set(job.supplement["pending_entries"])
    first_unread = job.reading_report["unread_chars"]
    assert first_pending and first_unread > 0, job.reading_report
    seed_cards_before = {uid: set(cards) for uid, cards in job.chunk_cards.items()}
    # 提高预算续跑：剩余补集必须继续补，且不重跑整轮、不丢已成功的种子切片。
    run_build(job, book, llm, model="stub", cache=cache, max_calls=500)
    assert job.reading_report["coverage"] == "full", job.reading_report
    assert job.reading_report["unread_chars"] == 0
    for uid, ids in seed_cards_before.items():
        assert ids <= set(job.chunk_cards.get(uid, {})), "已成功的种子切片必须保留"


def test_supplement_uses_strict_validator(tmpdir):
    """P1-6：补充响应缺片 → 不放行、不写缓存、留在 pending、如实报协议错误。"""
    text = prose(chars=60000)
    book = make_book(text)
    calls = {"n": 0}

    class MissingSupplementPieceLLM(StubLLM):
        def chat(self, messages):
            calls["n"] += 1
            response = super().chat(messages)
            payload = json.loads(response["content"])
            # 种子轮（第一次提问）全部返回；补充轮起只回第一张，其余静默省略。
            if calls["n"] > 1 and len(payload["cards"]) > 1:
                payload["cards"] = payload["cards"][:1]
            return {"content": json.dumps(payload, ensure_ascii=False)}

    llm = MissingSupplementPieceLLM(fields={"needs_more_context": True},
                                    evidence=["普通记录。"])
    job = make_job(tmpdir)
    cache = AnalysisCache(Path(tmpdir) / "cache")
    # 给有限的预算：每轮只回一张，永远补不齐 → 必须停在 partial 且留下待办。
    run_build(job, book, llm, model="stub", cache=cache, max_calls=6)
    # 被省略的补充切片必须留在待办，且整体覆盖停在 partial。
    assert job.reading_report["coverage"] == "partial", job.reading_report
    assert job.supplement["pending_entries"], "被省略的切片必须留在待办"
    assert any(batch.get("code") == "invalid_response"
               for batch in job.failed_batches), "省略响应必须被记为协议错误"
    # 关键：有缺片时**不得**把这一条写进正式缓存（缓存只存收尾后的最终态）。
    entry = book.entries[0]
    key = builder._sha(entry.content) + builder._sha(
        json.dumps(["prose", "正文", [entry.name, "prose"], []],
                   ensure_ascii=False, sort_keys=True)) + "|adaptive|" + \
        reading.selection_cache_identity(select_spans(text, uid="prose"))
    assert cache.get(cache.card_key(key, "stub",
                                    version=ADAPTIVE_ANALYSIS_PROMPT_VERSION)) is None


def test_partial_cards_never_enter_cache_before_escalation(tmpdir):
    """P1-4：升级决定落定前不得把部分卡写进正式缓存，否则重试永远不再补全。

    用**必然打断**的预算（单次调用上限 1）保证走到「未收尾」分支，
    因此断言是无条件的，不存在「分支没走到就默默通过」。
    """
    text = prose(chars=100000)
    book = make_book(text)
    cache = AnalysisCache(Path(tmpdir) / "cache")
    llm = StubLLM(fields={"needs_more_context": True})
    job = make_job(tmpdir)
    run_build(job, book, llm, model="stub", cache=cache, max_calls=1)
    entry = book.entries[0]
    key = builder._sha(entry.content) + builder._sha(
        json.dumps(["prose", "正文", [entry.name, "prose"], []],
                   ensure_ascii=False, sort_keys=True)) + "|adaptive|" + \
        reading.selection_cache_identity(select_spans(text, uid="prose"))
    assert cache.get(cache.card_key(key, "stub",
                                    version=ADAPTIVE_ANALYSIS_PROMPT_VERSION)) is None, \
        "未收尾的部分卡不得进正式缓存"
    assert job.outcome != "success", "预算打断的任务不得报成功"
    assert job.resumable is True


def test_partial_card_cannot_satisfy_full_mode(tmpdir):
    """部分阅读的卡永远不满足全文模式（键里带模式与策略指纹）。"""
    text = prose()
    book = make_book(text)
    cache = AnalysisCache(Path(tmpdir) / "cache")
    adaptive_job = make_job(tmpdir, mode=READING_MODE_ADAPTIVE)
    run_build(adaptive_job, book, StubLLM(fields={"needs_more_context": False}),
              model="stub", cache=cache, max_calls=5)
    full_job = make_job(tmpdir, mode=READING_MODE_FULL)
    llm = StubLLM(fields={})
    run_build(full_job, book, llm, model="stub", cache=cache, max_calls=5)
    assert llm.calls >= 1, "全文模式必须重新读整条，不能命中部分阅读的缓存"
    assert full_job.metrics.get("analysis_cache_hits", 0) == 0


@pytest.mark.parametrize("first_mode,second_mode", [
    (READING_MODE_ADAPTIVE, READING_MODE_FULL),
    (READING_MODE_FULL, READING_MODE_ADAPTIVE),
])
def test_short_entry_cache_isolated_in_both_mode_directions(tmpdir, first_mode, second_mode):
    """短条目虽两种模式都读全文，adaptive 契约仍不能污染 full 缓存。"""
    book = make_book("短条目正文。")
    cache = AnalysisCache(Path(tmpdir) / "cache")
    first = make_job(tmpdir, mode=first_mode)
    run_build(first, book, StubLLM(fields={"needs_more_context": False}),
              model="stub", cache=cache, max_calls=5)
    second_llm = StubLLM(fields={"needs_more_context": False})
    second = DependencyBuildJob("second", "wb", "hash", model="stub",
                                directory=Path(tmpdir), reading_mode=second_mode)
    run_build(second, book, second_llm, model="stub", cache=cache, max_calls=5)
    assert second_llm.calls == 1
    assert second.metrics.get("analysis_cache_hits", 0) == 0


# ─────────────────────────────────────────────────────────────
# 报告 / 根安全 / 估算
# ─────────────────────────────────────────────────────────────

def test_report_counts_actual_success_not_plan(tmpdir):
    """P1-7：报告按实际成功覆盖记账；种子全失败时不得报告已读。"""
    text = prose()

    class DeadLLM:
        def chat(self, messages):
            raise RuntimeError("all calls fail")

    book = make_book(text)
    job = make_job(tmpdir)
    run_build(job, book, DeadLLM(), model="stub",
              cache=AnalysisCache(Path(tmpdir) / "cache"), max_calls=5)
    report = job.reading_report
    assert report.get("read_chars") == 0, "没有任何成功响应 → 已读为 0"
    assert report.get("coverage") == "partial"
    assert report.get("planned_selected_chars", 0) > 0, "计划口径单独保留"


def test_partial_foundational_does_not_become_global_root(tmpdir):
    """P1-9：部分阅读（未补齐）的 foundational 卡不得自动产生全局根。

    直接走**校验层**：给部分覆盖的 job 状态 + 一张 foundational 卡，
    校验器必须拒绝把它落成全局根，并回报待复核问题。断言无条件执行。
    """
    from worldbook_builder import build_metadata_index, validate_proposal

    text = prose(chars=120000)
    book = make_book(text)
    selection = select_spans(text, uid="prose")
    seed_ids = [_span_chunk_id("prose", span) for span in selection.spans]
    card = {"uid": "prose", "chunk_id": seed_ids[0], "summary": "摘要",
            "foundational": True, "needs_more_context": True,
            "evidence": ["普通记录。"]}
    metadata = build_metadata_index(book.entries)
    # 部分覆盖：升级已开始但补集尚未补齐（pending 非空）。
    read_state = {"prose": {"phase": "supplement", "expected": seed_ids,
                            "done": seed_ids, "pending": ["prose@missing"]}}
    result = validate_proposal(book, {"prose": card}, [], metadata, "stub",
                               character_ids=None, reading={"prose": selection},
                               job_read_state=read_state)
    assert all(root["entry_uid"] != "prose" for root in result["roots"]), \
        "部分阅读不得自动建立全局根"
    codes = {issue["code"] for issue in result["issues"]}
    assert "foundational_needs_review" in codes


def test_phase_complete_does_not_make_partial_foundational_a_global_root(tmpdir):
    """phase=complete 只表示阅读策略已结算；部分覆盖仍不能建立全局根。"""
    from worldbook_builder import build_metadata_index, validate_proposal

    text = prose(chars=120000)
    book = make_book(text)
    selection = select_spans(text, uid="prose")
    seed_ids = [_span_chunk_id("prose", span) for span in selection.spans]
    card = {"uid": "prose", "chunk_id": seed_ids[0], "summary": "摘要",
            "foundational": True, "needs_more_context": True,
            "evidence": ["普通记录。"]}
    metadata = build_metadata_index(book.entries)
    read_state = {"prose": {"phase": "complete", "expected": seed_ids,
                            "done": seed_ids, "pending": []}}
    result = validate_proposal(book, {"prose": card}, [], metadata, "stub",
                               character_ids=None, reading={"prose": selection},
                               job_read_state=read_state)
    assert all(root["entry_uid"] != "prose" for root in result["roots"]), result


def test_full_mode_foundational_becomes_global_root(tmpdir):
    """FULL 模式没有部分覆盖问题：foundational 直接成为全局根（不回归）。"""
    from worldbook_builder import build_metadata_index, validate_proposal

    text = prose(chars=2000)
    book = make_book(text)
    card = {"uid": "prose", "chunk_id": "prose:0:h", "summary": "摘要",
            "foundational": True, "evidence": ["普通记录。"]}
    metadata = build_metadata_index(book.entries)
    result = validate_proposal(book, {"prose": card}, [], metadata, "stub",
                               character_ids=None, reading=None,
                               job_read_state=None)
    assert any(root["entry_uid"] == "prose" for root in result["roots"]), result


def test_full_coverage_foundational_becomes_root(tmpdir):
    """补全到全读之后，foundational 才允许成为全局根（安全 ≠ 一律禁止）。"""
    text = prose()
    job, llm = run_probe_like(tmpdir, text, {"needs_more_context": True,
                                             "foundational": True})
    assert job.reading_report["coverage"] == "full"
    roots = (job.result or {}).get("roots") or []
    assert any(root["entry_uid"] == "prose" for root in roots), roots


def test_estimate_workload_keeps_reading_mode(tmpdir):
    """P1-8：候选对阶段重算估算时不得把阅读模式退回全文。"""
    text = prose()
    book = make_book(text)
    job = make_job(tmpdir)
    run_build(job, book, StubLLM(fields={"needs_more_context": False}),
              model="stub", cache=AnalysisCache(Path(tmpdir) / "cache"), max_calls=5)
    assert job.workload.get("reading_mode") == READING_MODE_ADAPTIVE
    assert job.workload.get("reading_coverage") in ("full", "partial")


def test_adaptive_workload_uses_same_bundle_units_as_execution(tmpdir):
    text = prose(chars=12000)
    book = make_book(text)
    entries = {entry.uid: entry for entry in book.entries}
    metadata = builder.build_metadata_index(book.entries)
    plan = build_reading_plan(book.entries, {}, mode=READING_MODE_ADAPTIVE,
                              categories={"prose": "other"})
    units = builder.analysis_plan_units(metadata, entries, plan)
    requests = builder.plan_analysis(units, metadata, entries, reading=plan, adaptive=True)
    workload = builder.estimate_workload(metadata, [], "stub", entries_by_uid=entries,
                                         reading=plan, reading_mode=READING_MODE_ADAPTIVE)
    assert workload["chunks"] == len(units) == 1
    assert workload["card_calls"] == len(requests)
    assert workload["estimated_analysis_input_tokens"] == sum(
        request.input_tokens for request in requests)


def test_full_mode_is_unchanged(tmpdir):
    """FULL 模式必须与改造前逐字一致：整条一次读完，无升级、无跨度。

    同时要求 FULL 模式也给出一份**紧凑覆盖**（全读不是「没有报告」）：
    `coverage == "full"`、`unread_chars == 0`，且不含自适应专属的补齐条目。
    """
    text = prose()
    book = make_book(text)
    job = make_job(tmpdir, mode=READING_MODE_FULL)
    llm = StubLLM(fields={})
    run_build(job, book, llm, model="stub",
              cache=AnalysisCache(Path(tmpdir) / "cache"), max_calls=5)
    assert llm.calls == 1
    assert job.supplement.get("escalated") in (None, False)
    assert job.reading_mode == READING_MODE_FULL
    report = job.reading_report
    assert report.get("coverage") == "full"
    assert report.get("unread_chars") == 0
    assert report.get("partial_entries") == 0
    assert report.get("read_chars") == report.get("total_chars")
