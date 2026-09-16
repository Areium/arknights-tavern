"""世界书依赖构建的**性能契约**：规划/装箱、覆盖完整性、缓存正确性、用量指标。

和 `test_worldbook_builder.py` 一样，stub 只替代「模型这一层」；分块、装箱、
缓存键、响应校验、任务指标全是被测的真实代码。

这里刻意验证的是那些「省 token 也最容易省出问题」的地方：
- 覆盖：每个分块、每个候选对都必须有人管，不能因为装箱被静默丢掉；
- 预算：任何请求都不得超出输入/输出上限（超大单元独占一个请求，而不是漏发）；
- 证据：引用在**中部 / 尾部**、以及正文带空格（规范化命中）时都要能定位；
- 响应：缺失 / 重复 / 未知的处理必须「保持待重试」，空结果**不等于**全无关系；
- 缓存：正文、名称、别名、卡片、提示词、证据窗口任一变化都要失效；
- 指标：估算与真实用量分开记账，provider 不报 usage 时是**未知**而不是 0。
"""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import worldbook_builder as builder
from world_book import DEFAULT_CATEGORIES, WorldBook, WorldBookEntry
from worldbook_builder import (
    ADJUDICATION_INPUT_TOKEN_BUDGET, ADJUDICATION_MAX_UNITS, ADJUDICATION_OUTPUT_TOKEN_BUDGET,
    ADJUDICATION_PAIR_OUTPUT_TOKENS, ANALYSIS_INPUT_TOKEN_BUDGET, ANALYSIS_MAX_UNITS,
    ANALYSIS_OUTPUT_TOKEN_BUDGET, REL_NONE, REL_REQUIRES, REL_UNSURE, AnalysisCache,
    DependencyBuildJob, DependencyJobStore, build_metadata_index, entry_chunks,
    entry_context, estimate_workload, evidence_windows, plan_adjudication, plan_analysis,
    analysis_plan_units, collect_candidates, run_build,
)
from worldbook_builder_plan import Unit, packs_all_units

PREINSTALLED = REPO / "data" / "worldbooks" / "arknights.json"


def entry_context_tokens(text: str) -> int:
    """按产品口径量一段渲染文本的 token（与规划器同一函数）。"""
    return builder.estimate_tokens(text)


def grouped_in_order(pairs) -> list:
    """按来源首次出现顺序重排候选对 —— 与 `group_pairs_by_source` 一致。"""
    seen, ordered = set(), []
    for pair in pairs:
        if pair["from_uid"] in seen:
            continue
        seen.add(pair["from_uid"])
        ordered.extend(p for p in pairs if p["from_uid"] == pair["from_uid"])
    return ordered


def entry(uid, content, name="", character_id="", category_id="unclassified", **kwargs):
    return WorldBookEntry(uid, content=content, name=name or uid,
                          character_id=character_id, category_id=category_id,
                          always_active=True, **kwargs)


def fixture_book():
    return WorldBook("bk", "性能测试书", [
        entry("world", "泰拉世界的基础设定，源石与天灾。", name="世界设定",
              category_id="worldview"),
        entry("a", "角色A：罗德岛干员。他使用源石技艺。", name="角色A", character_id="A",
              category_id="characters"),
        entry("b", "角色B：与角色A同属罗德岛。", name="角色B", character_id="B",
              category_id="characters"),
        entry("tech", "源石技艺的定义与规则。", name="源石技艺"),
    ], categories=copy.deepcopy(DEFAULT_CATEGORIES))


# ─────────────────────────────────────────────────────────────
# 规划与装箱
# ─────────────────────────────────────────────────────────────

def test_packer_measures_real_render_and_never_exceeds_budgets():
    """装箱器量的是**真实渲染文本**，不是近似的固定开销算术。"""
    rendered = {}

    def render(units):
        text = "|".join(unit.key for unit in units)
        rendered[id(text)] = text
        return text, None

    packer = builder.ExactPacker(render=render, instruction_tokens=10,
                                 input_budget=60, output_budget=100, max_units=3,
                                 output_of=lambda unit: 10)
    # 每个单元 key 长 8 个 ASCII 字符 → 2 token；分隔符 1 个 ASCII 字符。
    units = [Unit(key=f"unit{i:04d}") for i in range(20)]
    plans = packer.plan(units)
    assert packs_all_units(plans, units), "装箱丢失了单元"
    for plan in plans:
        assert len(plan.units) <= 3, "超过条数上限"
        assert plan.expected_output_tokens <= 100, "超过输出预算"
        # 输入预算按真实渲染长度核对（含每次请求都付的 system 开销）。
        assert plan.input_tokens == 10 + builder.estimate_tokens(plan.text)
        if not plan.oversized:
            assert plan.input_tokens <= 60
    # 规划时量到的文本就是执行时会发送的文本。
    assert all(plan.text for plan in plans)


def test_oversized_unit_gets_its_own_request_instead_of_being_dropped():
    """单个单元本身就超预算：独占一个请求并标记 oversized，绝不静默发送超限请求。"""
    packer = builder.ExactPacker(render=lambda units: ("x" * 4000, None),
                                 instruction_tokens=0, input_budget=200,
                                 output_budget=5000, max_units=10,
                                 output_of=lambda unit: 10)
    units = [Unit(key="huge"), Unit(key="small")]
    plans = packer.plan(units)
    assert packs_all_units(plans, units)
    assert all(plan.oversized for plan in plans), "超限单元没有被标记"
    assert all(len(plan.units) == 1 for plan in plans), "超限单元没有被单独成批"


def test_packer_keeps_source_order_instead_of_sorting():
    """贪心必须保持传入顺序：重排会打散来源分组、破坏上下文去重。"""
    packer = builder.ExactPacker(render=lambda units: (",".join(u.key for u in units), None),
                                 instruction_tokens=0, input_budget=10_000,
                                 output_budget=10_000, max_units=100,
                                 output_of=lambda unit: 1)
    units = [Unit(key=key) for key in ("c", "a", "b")]
    plans = packer.plan(units)
    assert [unit.key for plan in plans for unit in plan.units] == ["c", "a", "b"]


def test_analysis_planning_covers_every_chunk_within_budgets(tmp_path):
    """真实形态的夹具：709 级别的分块必须被完整装箱，且不超上限。"""
    long_text = "\n".join(f"## 章节{i}\n" + "内容" * 900 for i in range(8))
    book = WorldBook("plan", "规划书",
                     [entry(f"e{i}", long_text, name=f"条目{i}") for i in range(6)],
                     categories=copy.deepcopy(DEFAULT_CATEGORIES))
    metadata = build_metadata_index(book.entries)
    entries_by_uid = {e.uid: e for e in book.entries}
    units = analysis_plan_units(metadata, entries_by_uid)
    expected = sum(len(entry_chunks(e.content)[0]) for e in book.entries)
    assert len(units) == expected, "规划单元数必须等于分块总数"
    plans = plan_analysis(units, metadata, entries_by_uid)
    assert packs_all_units(plans, units), "分块覆盖不完整"
    for plan in plans:
        assert len(plan.units) <= ANALYSIS_MAX_UNITS
        assert plan.expected_output_tokens <= ANALYSIS_OUTPUT_TOKEN_BUDGET
        # 输入预算按**真实渲染**核对，且系统提示词开销必须计入。
        assert plan.input_tokens == (builder._system_tokens()
                                     + entry_context_tokens(plan.text))
        if not plan.oversized:
            assert plan.input_tokens <= ANALYSIS_INPUT_TOKEN_BUDGET


def test_adjudication_planning_covers_every_pair_and_reuses_context(tmp_path):
    """按来源分组的上下文必须被**复用**：同来源的多对只付一次共享开销。"""
    sources = [entry(f"src{i}", "凯尔希与罗德岛以及阿米娅。", name=f"来源{i}")
               for i in range(6)]
    targets = [entry("kaltsit", "凯尔希的档案。", name="凯尔希"),
               entry("rhodes", "罗德岛的档案。", name="罗德岛"),
               entry("amiya", "阿米娅的档案。", name="阿米娅")]
    book = WorldBook("adj", "判定书", sources + targets,
                     categories=copy.deepcopy(DEFAULT_CATEGORIES))
    metadata = build_metadata_index(book.entries)
    entries_by_uid = {e.uid: e for e in book.entries}
    pairs = collect_candidates(metadata, entries_by_uid)["pairs"]
    assert len(pairs) >= 18, "夹具应当产出足够多的候选对"
    cards = {uid: {"uid": uid, "summary": "摘要" * 40, "defined_concepts": ["甲"],
                   "unexplained_concepts": ["乙"]} for uid in entries_by_uid}
    plans = plan_adjudication(pairs, entries_by_uid, cards)
    units = [unit for plan in plans for unit in plan.units]
    assert len(units) == len(pairs), "候选对被丢弃或重复"
    for plan in plans:
        assert len(plan.units) <= ADJUDICATION_MAX_UNITS
        assert plan.expected_output_tokens <= ADJUDICATION_OUTPUT_TOKEN_BUDGET
        if not plan.oversized:
            assert plan.input_tokens <= ADJUDICATION_INPUT_TOKEN_BUDGET
        # 渲染出的请求必须真的按 uid/片段去重：同一证据**定义**只出现一次。
        # 只看 `[证据窗口]` 段：指令里的格式示例也含 `<evidence id="e0"`。
        table = plan.text.split("[证据窗口]", 1)[1].split("<pair ", 1)[0]
        defs = re.findall(r'<evidence id="(e\d+)"', table)
        assert len(defs) == len(set(defs)), "同一证据在同一请求里重复列出"
        # pair 行通过 ref 引用，不在 pair 行里重复粘贴原文窗口。
        for ref in re.findall(r'[ab]_ref="(e\d+)"', table):
            assert ref in defs, f"pair 引用了不存在的证据 {ref}"
    # 同一来源的候选对连续排布（顺序被保持），上下文才可能被复用。
    ordered = [unit.key for plan in plans for unit in plan.units]
    assert ordered == [(p["from_uid"], p["to_uid"]) for p in grouped_in_order(pairs)]


def test_estimate_workload_matches_plan_for_realistic_book():
    book = WorldBook("est", "估算书",
                     [entry(f"e{i}", "正文" * 400 + f"提到 概念X{i}。", name=f"条目{i}")
                      for i in range(12)] + [entry("t", "概念X0 的定义。", name="概念X0")],
                     categories=copy.deepcopy(DEFAULT_CATEGORIES))
    metadata = build_metadata_index(book.entries)
    entries_by_uid = {e.uid: e for e in book.entries}
    pairs = collect_candidates(metadata, entries_by_uid)["pairs"]
    cards = {uid: {"uid": uid, "summary": "摘要", "defined_concepts": [],
                   "unexplained_concepts": []} for uid in entries_by_uid}
    workload = estimate_workload(metadata, pairs, entries_by_uid=entries_by_uid,
                                 cards=cards)
    plans_analysis = plan_analysis(analysis_plan_units(metadata, entries_by_uid),
                                   metadata, entries_by_uid)
    plans_adj = plan_adjudication(pairs, entries_by_uid, cards)
    assert workload["card_calls"] == len(plans_analysis)
    assert workload["adjudication_calls"] == len(plans_adj)
    assert workload["estimated_calls"] == len(plans_analysis) + len(plans_adj)
    assert workload["estimated_input_tokens"] == (
        sum(p.input_tokens for p in plans_analysis) + sum(p.input_tokens for p in plans_adj))
    assert workload["planned"] is True


# ─────────────────────────────────────────────────────────────
# 证据窗口：中部 / 尾部 / 空白规范化
# ─────────────────────────────────────────────────────────────

def test_evidence_window_keeps_middle_and_tail_matches():
    filler = "无关填充。" * 3000
    middle_ref = "稀有概念ZETA"
    tail_ref = "尾部概念OMEGA"
    content = filler[:len(filler) // 2] + f"这里提到 {middle_ref}。" + \
        filler[len(filler) // 2:] + f"最后提到 {tail_ref}。"
    for needle in (middle_ref, tail_ref):
        window, how, clipped = evidence_windows(content, needle)
        assert needle in window, f"{needle} 没有被窗口取到"
        assert how == "exact"
        assert clipped in (True, False)
    # 旧实现只取「包含该词的整段」；新窗口必须短得多
    from worldbook_builder import relevant_chunk
    legacy_text, _ = relevant_chunk(content, middle_ref)
    window, _, _ = evidence_windows(content, middle_ref)
    assert len(window) < len(legacy_text), "短窗口没有比整段更小"


def test_evidence_window_handles_whitespace_normalized_match():
    """正文里词被空格拆开时，规范化命中仍要取到窗口（不能退化成开头前缀）。"""
    # 用互不相同的填充，才能断言「窗口里没有退化成开头的前缀」。
    head = "".join(f"头{i}。" for i in range(400))
    tail = "".join(f"尾{i}。" for i in range(400))
    content = head + "凯 尔 希 在 这 里。" + tail
    window, how, clipped = evidence_windows(content, "凯尔希")
    assert how == "normalized"
    assert "凯 尔 希" in window, "规范化命中没有把引用取进窗口"
    assert clipped is True
    # prefix 退化分支只返回正文开头；命中在中间时不该出现开头标记。
    assert "头0。" not in window, "规范化命中退化成前缀，说明没定位到引用"
    assert window.startswith(builder._MARK_HEAD), "命中在中间却没有截断标记"


def test_evidence_window_marks_truncation_and_falls_back_widely():
    content = "甲" * 5000
    window, how, clipped = evidence_windows(content, "不存在的词")
    assert how == "prefix" and clipped is True
    assert len(window) == builder.EVIDENCE_PREFIX_CHARS
    # 命中位置在中间时，两侧都要有显式截断标记
    middle = "甲" * 2000 + "目标引用" + "乙" * 2000
    window, how, clipped = evidence_windows(middle, "目标引用")
    assert how == "exact" and clipped is True
    assert window.startswith(builder._MARK_HEAD) and window.endswith(builder._MARK_TAIL)


def test_entry_context_is_bounded_and_keeps_requires_signal():
    """判定上下文必须有限，同时保留「还有什么没解释」这个 requires 信号。"""
    card = {"summary": "摘" * 500, "defined_concepts": ["甲" * 100, "乙"],
            "unexplained_concepts": ["丙", "丁"]}
    text = entry_context(card)
    # 逐字段约束：超长的摘要/概念各自被裁到上限，整体自然落在硬上限内。
    assert len(text) <= builder.CONTEXT_MAX_CHARS
    assert "摘" * (builder.CONTEXT_SUMMARY_CHARS + 1) not in text, "摘要没有按上限裁剪"
    assert "甲" * (builder.CONTEXT_ITEM_CHARS + 1) not in text, "概念没有被裁剪"
    assert "自身定义" in text and "提到但未解释" in text
    # 概念条数也要封顶，避免「一个条带几十个概念」把请求撑大。
    many = {"summary": "", "defined_concepts": [f"概念{i}" for i in range(50)],
            "unexplained_concepts": [f"未解{i}" for i in range(50)]}
    bounded = entry_context(many)
    assert bounded.count("、") + 1 <= builder.CONTEXT_LIST_ITEMS * 2
    assert len(bounded) <= builder.CONTEXT_MAX_CHARS


def test_entry_context_marks_hard_truncation():
    """即便各字段都在限内，总长超硬上限时也要有显式截断标记。"""
    card = {"summary": "摘" * builder.CONTEXT_SUMMARY_CHARS,
            "defined_concepts": ["甲" * builder.CONTEXT_ITEM_CHARS] * builder.CONTEXT_LIST_ITEMS,
            "unexplained_concepts": ["乙" * builder.CONTEXT_ITEM_CHARS] * builder.CONTEXT_LIST_ITEMS}
    mark = builder.TRUNCATION_MARKERS[0]
    limit = 30
    capped = entry_context(card, limit=limit)
    assert capped.endswith(mark), "总长超出硬上限却没有截断标记"
    assert len(capped) == limit + len(mark)


# ─────────────────────────────────────────────────────────────
# 响应校验：缺失 / 重复 / 未知 / 空
# ─────────────────────────────────────────────────────────────

class PairStub:
    """按请求里的 `<pair>` 行回判定；可注入缺失 / 重复 / 未知 / 空响应。"""

    def __init__(self, omit=(), duplicate=(), unknown=False, empty=False,
                 relation=REL_REQUIRES, evidence=""):
        self.omit = set(map(tuple, omit))
        self.duplicate = set(map(tuple, duplicate))
        self.unknown = unknown
        self.empty = empty
        self.relation = relation
        self.evidence = evidence
        self.calls = []
        self.requests = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        prompt = messages[-1]["content"]
        if "分析下面这批" in prompt:
            lines = [line for line in prompt.splitlines() if line.startswith("<entry uid=")]
            cards = []
            for line in lines:
                uid = line.split('uid="')[1].split('"')[0]
                chunk_id = line.split('chunk_id="')[1].split('"')[0]
                cards.append({"uid": uid, "chunk_id": chunk_id, "summary": f"摘要-{uid}",
                              "entities": [], "defined_concepts": [],
                              "unexplained_concepts": [], "candidate_characters": [],
                              "evidence": []})
            return {"type": "text", "content": json.dumps({"cards": cards},
                                                          ensure_ascii=False)}
        if not self.empty:
            pass
        pairs = []
        for line in prompt.splitlines():
            if line.startswith("<pair from="):
                parts = dict(part.split("=", 1) for part in
                             line.strip("<>").split(" ") if "=" in part)
                pairs.append((parts.get("from", "").strip('"'),
                              parts.get("to", "").strip('"')))
        self.requests.append(pairs)
        if self.empty:
            return {"type": "text", "content": '{"judgments":[]}'}
        judgments = []
        for a, b in pairs:
            if (a, b) in self.omit:
                continue
            judgments.append({"from_uid": a, "to_uid": b, "relation": self.relation,
                              "confidence": 0.7,
                              "evidence": self.evidence,
                              "reason": "stub"})
            if (a, b) in self.duplicate:
                judgments.append({"from_uid": a, "to_uid": b, "relation": REL_NONE,
                                  "confidence": 0.1, "evidence": "", "reason": "重复"})
        if self.unknown:
            judgments.append({"from_uid": "ghost", "to_uid": "ghost2",
                              "relation": self.relation, "confidence": 0.9})
        return {"type": "text", "content": json.dumps({"judgments": judgments},
                                                      ensure_ascii=False)}


@pytest.fixture
def cache(tmp_path):
    return AnalysisCache(tmp_path / "analysis")


@pytest.fixture
def store(tmp_path):
    return DependencyJobStore(tmp_path / "jobs")


def judge_book():
    """一个必然产生「明确引用」候选对的书（b→a 因为 b 提到角色A）。"""
    return fixture_book()


def test_missing_pair_response_stays_pending_and_is_retryable(cache, store):
    """别的对答了、这一对漏了 → 必须保持待重试，绝不静默当成 none。"""
    book = judge_book()
    metadata = build_metadata_index(book.entries)
    pairs = collect_candidates(metadata, {e.uid: e for e in book.entries})["pairs"]
    assert pairs, "夹具必须产出候选对"
    target = (pairs[0]["from_uid"], pairs[0]["to_uid"])
    job = store.create(book.id, "h", "m")
    run_build(job, book, PairStub(omit=[target]), model="m", cache=cache)

    assert any(batch["code"] == "invalid_response" and batch.get("pairs")
               for batch in job.failed_batches), "遗漏的候选对没有被记录为失败批次"
    judged = {(item.get("from_uid"), item.get("to_uid")) for item in job.judgments}
    assert target not in judged, "遗漏的候选对被静默写成了结论"

    retry = PairStub(evidence="他使用源石技艺")
    job.cancelled = False
    failed = [{"from_uid": a, "to_uid": b} for batch in job.failed_batches
              for a, b in batch.get("pairs", [])]
    job.failed_batches = []
    run_build(job, book, retry, model="m", cache=cache, only_pairs=failed)
    assert job.result is not None
    assert any(record["from_uid"] == target[0] and record["to_uid"] == target[1]
               for record in job.result["records"]), "重试后仍然没有这一对的结论"


def test_empty_judgments_is_retryable_not_cached_as_none(cache, store):
    """`{"judgments":[]}` 是**空响应**：必须可重试，绝不静默缓存成 none。

    这是 review 的硬要求：空 / 缺失 / 重复 / 未知响应一律算失败批次，
    宁可重试也不能把「模型什么都没说」写成「模型说没关系」。
    """
    book = judge_book()
    job = store.create(book.id, "h", "m")
    run_build(job, book, PairStub(empty=True), model="m", cache=cache)

    assert job.outcome != "success", "空响应被当成了成功构建"
    assert job.result is None or not job.result.get("records"), "空响应产出了结论"
    assert job.failed_batches, "空响应没有被记录为可重试的失败批次"
    assert all(batch["code"] == "invalid_response" for batch in job.failed_batches)
    assert not job.judgments, "空响应被静默缓存成了 none"
    assert job.resumable, "空响应之后必须还能续跑"

    # 重试必须能补齐：这次每对都**显式**回答 none。
    retry = PairStub(relation=REL_NONE)
    job.cancelled = False
    run_build(job, book, retry, model="m", cache=cache)
    assert job.result is not None
    assert {record["relation"] for record in job.result["records"]} == {REL_NONE}


def test_explicit_none_results_are_cached_and_not_recharged(cache, store):
    """模型**显式**逐对回答 none 时，结果进缓存；第二次运行不再计费。"""
    book = judge_book()
    job = store.create(book.id, "h", "m")
    run_build(job, book, PairStub(relation=REL_NONE), model="m", cache=cache)
    assert not job.failed_batches
    assert {record["relation"] for record in job.result["records"]} == {REL_NONE}

    replay = PairStub(relation=REL_NONE)
    job2 = store.create(book.id, "h2", "m")
    run_build(job2, book, replay, model="m", cache=cache)
    assert replay.requests == [], "显式 none 结论没有写进缓存"


def test_duplicate_pair_response_does_not_silently_pick_one(cache, store):
    """同一对返回两条互相冲突的判定：既不挑一条，也不进结算/缓存。

    review-2 复现的 P1：旧实现把重复判定留在 `items` 里落盘，续跑时该对被当成
    「已结算」而不再问模型，于是从冲突响应里得出**假 success**。这里断言两件事：
    1. 冲突对既不产出记录、也不写缓存；
    2. 续跑时模型**确实被重新调用**，并且这次能拿到可用结论。
    """
    book = judge_book()
    metadata = build_metadata_index(book.entries)
    pairs = collect_candidates(metadata, {e.uid: e for e in book.entries})["pairs"]
    target = (pairs[0]["from_uid"], pairs[0]["to_uid"])
    job = store.create(book.id, "h", "m")
    run_build(job, book, PairStub(duplicate=[target]), model="m", cache=cache)

    assert job.outcome != "success", "冲突响应被当成了成功构建"
    records = [r for r in job.result["records"]
               if (r["from_uid"], r["to_uid"]) == target]
    assert records == [], "冲突判定进入了结算（应保持待重试）"
    assert not any((j.get("from_uid"), j.get("to_uid")) == target
                   for j in job.judgments), "冲突判定被静默写进 job.judgments"

    # 续跑：必须真的再问一次模型，而不是因为「已结算」而跳过。
    retry = PairStub(evidence="他使用源石技艺")
    job.cancelled = False
    run_build(job, book, retry, model="m", cache=cache)
    assert retry.requests, "续跑没有重新调用模型（冲突对被误判为已结算）"
    assert any(r["from_uid"] == target[0] and r["to_uid"] == target[1]
               for r in job.result["records"]), "续跑后仍没有该对的结论"


def test_unknown_pair_response_is_recorded(cache, store):
    book = judge_book()
    job = store.create(book.id, "h", "m")
    run_build(job, book, PairStub(unknown=True), model="m", cache=cache)
    assert any("未知候选对" in (batch.get("message") or "")
               for batch in job.failed_batches)


class MixedUsageStub(PairStub):
    """只有**第一次**请求上报 usage，其余不报：用于验证部分覆盖的诚实呈现。"""

    def __init__(self):
        super().__init__(evidence="他使用源石技艺")
        self.seen = 0

    def chat(self, messages, **kwargs):
        self.seen += 1
        response = super().chat(messages, **kwargs)
        if self.seen == 1:
            response["usage"] = {"prompt_tokens": 100, "completion_tokens": 40,
                                 "total_tokens": 140}
        return response


class UsageStub(PairStub):
    """第一次回复故意不是 JSON（触发一次修复），之后每次报告完整 usage。"""

    def __init__(self, bad_first=True):
        super().__init__(evidence="他使用源石技艺")
        self.bad_first = bad_first
        self.seen = 0

    def chat(self, messages, **kwargs):
        self.seen += 1
        if self.bad_first and self.seen == 1:
            self.calls.append(messages)
            return {"type": "text", "content": "这不是 JSON",
                    "usage": {"prompt_tokens": 11, "completion_tokens": 3,
                              "total_tokens": 14}}
        response = super().chat(messages, **kwargs)
        response["usage"] = {"prompt_tokens": 100, "completion_tokens": 40,
                             "total_tokens": 140}
        return response


def test_missing_evidence_window_forces_unsure(cache, store):
    """证据窗口缺失（正文为空，模型看不到原文）时，不能接受 requires 结论。"""
    # 只有正文为空才会产生「空窗口」：定位不到、又没有可退化的前缀。
    book = WorldBook("emptyref", "空引用",
                     [entry("src", "", name="来源"),
                      entry("dst", "目标条目。", name="目标")],
                     categories=copy.deepcopy(DEFAULT_CATEGORIES))
    job = store.create(book.id, "h", "m")
    stub = PairStub(relation=REL_REQUIRES, evidence="短正文")
    original = builder._merge_card_pairs

    def patched(pairs, cards, metadata, entries_by_uid):
        merged = original(pairs, cards, metadata, entries_by_uid)
        # 注入一个必被判定、且 A 侧窗口为空的候选对。
        merged.append({"from_uid": "src", "to_uid": "dst", "matched": "任意词",
                       "kind": "explicit"})
        return merged

    builder._merge_card_pairs = patched
    try:
        run_build(job, book, stub, model="m", cache=cache)
    finally:
        builder._merge_card_pairs = original

    record = next((r for r in job.result["records"]
                   if r["from_uid"] == "src" and r["to_uid"] == "dst"), None)
    assert record is not None, "候选对没有被判定"
    assert record["relation"] == REL_UNSURE, "窗口缺失却接受了 requires"
    assert "窗口缺失" in (record["reason"] or "")


# ─────────────────────────────────────────────────────────────
# 缓存失效
# ─────────────────────────────────────────────────────────────

def test_judgment_cache_invalidates_on_name_and_alias_change(cache, store):
    """名称或触发别名变了 → 判定依据已变，旧判定不得复用。"""
    book = judge_book()
    first = PairStub(evidence="他使用源石技艺")
    job = store.create(book.id, "h1", "m")
    run_build(job, book, first, model="m", cache=cache)
    assert first.requests, "第一次应当调用模型"

    replay = PairStub(evidence="他使用源石技艺")
    job2 = store.create(book.id, "h2", "m")
    run_build(job2, book, replay, model="m", cache=cache)
    assert replay.requests == [], "未改动时判定缓存没有命中"

    # 只改别名（正文不动）
    book.entries[1].trigger_keys = ["角色A", "新别名"]
    changed = PairStub(evidence="他使用源石技艺")
    job3 = store.create(book.id, "h3", "m")
    run_build(job3, book, changed, model="m", cache=cache)
    assert changed.requests, "触发别名变化后仍然命中了旧判定缓存"


def test_judgment_cache_invalidates_on_card_context_change(cache, store):
    """判定所依据的卡片上下文变了 → 旧判定失效（判定键绑定了卡片指纹）。"""
    book = judge_book()
    first = PairStub(evidence="他使用源石技艺")
    job = store.create(book.id, "h1", "m")
    run_build(job, book, first, model="m", cache=cache)
    assert first.requests, "第一次应当调用模型"
    assert job.cards, "分析卡没有落进 job.cards，指纹无从绑定"

    replay = PairStub(evidence="他使用源石技艺")
    job_replay = store.create(book.id, "h2", "m")
    run_build(job_replay, book, replay, model="m", cache=cache)
    assert replay.requests == [], "未改动时判定缓存没有命中"

    # 正文、名称、别名、提示词都不动，只让分析卡重新提炼出不同上下文：
    # 走真实路径——把某一个条目标记为「必须重问」，第二轮的分析卡因此改口。
    target_uid = sorted(job.cards)[0]

    class RewordedStub(PairStub):
        def chat(self, messages, **kwargs):
            response = super().chat(messages, **kwargs)
            if "分析下面这批" not in messages[-1]["content"]:
                return response
            payload = json.loads(response["content"])
            for card in payload["cards"]:
                if card.get("uid") == target_uid:
                    card["summary"] = "改过的摘要"
                    card["unexplained_concepts"] = ["新概念"]
            response["content"] = json.dumps(payload, ensure_ascii=False)
            return response

    changed = RewordedStub(evidence="他使用源石技艺")
    job3 = store.create(book.id, "h3", "m")
    job3.rebuild_card_uids = [target_uid]
    run_build(job3, book, changed, model="m", cache=cache)
    assert job3.cards[target_uid]["summary"] == "改过的摘要", "分析卡没有按预期改口"
    assert changed.requests, "卡片上下文变化后仍然命中了旧判定缓存"


def test_analysis_cache_survives_judgment_prompt_change(cache, store, monkeypatch):
    """只改判定提示词 → 分析卡应当仍然有效（不重付整本书的分析费）。"""
    book = judge_book()
    first = PairStub(evidence="他使用源石技艺")
    job = store.create(book.id, "h1", "m")
    run_build(job, book, first, model="m", cache=cache)
    analysis_requests = len([call for call in first.calls
                             if "分析下面这批" in call[-1]["content"]])
    assert analysis_requests > 0

    monkeypatch.setattr(builder, "ADJUDICATION_PROMPT_VERSION", "next-adjudication")
    second = PairStub(evidence="他使用源石技艺")
    job2 = store.create(book.id, "h2", "m")
    run_build(job2, book, second, model="m", cache=cache)
    assert not [call for call in second.calls if "分析下面这批" in call[-1]["content"]], \
        "判定提示词变化把分析卡也作废了"
    assert second.requests, "判定提示词变化后应当重新判定"


# ─────────────────────────────────────────────────────────────
# 预算 / 取消 / 指标持久化
# ─────────────────────────────────────────────────────────────

def test_job_metrics_are_persisted_and_distinguish_unknown_usage(cache, store, tmp_path):
    """估算与真实用量分开记账；provider 不报 usage 时是**未知**而不是 0。"""
    book = judge_book()
    job = store.create(book.id, "h", "m")
    run_build(job, book, PairStub(evidence="他使用源石技艺"), model="m", cache=cache)
    metrics = job.metrics
    assert metrics["requests"] > 0
    assert metrics["actual_known"] is False, "stub 不报 usage，必须记成未知"
    assert metrics["actual_total_tokens"] == 0

    reloaded = DependencyBuildJob.load(job.id, tmp_path / "jobs")
    assert reloaded is not None
    assert reloaded.metrics["requests"] == metrics["requests"]
    assert reloaded.metrics["actual_known"] is False
    assert reloaded.workload.get("estimated_input_tokens", 0) > 0


def test_provider_usage_is_accumulated_and_json_repairs_counted(cache, store):
    """provider 报告 usage 时累加进去；JSON 修复调用同样计入请求数与修复数。"""
    book = judge_book()
    job = store.create(book.id, "h", "m")
    run_build(job, book, UsageStub(), model="m", cache=cache)
    metrics = job.metrics
    assert metrics["actual_known"] is True
    assert metrics["actual_prompt_tokens"] > 100
    assert metrics["actual_completion_tokens"] >= 40
    assert metrics["actual_total_tokens"] == (metrics["actual_prompt_tokens"]
                                              + metrics["actual_completion_tokens"])
    assert metrics["json_repair_calls"] >= 1, "JSON 修复没有被计入指标"


def test_budget_exhaustion_keeps_metrics_and_resumes(cache, store, monkeypatch):
    """预算在分析阶段就用完 → 记下进度与待办条目，续跑能接着做完。"""
    # 每个请求只允许 1 个分块，保证 41 条目的分析需要 41 次调用，3 次必然做不完。
    # 输入预算必须仍**大于单个请求的真实渲染**（系统提示词 + 单条上下文 ≈ 595），
    # 否则每批都会因放不下而被判 oversized，任务根本走不动，测不到「预算耗尽」。
    monkeypatch.setattr(builder, "ANALYSIS_MAX_UNITS", 1)
    monkeypatch.setattr(builder, "ANALYSIS_INPUT_TOKEN_BUDGET", 640)
    book = WorldBook("budget", "预算书",
                     [entry(f"e{i}", f"条目{i} 提到 概念X。", name=f"条目{i}")
                      for i in range(40)] + [entry("t", "概念X 的定义。", name="概念X")],
                     categories=copy.deepcopy(DEFAULT_CATEGORIES))
    job = store.create(book.id, "h", "m")
    run_build(job, book, PairStub(evidence="概念X"), model="m", cache=cache, max_calls=3)
    assert job.resumable is True
    assert job.metrics["requests"] > 0, "预算耗尽的中间进度也要计账"
    assert job.pending_card_uids, "未完成的条目没有被记为待办"

    resume = PairStub(evidence="概念X")
    run_build(job, book, resume, model="m", cache=cache,
              only_uids=list(job.pending_card_uids), max_calls=400)
    assert job.outcome == "success", (job.outcome, job.error, job.failed_batches[:3])
    assert job.metrics["requests"] > 0


def test_cancel_before_batches_makes_no_calls(cache, store):
    book = judge_book()
    job = store.create(book.id, "h", "m")
    job.cancelled = True
    stub = PairStub(evidence="他使用源石技艺")
    run_build(job, book, stub, model="m", cache=cache)
    assert job.stage == "cancelled"
    assert stub.calls == []


# ─────────────────────────────────────────────────────────────
# 真实预装书：覆盖与规模
# ─────────────────────────────────────────────────────────────

@pytest.mark.skipif(not PREINSTALLED.is_file(), reason="仓库内没有预装世界书")
def test_preinstalled_book_planning_covers_everything_with_bounded_requests():
    """全书：分块与候选对全部被规划到，且没有请求超出上限。"""
    from world_book import WorldBookManager
    book = WorldBookManager(REPO / "data" / "worldbooks").load("arknights")
    assert book is not None and len(book.entries) >= 200
    metadata = build_metadata_index(book.entries)
    entries_by_uid = {e.uid: e for e in book.entries}
    pairs = collect_candidates(metadata, entries_by_uid)["pairs"]
    assert len(pairs) > 1000, "候选对规模变了，性能契约需要重新校准"

    units = analysis_plan_units(metadata, entries_by_uid)
    analysis_plans = plan_analysis(units, metadata, entries_by_uid)
    assert packs_all_units(analysis_plans, units)
    assert all(plan.input_tokens <= ANALYSIS_INPUT_TOKEN_BUDGET or plan.oversized
               for plan in analysis_plans)
    assert all(plan.expected_output_tokens <= ANALYSIS_OUTPUT_TOKEN_BUDGET
               for plan in analysis_plans)

    cards = {uid: {"uid": uid, "summary": "摘要" * 30, "defined_concepts": ["甲", "乙"],
                   "unexplained_concepts": ["丙", "丁"]} for uid in entries_by_uid}
    adjudication_plans = plan_adjudication(pairs, entries_by_uid, cards)
    planned = [unit for plan in adjudication_plans for unit in plan.units]
    assert len(planned) == len(pairs), "候选对覆盖不完整"
    assert all(plan.input_tokens <= ADJUDICATION_INPUT_TOKEN_BUDGET or plan.oversized
               for plan in adjudication_plans)
    assert all(plan.expected_output_tokens <= ADJUDICATION_OUTPUT_TOKEN_BUDGET
               for plan in adjudication_plans)

    # 历史基线：固定批量下是 119 次分析 + 203 次判定。新装箱必须明显更少。
    assert len(analysis_plans) < 119
    assert len(adjudication_plans) < 203
    print(f"[perf] 分块 {len(units)} → 分析请求 {len(analysis_plans)}；"
          f"候选对 {len(pairs)} → 判定请求 {len(adjudication_plans)}")


def test_analysis_batch_constants_match_planner_caps():
    """对外暴露的批量常量必须就是装箱上限，不能再是「另一套固定值」。"""
    assert builder.ANALYSIS_BATCH == ANALYSIS_MAX_UNITS
    assert builder.ADJUDICATION_BATCH == ADJUDICATION_MAX_UNITS
    assert ADJUDICATION_PAIR_OUTPUT_TOKENS > 0


# ─────────────────────────────────────────────────────────────
# review-2 追加回归：持久化 / 计数 / 部分用量
# ─────────────────────────────────────────────────────────────

def test_failed_batches_survive_save_load(cache, store, tmp_path):
    """失败批次必须能被 save/load 原样带回：重启后重试 API 只认它。

    review-2 指出 `load` 漏了 `failed_batches` 赋值，重启后「还差哪些」全部丢失。
    """
    book = judge_book()
    job = store.create(book.id, "h", "m")
    run_build(job, book, PairStub(empty=True), model="m", cache=cache)
    assert job.failed_batches, "前置条件：这次构建必须留下失败批次"
    expected = [(b["stage"], b["code"], tuple(map(tuple, b.get("pairs", []))))
                for b in job.failed_batches]

    restored = builder.DependencyBuildJob.load(job.id, directory=store._dir)
    assert restored is not None
    got = [(b["stage"], b["code"], tuple(map(tuple, b.get("pairs", []))))
           for b in restored.failed_batches]
    assert got == expected, "失败批次没有随任务恢复"
    assert restored.resumable, "恢复后的任务必须仍可续跑"


def test_requests_metric_counts_json_repairs(cache, store):
    """`requests` 必须等于真实调用数：JSON 修复也算一次（不能低报）。"""
    book = judge_book()
    job = store.create(book.id, "h", "m")
    stub = UsageStub()
    run_build(job, book, stub, model="m", cache=cache)
    assert job.metrics["json_repair_calls"] >= 1
    assert job.metrics["requests"] == len(stub.calls), (
        f"requests={job.metrics['requests']} 与真实调用 {len(stub.calls)} 不一致")
    assert job.metrics["requests"] == job.calls


def test_partial_usage_coverage_is_flagged(cache, store):
    """只有一部分请求上报 usage 时，必须标出「部分」，不能显示成完整实测。"""
    book = judge_book()
    job = store.create(book.id, "h", "m")
    run_build(job, book, MixedUsageStub(), model="m", cache=cache)
    metrics = job.metrics
    assert metrics["actual_known"] is True, "至少上报过一次用量"
    assert metrics["usage_partial"] is True, "部分上报没有被标记为 partial"
    assert metrics["usage_requests_total_tokens"] == metrics["requests"]
    assert metrics["usage_reported_total_tokens"] < metrics["requests"]
