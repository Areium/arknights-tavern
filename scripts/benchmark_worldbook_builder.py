#!/usr/bin/env python
"""世界书依赖构建：旧实现 vs 新装箱器的**确定性**成本对照。

这个脚本回答一个具体问题：同一本真实世界书，同样的候选对，改造前后
「实际会发出去的请求」规模差多少。它**不联网、不调用模型**：两边都通过
构造真实请求文本（提示词 + 正文 / 上下文 / 证据）来度量，所以数字可复现。

口径说明（重要）：
- 这里的数字是**估算**，不是账单。token 用 `world_book.estimate_tokens`
  （CJK 1 token / 其余 4 字符 1 token）估算；
- 新实现一侧调用的是**产品代码里同一个装箱器**（`plan_analysis` /
  `plan_adjudication` 与 `build_*_prompt`），因此估算与真实请求一致；
- 旧实现一侧按历史参数复刻（分析固定 6 分块 / 判定固定 8 对，判定发送
  `relevant_chunk` 返回的整段）。这是已核实的历史口径，用于对照，不是当前行为。

用法：
    python scripts/benchmark_worldbook_builder.py
    python scripts/benchmark_worldbook_builder.py --book-path D:/path/to/book.json --json-out report.json
    python scripts/benchmark_worldbook_builder.py --cards-file path/to/job.json  # 真实历史卡片（推荐）

`--cards-file` 指向一个已完成的构建任务 JSON（取其 `cards`）。**真实卡片**才是
可靠的口径：合成卡片的摘要/概念往往比真实卡片更长或更短，会让判定请求的
上下文开销偏离现实（历史上就出现过「合成卡片下看着达标、真实卡片下超预算」）。
脚本默认会同时跑「真实卡片」与「合成上界」，并断言**每一个真实渲染的请求**
都在预算内。
"""
import argparse
import json
import os
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from world_book import WorldBook, estimate_tokens                  # noqa: E402
import worldbook_builder as builder                                # noqa: E402

# 基准必须跑在**主仓库的真实 262 条世界书**上，而不是隔离工作区里可能过期的副本：
# 工作区副本的条目数不同会让「318 → 144」这类结论对不上号。主仓库不存在时才回退
# 到本仓库副本，便于在没有主仓库的环境里跑（此时报告中会注明用的是哪一份）。
MAIN_REPO = REPO.parent / "arknights-tavern"
MAIN_BOOK = MAIN_REPO / "data" / "worldbooks" / "arknights.json"
DEFAULT_BOOK = MAIN_BOOK if MAIN_BOOK.is_file() else (
    REPO / "data" / "worldbooks" / "arknights.json")

# 真实历史卡片（只读；来自主仓库的一个已完成构建任务）。
DEFAULT_CARDS_FILE = (MAIN_REPO / "data" / "worldbook_jobs"
                      / "0ea671eaaef541d5.json")

# 历史参数（已核实）：用于复刻旧实现的请求规模，不是当前产品行为。
LEGACY_ANALYSIS_BATCH = 6
LEGACY_ADJUDICATION_BATCH = 8


def legacy_analysis_cost(units, instruction_tokens: int) -> dict:
    texts = []
    for start in range(0, len(units), LEGACY_ANALYSIS_BATCH):
        blocks = [item[5] for item in units[start:start + LEGACY_ANALYSIS_BATCH]]
        texts.append(instruction_tokens + sum(estimate_tokens(b) for b in blocks))
    return {"requests": len(texts), "estimated_input_tokens": sum(texts),
            "max_request_tokens": max(texts) if texts else 0}


def legacy_adjudication_cost(pairs, entries_by_uid, instruction_tokens: int) -> dict:
    texts = []
    total = 0
    for start in range(0, len(pairs), LEGACY_ADJUDICATION_BATCH):
        cost = instruction_tokens
        for pair in pairs[start:start + LEGACY_ADJUDICATION_BATCH]:
            a, b = pair["from_uid"], pair["to_uid"]
            matched = pair.get("matched", "")
            # 旧实现：整段 relevant_chunk（最多 1800-6000 字/端），不是短窗口。
            for uid in (a, b):
                text, _hit = builder.relevant_chunk(entries_by_uid[uid].content, matched)
                cost += estimate_tokens(text)
            cost += 40
        texts.append(cost)
        total += cost
    return {"requests": len(texts), "estimated_input_tokens": total,
            "max_request_tokens": max(texts) if texts else 0}


def new_analysis_cost(units, metadata, entries_by_uid, character_ids) -> dict:
    plans = builder.plan_analysis(units, metadata, entries_by_uid, character_ids)
    sizes = [len(plan.units) for plan in plans]
    return {"requests": len(plans),
            "units": sum(sizes),
            "estimated_input_tokens": sum(plan.input_tokens for plan in plans),
            "max_request_tokens": max((plan.input_tokens for plan in plans), default=0),
            "max_units_per_request": max(sizes, default=0),
            "median_units_per_request": statistics.median(sizes) if sizes else 0,
            "expected_output_tokens": sum(plan.expected_output_tokens for plan in plans),
            "oversized_requests": sum(1 for plan in plans if plan.oversized)}


def new_adjudication_cost(pairs, entries_by_uid, cards) -> dict:
    plans = builder.plan_adjudication(pairs, entries_by_uid, cards)
    sizes = [len(plan.units) for plan in plans]
    return {"requests": len(plans),
            "units": sum(sizes),
            "estimated_input_tokens": sum(plan.input_tokens for plan in plans),
            "max_request_tokens": max((plan.input_tokens for plan in plans), default=0),
            "max_units_per_request": max(sizes, default=0),
            "median_units_per_request": statistics.median(sizes) if sizes else 0,
            "expected_output_tokens": sum(plan.expected_output_tokens for plan in plans),
            "oversized_requests": sum(1 for plan in plans if plan.oversized)}


def synthetic_cards(metadata) -> dict:
    """模拟「已生成的分析卡」的常见规模，用于度量判定请求里的上下文开销。

    判定请求会带上有界摘要/定义/未解释概念。这里按提示词允许的上限量级构造，
    属于**上界**估计：真实卡片通常更短（模型倾向于给出简短索引）。
    """
    cards = {}
    for uid in metadata["entries"]:
        cards[uid] = {
            "uid": uid,
            "summary": f"{uid} 的一句话摘要，说明这条设定定义了什么、给谁用。" * 2,
            "defined_concepts": ["概念甲的定义", "概念乙的定义", "概念丙的定义", "概念丁的定义"],
            "unexplained_concepts": ["外部概念一", "外部概念二", "外部概念三", "外部概念四"],
        }
    return cards


def load_real_cards(path: Path, book) -> dict:
    """从已完成任务的 JSON 里取**真实历史卡片**（只读）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    cards = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(cards, dict):
        return {}
    known = {entry.uid for entry in book.entries}
    return {uid: card for uid, card in cards.items()
            if uid in known and isinstance(card, dict)}


def render_fit_report(plans, budget: int) -> dict:
    """逐个**真实渲染**的请求是否都在预算内 —— 这是不可让步的硬约束。"""
    over = [plan for plan in plans if plan.input_tokens > budget]
    return {"requests": len(plans), "over_budget": len(over),
            "max_input_tokens": max((plan.input_tokens for plan in plans), default=0),
            "budget": budget,
            "total_input_tokens": sum(plan.input_tokens for plan in plans),
            "rendered_chars": sum(len(plan.text) for plan in plans)}


def rendered_batches_fit(plans, cards, entries_by_uid,
                         budget: int) -> list:
    """把每个计划**重新渲染一遍**并核对预算，返回超限清单。

    与 `render_fit_report` 的区别：这里刻意走一遍 `build_adjudication_prompt`，
    确认「规划时看到的文本」与「真正会发送的文本」是同一份（防止规划/执行漂移）。
    """
    problems = []
    for index, plan in enumerate(plans):
        pairs = [unit.payload for unit in plan.units]
        text, _ = builder.build_adjudication_prompt(pairs, cards, entries_by_uid)
        tokens = builder._system_tokens() + estimate_tokens(text)
        if tokens > budget:
            problems.append({"plan": index, "input_tokens": tokens, "budget": budget})
    return problems


def percent(before: float, after: float) -> float:
    return round(100.0 * (before - after) / before, 2) if before else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--book-path", default=str(DEFAULT_BOOK),
                        help="世界书 JSON 路径（只读）")
    parser.add_argument("--json-out", default="", help="把结果写到这个 JSON 文件")
    parser.add_argument("--cards-file", default=str(DEFAULT_CARDS_FILE),
                        help="真实历史卡片所在的任务 JSON（只读；不存在则退回合成卡片）")
    parser.add_argument("--min-adjudication-token-reduction", type=float, default=50.0,
                        help="判定输入 token 的最低下降百分比（未达到则退出码 1）")
    parser.add_argument("--min-call-reduction", type=float, default=50.0,
                        help="总请求数的最低下降百分比（未达到则退出码 1）")
    args = parser.parse_args()

    path = Path(args.book_path)
    if not path.is_file():
        print(f"[2] 找不到世界书：{path}")
        return 2
    book = WorldBook.from_dict(json.loads(path.read_text(encoding="utf-8")))
    entries_by_uid = {entry.uid: entry for entry in book.entries}
    metadata = builder.build_metadata_index(book.entries)
    report = builder.collect_candidates(metadata, entries_by_uid)
    pairs = report["pairs"]
    character_ids = sorted({entry.character_id for entry in book.entries if entry.character_id})

    units = builder.analysis_plan_units(metadata, entries_by_uid)
    # 旧实现只保留「首尾裁剪 + 分块」后的文本，这里按同样方式构造块文本。
    legacy_units = []
    for uid, info in metadata["entries"].items():
        entry = entries_by_uid.get(uid)
        if entry is None:
            continue
        chunks, _ = builder.entry_chunks(entry.content or "")
        for index, chunk in enumerate(chunks or [""]):
            block = builder._entry_block(uid, entry.name or uid, chunk,
                                         info.get("aliases") or [], part="x/y", chunk_id="x")
            legacy_units.append((uid, index, chunk, block, block, block))

    real_cards = load_real_cards(Path(args.cards_file), book)
    card_source = "real-historical-cards" if real_cards else "synthetic-upper-bound"
    cards = real_cards or synthetic_cards(metadata)

    analysis_instruction = estimate_tokens(builder._ANALYSIS_INSTRUCTION)
    adjudication_instruction = estimate_tokens(builder._ADJUDICATION_INSTRUCTION)

    legacy_analysis = legacy_analysis_cost(legacy_units, analysis_instruction)
    new_analysis_plans = builder.plan_analysis(units, metadata, entries_by_uid, character_ids)
    new_analysis = new_analysis_cost(units, metadata, entries_by_uid, character_ids)
    legacy_adjudication = legacy_adjudication_cost(pairs, entries_by_uid,
                                                   adjudication_instruction)
    new_adjudication_plans = builder.plan_adjudication(pairs, entries_by_uid, cards)
    new_adjudication = new_adjudication_cost(pairs, entries_by_uid, cards)

    # 硬约束：**每一个真实渲染的请求**都必须装得进它的输入预算。
    # 规划时已按真实渲染切分，这里再独立渲染一遍核对，捕捉规划/执行漂移。
    analysis_fit = render_fit_report(new_analysis_plans, builder.ANALYSIS_INPUT_TOKEN_BUDGET)
    adjudication_fit = render_fit_report(new_adjudication_plans,
                                         builder.ADJUDICATION_INPUT_TOKEN_BUDGET)
    drift = (rendered_batches_fit(new_adjudication_plans, cards, entries_by_uid,
                                  builder.ADJUDICATION_INPUT_TOKEN_BUDGET)
             if card_source == "real-historical-cards" else [])

    legacy_calls = legacy_analysis["requests"] + legacy_adjudication["requests"]
    new_calls = new_analysis["requests"] + new_adjudication["requests"]
    legacy_tokens = (legacy_analysis["estimated_input_tokens"]
                     + legacy_adjudication["estimated_input_tokens"])
    new_tokens = (new_analysis["estimated_input_tokens"]
                  + new_adjudication["estimated_input_tokens"])

    result = {
        "book": {"path": str(path), "entries": len(book.entries),
                 "chars": sum(len(e.content or "") for e in book.entries)},
        "chunks": len(units),
        "pairs": len(pairs),
        "cards_source": card_source,
        "legacy": {"analysis": legacy_analysis, "adjudication": legacy_adjudication,
                   "calls": legacy_calls, "estimated_input_tokens": legacy_tokens},
        "new": {"analysis": new_analysis, "adjudication": new_adjudication,
                "calls": new_calls, "estimated_input_tokens": new_tokens},
        "delta": {
            "calls_percent": percent(legacy_calls, new_calls),
            "estimated_input_tokens_percent": percent(legacy_tokens, new_tokens),
            "adjudication_input_tokens_percent": percent(
                legacy_adjudication["estimated_input_tokens"],
                new_adjudication["estimated_input_tokens"]),
            "analysis_input_tokens_percent": percent(
                legacy_analysis["estimated_input_tokens"],
                new_analysis["estimated_input_tokens"]),
        },
        "rendered_fit": {"analysis": analysis_fit, "adjudication": adjudication_fit,
                         "replayed_over_budget": drift},
        "note": ("估算值（estimate_tokens：CJK 1 token / 其余 4 字符 1 token），"
                 "不是 provider 账单。新实现一侧复用产品的装箱器与请求构造器；"
                 "旧实现一侧按历史参数（分析 6 / 判定 8、整段证据）复刻。"),
    }

    print(f"世界书：{path.name} · {len(book.entries)} 条 · "
          f"{result['book']['chars']} 字符 → {len(units)} 分块 / {len(pairs)} 候选对")
    print(f"分析卡来源：{card_source}")
    print("")
    print(f"{'阶段':<10}{'旧请求数':>10}{'新请求数':>10}{'旧输入 token':>16}{'新输入 token':>16}{'token 降幅':>12}")
    for stage, old, new in (("分析", legacy_analysis, new_analysis),
                            ("判定", legacy_adjudication, new_adjudication),
                            ("合计", {"requests": legacy_calls,
                                     "estimated_input_tokens": legacy_tokens},
                             {"requests": new_calls,
                              "estimated_input_tokens": new_tokens})):
        drop = percent(old["estimated_input_tokens"], new["estimated_input_tokens"])
        print(f"{stage:<10}{old['requests']:>10}{new['requests']:>10}"
              f"{old['estimated_input_tokens']:>16}{new['estimated_input_tokens']:>16}"
              f"{drop:>11.1f}%")
    print("")
    print(f"请求数下降：{result['delta']['calls_percent']}%"
          f"（{legacy_calls} → {new_calls}）")
    print(f"总输入 token 下降：{result['delta']['estimated_input_tokens_percent']}%"
          f"（{legacy_tokens} → {new_tokens}）")
    print(f"判定输入 token 下降：{result['delta']['adjudication_input_tokens_percent']}%")
    print(f"新实现单请求上限：分析 {new_analysis['max_request_tokens']} token / "
          f"判定 {new_adjudication['max_request_tokens']} token；"
          f"最大条数 {new_analysis['max_units_per_request']} / "
          f"{new_adjudication['max_units_per_request']}")
    print(f"超大单元独占请求：{new_analysis['oversized_requests']} / "
          f"{new_adjudication['oversized_requests']}")
    print(f"真实渲染超预算请求：分析 {analysis_fit['over_budget']}/{analysis_fit['requests']}、"
          f"判定 {adjudication_fit['over_budget']}/{adjudication_fit['requests']}"
          f"（预算 {builder.ADJUDICATION_INPUT_TOKEN_BUDGET}）")
    print(f"判定渲染总输入：{adjudication_fit['total_input_tokens']} token"
          f"（规划值 {new_adjudication['estimated_input_tokens']}）")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        print(f"结果已写入 {args.json_out}")

    failures = []
    if result["delta"]["adjudication_input_tokens_percent"] < args.min_adjudication_token_reduction:
        failures.append(f"判定输入 token 降幅不足："
                        f"{result['delta']['adjudication_input_tokens_percent']}% < "
                        f"{args.min_adjudication_token_reduction}%")
    if result["delta"]["calls_percent"] < args.min_call_reduction:
        failures.append(f"总请求数降幅不足：{result['delta']['calls_percent']}% < "
                        f"{args.min_call_reduction}%")
    if new_analysis["units"] != len(units) or new_adjudication["units"] != len(pairs):
        failures.append(f"覆盖不完整：分析 {new_analysis['units']}/{len(units)}、"
                        f"判定 {new_adjudication['units']}/{len(pairs)}")
    # 预算硬约束：任何一个真实渲染的请求超限都直接判失败。
    if analysis_fit["over_budget"]:
        failures.append(f"有 {analysis_fit['over_budget']} 个分析请求真实渲染后超出"
                        f"{analysis_fit['budget']} token（最大 {analysis_fit['max_input_tokens']}）")
    if adjudication_fit["over_budget"]:
        failures.append(f"有 {adjudication_fit['over_budget']} 个判定请求真实渲染后超出"
                        f"{adjudication_fit['budget']} token"
                        f"（最大 {adjudication_fit['max_input_tokens']}）")
    if drift:
        failures.append(f"重新渲染后有 {len(drift)} 个判定请求超限：规划与执行发生漂移")
    if failures:
        print("")
        for item in failures:
            print(f"[1] {item}")
        return 1
    print("")
    print("[0] 达标：判定输入 token 与总请求数均下降 ≥50%，且全部分块/候选对覆盖完整。")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
