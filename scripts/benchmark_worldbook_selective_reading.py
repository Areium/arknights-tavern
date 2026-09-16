#!/usr/bin/env python
"""离线比较当前 full 与 adaptive 第一遍阅读成本；不调用模型。"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from world_book import WorldBook  # noqa: E402
import worldbook_builder as builder  # noqa: E402
from worldbook_builder_plan import Unit  # noqa: E402
from worldbook_reading import build_reading_plan  # noqa: E402


def cost(units, metadata, entries, characters, reading, adaptive):
    wrapped = [item if isinstance(item, Unit) else Unit(key=item[1], payload=item)
               for item in units]
    plans = builder.plan_analysis(wrapped, metadata, entries, characters,
                                  reading=reading, adaptive=adaptive)
    return {
        "units": len(units), "calls": len(plans),
        "input_tokens": sum(plan.input_tokens for plan in plans),
        "expected_output_tokens": sum(plan.expected_output_tokens for plan in plans),
        "max_input_tokens": max((plan.input_tokens for plan in plans), default=0),
        "over_budget": sum(plan.oversized for plan in plans),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-path", required=True)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()
    path = Path(args.book_path)
    book = WorldBook.from_dict(json.loads(path.read_text(encoding="utf-8")))
    entries = {entry.uid: entry for entry in book.entries}
    metadata = builder.build_metadata_index(book.entries)
    candidate_report = builder.collect_candidates(metadata, entries)
    references = {}
    for pair in candidate_report["pairs"]:
        if pair.get("matched"):
            references.setdefault(pair["from_uid"], set()).add(pair["matched"])
    categories = {uid: info.get("category_id", "")
                  for uid, info in metadata["entries"].items()}
    full = build_reading_plan(book.entries, references, mode="full", categories=categories)
    adaptive = build_reading_plan(book.entries, references, mode="adaptive", categories=categories)
    characters = sorted({entry.character_id for entry in book.entries if entry.character_id})
    full_units = builder.analysis_plan_units(metadata, entries, full)
    adaptive_units = builder.analysis_plan_units(metadata, entries, adaptive)
    supplement_units = []
    for uid, selection in adaptive.items():
        if selection.full:
            continue
        content = entries[uid].content or ""
        for index, span in enumerate(selection.unread_spans(content)):
            supplement_units.append((uid, builder._span_chunk_id(uid, span), index,
                                     content[span.start:span.end], "", span.reason))
    full_cost = cost(full_units, metadata, entries, characters, full, False)
    adaptive_cost = cost(adaptive_units, metadata, entries, characters, adaptive, True)
    supplement_cost = cost(supplement_units, metadata, entries, characters, adaptive, True)
    total_chars = sum(len(entry.content or "") for entry in book.entries)
    selected_chars = sum(item.selected_chars for item in adaptive.values())
    full_ids = [item.key for item in full_units]
    adaptive_ids = [item.key for item in adaptive_units]
    supplement_ids = [item[1] for item in supplement_units]
    assert len(full_ids) == len(set(full_ids)), "full units contain duplicate IDs"
    assert len(adaptive_ids + supplement_ids) == len(set(adaptive_ids + supplement_ids)), \
        "adaptive seed/supplement units contain duplicate IDs"
    assert sum(len(item.payload[3]) for item in full_units) == total_chars, \
        "full units do not cover book"
    assert selected_chars + sum(len(item[3]) for item in supplement_units) == total_chars, \
        "adaptive seed plus complement does not cover book"
    second_candidates = builder.collect_candidates(metadata, entries)["pairs"]
    assert [(p["from_uid"], p["to_uid"], p.get("matched")) for p in candidate_report["pairs"]] == [
        (p["from_uid"], p["to_uid"], p.get("matched")) for p in second_candidates], \
        "candidate scan changed across reading plans"
    result = {
        "book_path": str(path), "entries": len(entries), "total_chars": total_chars,
        "candidate_pairs": len(candidate_report["pairs"]),
        "full": full_cost, "adaptive_first_pass": adaptive_cost,
        "adaptive_selected_chars": selected_chars,
        "adaptive_omitted_chars": total_chars - selected_chars,
        "first_pass_input_reduction_percent": round(
            100 * (full_cost["input_tokens"] - adaptive_cost["input_tokens"])
            / full_cost["input_tokens"], 2) if full_cost["input_tokens"] else 0,
        "forced_supplement": {
            **supplement_cost,
            "additional_raw_chars": sum(len(item[3]) for item in supplement_units),
            "note": "最坏情况下补读全部未读正文；实际请求数取决于哪些条目请求补充。",
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    return 1 if full_cost["over_budget"] or adaptive_cost["over_budget"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
