#!/usr/bin/env python
"""真实 LLM 端到端验证：世界书依赖自动构建。

这个脚本**真的调用**当前已配置的模型（不是 stub、不是字符串匹配假装 AI），
用来回答一个具体问题：给定一本真实世界书，一次点击能不能产出可用的
起点与依赖建议，并且这些建议有原文证据、能被程序校验、能被缓存复用。

用法：
    # 用仓库默认配置（config/llm_config.json）
    python scripts/verify_worldbook_builder_llm.py

    # 指定配置（例如复用主工作区里已配好的模型，不必把密钥复制过来）
    python scripts/verify_worldbook_builder_llm.py --config D:/Code/arknights-tavern/config/llm_config.json

    # 用内置预装世界书跑真实规模（默认只用 6 条小样本，省时间与费用）
    python scripts/verify_worldbook_builder_llm.py --book preinstalled --limit 12

    # 直接指定要验证的世界书（不再按「预装列表第一本」随机挑选）
    python scripts/verify_worldbook_builder_llm.py --book-path D:/Code/arknights-tavern/data/worldbooks/arknights.json

退出码：
    0 = 真实调用成功且通过全部断言
    2 = 没有可用模型 / 配置缺失（明确报告「未做真实验证」，不假装通过）
    3 = 真实调用失败或断言不通过
"""
import argparse
import json
import os
import sys
import time
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import llm_backend_manager as backend_module          # noqa: E402
from llm_backend_manager import LLMBackendManager     # noqa: E402
from world_book import DEFAULT_CATEGORIES, WorldBook, WorldBookEntry  # noqa: E402
from worldbook_builder import (                        # noqa: E402
    AnalysisCache, DependencyBuildJob, PROMPT_VERSION, build_to_v3_rules, model_identity, run_build,
)
from worldbook_scope import validate_v3_rules          # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(REPO / "config" / "llm_config.json"),
                        help="LLM 配置文件路径（默认仓库内 config/llm_config.json）")
    parser.add_argument("--book", default="sample", choices=["sample", "preinstalled"],
                        help="sample=内置 6 条小样本；preinstalled=仓库预装世界书")
    parser.add_argument("--book-path", default="",
                        help="直接指定世界书 JSON 路径（只读）；给了它就以它为准，"
                             "不再按「预装书列表第一本」随机挑选")
    parser.add_argument("--limit", type=int, default=0,
                        help="预装书只取前 N 条（0 表示不限制；大书会明显更慢更贵）")
    parser.add_argument("--max-calls", type=int, default=60, help="调用预算上限")
    parser.add_argument("--json-out", default="", help="把结果写到这个 JSON 文件")
    args = parser.parse_args()
    if args.book_path and args.book == "sample":
        args.book = "path"
    return args


def sample_book() -> WorldBook:
    """6 条小样本：足够触发「明确引用 → 候选对 → 判定」全链路。"""
    return WorldBook("verify-sample", "验证样本", [
        WorldBookEntry("world", "泰拉大陆的基础设定：源石、天灾与移动城市。", name="泰拉世界",
                       always_active=True, category_id="worldview"),
        WorldBookEntry("originium", "源石技艺：以源石为媒介施术，长期使用会导致矿石病。",
                       name="源石技艺", always_active=True, category_id="other"),
        WorldBookEntry("rhodes", "罗德岛：以治疗矿石病为目标的制药公司与武装组织。",
                       name="罗德岛", always_active=True, category_id="other"),
        WorldBookEntry("amiya", "阿米娅：罗德岛公开领袖，使用源石技艺，与博士关系密切。",
                       name="阿米娅", always_active=True, category_id="characters",
                       character_id="amiya"),
        WorldBookEntry("kaltsit", "凯尔希：罗德岛医疗部门负责人，对矿石病有深入研究。",
                       name="凯尔希", always_active=True, category_id="characters",
                       character_id="kaltsit"),
        WorldBookEntry("oriopathy", "矿石病：源石技艺的副作用，罗德岛的核心研究课题。",
                       name="矿石病", always_active=True, category_id="other"),
    ], categories=json.loads(json.dumps(DEFAULT_CATEGORIES)))


def preinstalled_book(limit: int, book_path: str = "") -> WorldBook:
    from world_book import WorldBookManager
    if book_path:
        book = WorldBook.from_dict(json.loads(Path(book_path).read_text(encoding="utf-8")))
        if limit:
            book.entries = book.entries[:limit]
        return book
    manager = WorldBookManager(REPO / "data" / "worldbooks")
    for summary in manager.list_books():
        book = manager.load(summary["id"])
        if book is None:
            continue
        if limit:
            book.entries = book.entries[:limit]
        return book
    raise SystemExit("没有找到预装世界书，请先用 --book sample 运行。")


def _expected_pairs(book) -> list:
    """这本书在一次完整构建里应当被判定到的全部候选对（与产品同一条代码路径）。"""
    from worldbook_builder import build_metadata_index, collect_candidates
    entries_by_uid = {entry.uid: entry for entry in book.entries}
    metadata = build_metadata_index(book.entries)
    return collect_candidates(metadata, entries_by_uid)["pairs"]


def main() -> int:
    args = parse_args()
    config = Path(args.config)
    if not config.exists():
        print(f"[2] 未做真实验证：找不到配置文件 {config}")
        print("    请先在「设置」里配置模型，或用 --config 指向已有配置。")
        return 2

    # 刻意**不预先检查 api_key**：本地 endpoint（Ollama / 局域网网关 / 无需鉴权的
    # 自建服务）完全可能没有 key 或用一个非占位符的本地值，预检会把合法的本地
    # 配置误判成「未配置」。配置是否可用，交给下面的 get_llm() 用真实探测回答。
    # 让后端管理器读这份配置，但绝不打印其中的密钥。
    backend_module._CONFIG_PATH = config
    backend = LLMBackendManager()
    llm, backend_id = backend.get_llm()
    model = model_identity(llm, backend_id)
    if llm is None:
        print("[2] 未做真实验证：配置存在但当前没有可用端点（模型未就绪或处于冷却）。")
        return 2
    print(f"[1] 使用真实模型：{model or '(未报告模型名)'}")
    print(f"    配置来源：{config}")

    if args.book_path:
        book = preinstalled_book(args.limit, args.book_path)
        print(f"    输入来源：--book-path {args.book_path}")
    else:
        book = sample_book() if args.book == "sample" else preinstalled_book(args.limit)
    print(f"    世界书：{book.name}（{len(book.entries)} 条，{sum(len(e.content) for e in book.entries)} 字符）")

    temporary = tempfile.TemporaryDirectory(prefix="worldbook-llm-verification-")
    cache = AnalysisCache(Path(temporary.name) / "cache")
    job = DependencyBuildJob("verify", book.id, "verify-input", model=model, directory=Path(temporary.name))
    started = time.time()
    run_build(job, book, llm, model=model, cache=cache, max_calls=args.max_calls,
              character_ids=sorted({e.character_id for e in book.entries if e.character_id}))
    elapsed = time.time() - started

    print(f"[2] 阶段结束于：{job.stage}（{elapsed:.1f}s，{job.calls} 次模型调用，"
          f"{len(job.cards)} 张卡 / {len(job.judgments)} 条判定）")
    workload = job.workload or {}
    metrics = job.metrics or {}
    print(f"    规划：预计 {workload.get('estimated_calls', '?')} 次请求"
          f"（分析 {workload.get('card_calls', '?')} + 判定 {workload.get('adjudication_calls', '?')}）"
          f" · 预计输入 {workload.get('estimated_input_tokens', '?')} token")
    actual = (f"输入 {metrics.get('actual_prompt_tokens')} / 输出 {metrics.get('actual_completion_tokens')}"
              if metrics.get("actual_known") else "未知（当前模型未返回 usage）")
    print(f"    实际：{metrics.get('requests', 0)} 次请求 · JSON 修复 {metrics.get('json_repair_calls', 0)} 次"
          f" · 缓存命中 {metrics.get('cache_hits', 0)} 对 · 真实用量：{actual}")
    if job.error:
        print(f"[3] 真实调用失败：{job.error['code']} {job.error['message']}")
        return 3
    if job.stage != "done" or job.outcome != "success" or not job.result:
        print(f"[3] 未产出结果：stage={job.stage} message={job.message}")
        return 3

    result = job.result
    stats = result["stats"]
    print(f"    关系：必要 {stats['requires']} / 关联 {stats['related']} / "
          f"待复核 {stats['unsure']} / 无关系 {stats['none']}")

    failures = []

    # ── 断言 1：结果真的进了 v3 规则，且能被写入校验接受 ──
    rules = build_to_v3_rules(book, {"accepted": result["accepted"]})
    try:
        parsed_rules, requires, related = validate_v3_rules(
            {e.uid for e in book.entries}, rules)
    except ValueError as exc:
        failures.append(f"v3 规则校验被拒：{exc}")
        parsed_rules, requires, related = {}, [], []
    print(f"    规则：起点 {len(parsed_rules.get('roots', []))} / "
          f"必要边 {len(requires)} / 关联边 {len(related)}")

    # ── 断言 2：UID 只能来自真实输入，证据必须能在原文里定位 ──
    known = {e.uid for e in book.entries}
    contents = {e.uid: e.content for e in book.entries}
    for record in result["records"]:
        if record["from_uid"] not in known or record["to_uid"] not in known:
            failures.append(f"出现输入之外的 UID：{record['from_uid']} → {record['to_uid']}")
        if record["relation"] in ("requires", "related"):
            evidence = (record.get("evidence") or "").strip()
            if len(evidence) < 4:
                failures.append(f"必要/关联关系缺证据：{record['from_uid']} → {record['to_uid']}")
            else:
                normalized = "".join(evidence.split())
                haystack = "".join((contents[record["from_uid"]] + contents[record["to_uid"]]).split())
                if normalized not in haystack:
                    failures.append(
                        f"证据无法在原文定位：{record['from_uid']} → {record['to_uid']}：{evidence[:40]}")
        if not record.get("model"):
            failures.append(f"缺少来源模型记录：{record['from_uid']} → {record['to_uid']}")
        if record.get("prompt_version") != PROMPT_VERSION:
            failures.append(f"prompt_version 不是 {PROMPT_VERSION}：{record.get('prompt_version')}")

    # ── 断言 3：角色条目变成 roster 起点而不是全局源 ──
    for root in parsed_rules.get("roots", []):
        entry = next((e for e in book.entries if e.uid == root["entry_uid"]), None)
        if entry is not None and entry.character_id:
            if root["activation"] != "roster_any":
                failures.append(f"角色条目 {entry.uid} 没有成为 roster 起点（{root['activation']}）")
            if root.get("character_ids") != [entry.character_id]:
                failures.append(f"角色条目 {entry.uid} 的 character_ids 不正确")

    # ── 断言 4：缓存按 content_hash + model 生效，第二次不再重新分析 ──
    # 用同一个缓存目录再跑一遍：第二次应当直接命中磁盘缓存。
    cache2 = AnalysisCache(cache._dir)
    job2 = DependencyBuildJob("verify-2", book.id, "verify-input", model=model, directory=Path(temporary.name))
    run_build(job2, book, llm, model=model, cache=cache2, max_calls=args.max_calls,
              character_ids=sorted({e.character_id for e in book.entries if e.character_id}))
    if job2.error:
        failures.append(f"第二次运行失败：{job2.error['code']} {job2.error['message']}")
    elif job2.calls >= job.calls:
        failures.append(f"缓存未生效：第二次仍调用 {job2.calls} 次（第一次 {job.calls} 次）")
    print(f"    缓存复用：第一次 {job.calls} 次调用 → 第二次 {job2.calls} 次"
          f"（省下 {job.calls - job2.calls} 次）")

    # ── 断言 5：候选对与分块必须被完整覆盖（没有静默丢件）──
    judged = {(item.get("from_uid"), item.get("to_uid")) for item in job.judgments}
    expected_pairs = {(p["from_uid"], p["to_uid"]) for p in _expected_pairs(book)}
    missing_pairs = expected_pairs - judged
    if missing_pairs:
        failures.append(f"有 {len(missing_pairs)} 对候选没有判定结果（未重试也未标记失败）")
    print(f"    覆盖：候选对 {len(judged)}/{len(expected_pairs)}"
          f" · 分析卡 {len(job.cards)}/{len(book.entries)}")

    print("[3] 展开自检（用于发现「所有角色都变成全局源」这类过度扩张）：")
    print("    " + json.dumps(result.get("expansion_probe", {}), ensure_ascii=False))
    if result.get("cycles"):
        print(f"    环：{len(result['cycles'])} 处（遍历会安全终止，不会静默截断）")
    if result.get("issues"):
        print(f"    校验问题 {len(result['issues'])} 条：")
        for issue in result["issues"][:10]:
            print(f"      - [{issue['severity']}] {issue['message']}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "model": model, "book": book.id, "entries": len(book.entries),
            "elapsed_seconds": round(elapsed, 2), "calls": job.calls,
            "stats": stats, "records": result["records"],
            "issues": result["issues"], "cycles": result["cycles"],
            "expansion_probe": result.get("expansion_probe", {}),
            "failures": failures,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    结果已写入 {args.json_out}")

    if failures:
        print(f"[3] 真实验证未通过，{len(failures)} 项问题：")
        for item in failures[:20]:
            print(f"    - {item}")
        return 3

    print("[0] 真实验证通过：真实模型产出的建议全部通过程序校验、证据可在原文定位、缓存生效。")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
