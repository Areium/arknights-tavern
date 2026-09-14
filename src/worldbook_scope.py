"""世界书分类 / 导入策略校验；与酒馆的关键词、常驻、预算规则相互独立。"""

from collections import deque
import copy

MAX_DEPENDENCY_DEPTH = 32
EXTENSION_KEY = "arknights_tavern"
UNCLASSIFIED = {"id": "unclassified", "parent_id": None, "name": "未分类",
                "scope_type": "other", "sort_order": 1000}


def validate_categories(value):
    if not isinstance(value, list):
        raise ValueError("categories 必须是数组")
    result, by_id = [], {}
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("分类必须是对象")
        cid, name = raw.get("id"), raw.get("name")
        if not isinstance(cid, str) or not cid.strip() or cid != cid.strip() or cid in by_id:
            raise ValueError("分类 ID 必须是唯一的非空字符串")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"分类 {cid} 名称不能为空")
        parent = raw.get("parent_id") or None
        if parent is not None and not isinstance(parent, str):
            raise ValueError(f"分类 {cid} 的父级 ID 无效")
        kind = raw.get("scope_type", "other")
        if kind not in ("worldview", "character", "other"):
            raise ValueError(f"分类 {cid} 类型无效")
        order = raw.get("sort_order", 0)
        if type(order) is not int:
            raise ValueError(f"分类 {cid} 排序必须是整数")
        category = {"id": cid, "name": name.strip(), "parent_id": parent,
                    "scope_type": kind, "sort_order": order}
        result.append(category)
        by_id[cid] = category
    for category in result:
        seen, current = set(), category
        while current["parent_id"]:
            if current["id"] in seen:
                raise ValueError(f"分类树不能包含循环：{category['id']}")
            seen.add(current["id"])
            parent = by_id.get(current["parent_id"])
            if not parent:
                raise ValueError(f"分类 {current['id']} 的父级不存在")
            if current["scope_type"] != parent["scope_type"]:
                raise ValueError(f"子分类 {current['id']} 必须继承父级类型")
            current = parent
    if "unclassified" in by_id and by_id["unclassified"] != UNCLASSIFIED:
        raise ValueError("系统分类“未分类”不可修改或移动")
    if "unclassified" not in by_id:
        result.append(copy.deepcopy(UNCLASSIFIED))
    return result


def validate_policy(known, value, default_edges=()):
    """写入接口严格拒绝坏引用，不能用静默过滤掩盖用户配置错误。"""
    if not isinstance(value, dict):
        raise ValueError("导入配置必须是对象")
    fixed, sources = value.get("fixed_entry_uids", []), value.get("dependency_sources", [])
    edges = value.get("dependency_edges", list(default_edges))
    if not all(isinstance(items, list) for items in (fixed, sources, edges)):
        raise ValueError("固定导入、依赖源和依赖边必须是数组")
    seen = set()
    for uid in fixed:
        if not isinstance(uid, str) or uid not in known or uid in seen:
            raise ValueError(f"固定导入包含不存在或重复的条目：{uid}")
        seen.add(uid)
    seen = set()
    normalized_sources = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("依赖源必须是对象")
        uid, depth = source.get("entry_uid"), source.get("max_depth")
        if not isinstance(uid, str) or uid not in known or uid in seen:
            raise ValueError(f"依赖源包含不存在或重复的条目：{uid}")
        if type(depth) is not int or not 0 <= depth <= MAX_DEPENDENCY_DEPTH:
            raise ValueError(f"依赖源 {uid} 深度必须是 0-{MAX_DEPENDENCY_DEPTH} 的整数")
        seen.add(uid)
        normalized_sources.append({"entry_uid": uid, "max_depth": depth})
    seen, normalized_edges = set(), []
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("依赖边必须是对象")
        a, b = edge.get("from_uid"), edge.get("to_uid")
        if not isinstance(a, str) or not isinstance(b, str) or a not in known or b not in known:
            raise ValueError(f"依赖边包含不存在的节点：{a} → {b}")
        if a == b or (a, b) in seen:
            raise ValueError(f"依赖边不能为自环或重复边：{a} → {b}")
        seen.add((a, b))
        normalized_edges.append({"from_uid": a, "to_uid": b})
    return {"fixed_entry_uids": list(fixed), "dependency_sources": normalized_sources}, normalized_edges


def expand_sources(sources, edges):
    """按最大剩余深度去重的 BFS；固定条目不作为隐式遍历起点。"""
    adjacency = {}
    for edge in edges:
        adjacency.setdefault(edge["from_uid"], []).append(edge["to_uid"])
    queue = deque((s["entry_uid"], s["max_depth"]) for s in sources)
    best_remaining = {}
    while queue:
        uid, remaining = queue.popleft()
        if remaining <= best_remaining.get(uid, -1):
            continue
        best_remaining[uid] = remaining
        if remaining:
            queue.extend((target, remaining - 1) for target in sorted(adjacency.get(uid, [])))
    return set(best_remaining)


def find_scope_extension(value):
    """只恢复所属世界书的命名空间扩展；普通酒馆/JSONL 导入仍按旧策略。"""
    if not isinstance(value, dict):
        return None
    if "entries" in value:
        extensions = value.get("extensions")
        extension = extensions.get(EXTENSION_KEY) if isinstance(extensions, dict) else None
        return extension if isinstance(extension, dict) else None
    for key in ("data", "character_book", "world", "extensions"):
        extension = find_scope_extension(value.get(key))
        if extension is not None:
            return extension
    return None
