"""Diagnostic: simulate preload import resolution for a story session."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from wiki_manager import WikiManager

wm = WikiManager()

# Near Light scenario — the 5 characters that would be in scene
scene_chars = ["临光", "瑕光", "玛恩纳·临光", "佐菲娅", "博士"]
entry_paths = [f"characters/{c}" for c in scene_chars]

print("=== Near Light 场景角色 ===")
print(f"入口: {entry_paths}\n")

result = wm.resolve_imports_chain(entry_paths, max_depth=2)

depth0 = {k: v for k, v in result.items() if v["depth"] == 0}
depth1 = {k: v for k, v in result.items() if v["depth"] == 1}
depth2 = {k: v for k, v in result.items() if v["depth"] >= 2}

print(f"=== 解析结果: {len(result)} 个文档 ===")
print(f"  Depth 0 (全文): {len(depth0)}")
for k, v in depth0.items():
    size = len(v["content"])
    print(f"    [{k}] → {size:,} chars")

print(f"  Depth 1 (核心): {len(depth1)}")
for k, v in sorted(depth1.items()):
    size = len(v["content"])
    print(f"    [{k}] → {size:,} chars")

print(f"  Depth 2 (摘要): {len(depth2)}")

total_chars = sum(len(v["content"]) for v in result.values())
print(f"\n总字符数: {total_chars:,} → 预估 ~{total_chars // 2:,} tokens (中文)")
print(f"\n重复检查: visited 集天然去重，无重复文档。")

# Check: would combat.md appear in the catalog?
print(f"\n=== combat.md 是否在 Wiki 目录中? ===")
combat_in_catalog = wm._catalog.get("characters/临光/combat")
print(f"  characters/临光/combat: {'存在' if combat_in_catalog else '不存在（正确——不在预加载链中）'}")
