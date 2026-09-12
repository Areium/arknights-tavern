"""T4：Token 节省对比——同知识集合下「全量注入」vs「三级提取+目录摘要+按需缓存」的注入规模。"""
import json
import sys
from pathlib import Path

from common import ROOT

from wiki_manager import WikiManager
from world_book import estimate_tokens

CHARS = ["临光", "瑕光"]
CATS = {"characters", "factions", "locations", "items", "world"}


def doc_full_tokens(wm: WikiManager, cat: str, doc_id: str) -> int:
    content = wm.get_document(cat, doc_id, "full") or ""
    return estimate_tokens(content)


def build_full(wm: WikiManager) -> int:
    """全量注入：把目录内全部文档全文直接拼接。"""
    total = 0
    for cat in CATS:
        for doc_id in wm._by_category.get(cat, []):
            total += doc_full_tokens(wm, cat, doc_id)
    return total


def build_layered(wm: WikiManager) -> int:
    """分层注入：目录摘要 + 角色 imports 链 core 提取 + 历史 3000 字 + 世界书触发样例。"""
    total = 0
    catalog = wm.format_catalog_summary(CATS)
    total += estimate_tokens(catalog)

    for name in CHARS:
        chain = wm.resolve_imports_chain([f"characters/{name}"], max_depth=1)
        for path, d in chain.items():
            total += estimate_tokens(d.get("content") or "")
            total += estimate_tokens(d.get("summary") or "")

    history = "第1轮…第20轮 对话历史示例（按 3000 字硬上限截断）：" + "列" * 2950
    total += estimate_tokens(history)

    wb_sample = "【世界书】### 喀兰贸易\n喀兰贸易是谢拉格最大的商业集团……" + "设" * 600
    total += estimate_tokens(wb_sample)
    return total


def run():
    wm = WikiManager(str(ROOT))
    full = build_full(wm)
    layered = build_layered(wm)
    doc_count = sum(len(wm._by_category.get(c, [])) for c in CATS)
    print(json.dumps({
        "docs_in_catalog": doc_count,
        "characters_preloaded": CHARS,
        "full_injection_tokens": full,
        "layered_injection_tokens": layered,
        "token_saving_pct": round((1 - layered / full) * 100, 1) if full else None,
        "note": "同知识集合口径：分层注入包含目录摘要、角色引用链 core 提取、3000字历史、世界书触发条目；全量注入为目录内全部文档全文。",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()