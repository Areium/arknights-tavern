"""世界书分类 / 导入策略校验；与酒馆的关键词、常驻、预算规则相互独立。"""

from collections import deque
import copy
import time

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


# ─────────────────────────────────────────────────────────────
# v3：全书底层有向图 + 条件起点
#
# v3 与 v2 的核心区别是「谁进候选」与「怎么组织」彻底分开：
#   - 分类只负责组织（改名/移动分类**不**隐式改变候选范围）；
#   - 起点由 activation 决定，展开由 expansion 决定；
#   - requires 边参与遍历，related 边只供浏览。
# v2 的 fixed / dependency_sources / max_depth 语义由 legacy_depth 精确保留。
# ─────────────────────────────────────────────────────────────

SCHEMA_VERSION_V3 = 3

ACTIVATION_ALWAYS = "always"
ACTIVATION_ROSTER_ANY = "roster_any"
ACTIVATION_MANUAL = "manual"
ACTIVATIONS = (ACTIVATION_ALWAYS, ACTIVATION_ROSTER_ANY, ACTIVATION_MANUAL)

EXPANSION_NONE = "none"
EXPANSION_REQUIRES_CLOSURE = "requires_closure"
EXPANSION_LEGACY_DEPTH = "legacy_depth"
EXPANSIONS = (EXPANSION_NONE, EXPANSION_REQUIRES_CLOSURE, EXPANSION_LEGACY_DEPTH)

# 必要闭包的保护上限：超过即报「来源过大」，**不做静默截断**。
MAX_CLOSURE_NODES = 20000


def _norm_edge_list(known, value, label):
    """规范化一类有向边：拒绝坏引用、自环与重复边（不静默过滤）。"""
    if not isinstance(value, list):
        raise ValueError(f"{label}必须是数组")
    seen, result = set(), []
    for edge in value:
        if not isinstance(edge, dict):
            raise ValueError(f"{label}必须是对象")
        a, b = edge.get("from_uid"), edge.get("to_uid")
        if not isinstance(a, str) or not isinstance(b, str) or a not in known or b not in known:
            raise ValueError(f"{label}包含不存在的节点：{a} → {b}")
        if a == b:
            raise ValueError(f"{label}不能为自环：{a} → {b}")
        if (a, b) in seen:
            raise ValueError(f"{label}不能有重复边：{a} → {b}")
        seen.add((a, b))
        result.append({"from_uid": a, "to_uid": b})
    return result


def validate_v3_rules(known, value, default_requires=()):
    """校验 v3 规则集，返回规范化后的 (rules, requires_edges, related_edges)。

    `known` 是合法 UID 集合。写入接口严格拒绝坏引用——配置错误必须暴露给用户，
    不能被静默丢弃成「看起来生效了」。
    """
    if not isinstance(value, dict):
        raise ValueError("v3 规则必须是对象")
    raw_roots = value.get("roots", [])
    requires = value.get("requires_edges", value.get("dependency_edges", list(default_requires)))
    related = value.get("related_edges", [])
    if not isinstance(raw_roots, list):
        raise ValueError("起点必须是数组")

    seen, roots = set(), []
    for raw in raw_roots:
        if not isinstance(raw, dict):
            raise ValueError("起点必须是对象")
        uid = raw.get("entry_uid")
        if not isinstance(uid, str) or uid not in known:
            raise ValueError(f"起点包含不存在或无效的条目：{uid}")
        if uid in seen:
            raise ValueError(f"起点重复：{uid}")
        seen.add(uid)

        activation = raw.get("activation", ACTIVATION_MANUAL)
        if activation not in ACTIVATIONS:
            raise ValueError(f"起点 {uid} 的 activation 必须是 {'/'.join(ACTIVATIONS)}")
        expansion = raw.get("expansion", EXPANSION_REQUIRES_CLOSURE)
        if expansion not in EXPANSIONS:
            raise ValueError(f"起点 {uid} 的 expansion 必须是 {'/'.join(EXPANSIONS)}")

        chars = raw.get("character_ids", [])
        if not isinstance(chars, list) or any(
                not isinstance(c, str) or not c.strip() for c in chars):
            raise ValueError(f"起点 {uid} 的 character_ids 必须是非空字符串组成的数组")
        if activation == ACTIVATION_ROSTER_ANY and not chars:
            raise ValueError(f"起点 {uid} 使用 roster_any 时必须给出 character_ids")
        if activation != ACTIVATION_ROSTER_ANY and chars:
            raise ValueError(f"起点 {uid} 只有 roster_any 才能指定 character_ids")

        item = {"entry_uid": uid, "activation": activation, "expansion": expansion,
                "character_ids": sorted({c.strip() for c in chars})}
        if expansion == EXPANSION_LEGACY_DEPTH:
            depth = raw.get("max_depth")
            if type(depth) is not int or not 0 <= depth <= MAX_DEPENDENCY_DEPTH:
                raise ValueError(
                    f"起点 {uid} 深度必须是 0-{MAX_DEPENDENCY_DEPTH} 的整数")
            item["max_depth"] = depth
        roots.append(item)

    requires_edges = _norm_edge_list(known, requires, "必要依赖边")
    related_edges = _norm_edge_list(known, related, "关联补充边")
    overlap = {(e["from_uid"], e["to_uid"]) for e in requires_edges} & {
        (e["from_uid"], e["to_uid"]) for e in related_edges}
    if overlap:
        pair = sorted(overlap)[0]
        raise ValueError(f"同一条边不能既是必要依赖又是关联补充：{pair[0]} → {pair[1]}")

    root_rule = value.get("root_rule")
    if root_rule is None:
        root_rule = {"entry_uids": sorted(seen)}
    elif not isinstance(root_rule, dict):
        raise ValueError("root_rule 必须是对象")
    rule_uids = root_rule.get("entry_uids", [])
    if not isinstance(rule_uids, list) or any(
            not isinstance(u, str) or u not in known for u in rule_uids):
        raise ValueError("root_rule.entry_uids 必须是有效条目 UID 数组")
    if len(set(rule_uids)) != len(rule_uids):
        raise ValueError("root_rule.entry_uids 不能重复")

    return ({"roots": roots, "root_rule": {"entry_uids": sorted(set(rule_uids))}},
            requires_edges, related_edges)


def _rank_remaining(remaining):
    """剩余深度排序键：None（不限深度）最大，其余按数值。"""
    return (1, 0) if remaining is None else (0, remaining)


def resolve_v3_scope(entries, rules, requires_edges, related_edges,
                     roster_character_ids=None, policy_revision=1,
                     content_revision="", book_id=""):
    """按 v3 规则解析候选范围，返回可解释的完整结果。

    解析以**实际成功加载的阵容**激活起点，沿 requires 闭包展开，UID 去重，
    保留所有选用原因与参与边，并生成稳定主路径用于树显示。

    关键语义：
    - `related` 边**不参与遍历**，只作为浏览信息返回；
    - 被依赖带入的条目**不会**反过来激活它所属角色的整组条目
      （激活只看起点自身的 activation，依赖只负责补齐）；
    - 环可终止；新必要闭包不会被随意深度静默截断，超限报「来源过大」。
    """
    roster = set()
    for value in roster_character_ids or []:
        if isinstance(value, str) and value.strip():
            roster.add(value.strip())

    by_uid = {}
    for entry in entries:
        uid = getattr(entry, "uid", None) if not isinstance(entry, dict) else entry.get("uid")
        if isinstance(uid, str) and uid:
            by_uid[uid] = entry

    def field(uid, name, default=""):
        entry = by_uid.get(uid)
        if entry is None:
            return default
        if isinstance(entry, dict):
            return entry.get(name, default)
        return getattr(entry, name, default)

    # ── 1. 激活起点 ──
    active_roots, root_reasons = [], {}
    for root in rules["roots"]:
        uid = root["entry_uid"]
        if uid not in by_uid:
            continue
        activation = root["activation"]
        if activation == ACTIVATION_ALWAYS:
            active_roots.append(root)
            root_reasons[uid] = "always"
        elif activation == ACTIVATION_ROSTER_ANY:
            hit = sorted(roster & set(root["character_ids"]))
            if hit:
                active_roots.append(root)
                root_reasons[uid] = "roster:" + ",".join(hit)
        # manual：只登记，不自动激活（由调用方按需显式追加）

    # ── 2. 沿 requires 闭包展开（多源、最大剩余深度去重）──
    adjacency = {}
    for edge in requires_edges:
        adjacency.setdefault(edge["from_uid"], []).append(edge["to_uid"])
    for targets in adjacency.values():
        targets.sort()

    best = {}          # uid -> remaining（None = 不限）
    path_of = {}       # uid -> {"root","depth","parent"}
    used_edges = set() # 真正参与展开的边
    oversized = None

    queue = deque()
    for root in active_roots:
        uid = root["entry_uid"]
        expansion = root["expansion"]
        if expansion == EXPANSION_NONE:
            remaining = 0
        elif expansion == EXPANSION_LEGACY_DEPTH:
            remaining = root["max_depth"]
        else:
            remaining = None
        queue.append((uid, remaining, uid, 0, None))

    while queue:
        uid, remaining, root_uid, depth, parent = queue.popleft()
        known_remaining = best.get(uid, "absent")
        if known_remaining != "absent" and _rank_remaining(known_remaining) >= _rank_remaining(remaining):
            continue
        best[uid] = remaining
        path_of[uid] = {"root": root_uid, "depth": depth, "parent": parent}
        if remaining == 0:
            continue
        for target in adjacency.get(uid, []):
            used_edges.add((uid, target))
            if remaining is None:
                queue.append((target, None, root_uid, depth + 1, uid))
            else:
                queue.append((target, remaining - 1, root_uid, depth + 1, uid))
        if oversized is None and len(best) > MAX_CLOSURE_NODES:
            oversized = len(best)

    if oversized is not None:
        return {"book_id": book_id, "schema_version": SCHEMA_VERSION_V3,
                "policy_revision": policy_revision, "content_revision": content_revision,
                "roster_character_ids": sorted(roster), "active_roots": [],
                "resolved_entry_uids": [], "resolved_edges": [],
                "selection_reasons": {}, "display_tree": [], "cross_references": [],
                "issues": [{"code": "closure_too_large", "severity": "error",
                            "message": (f"必要依赖闭包超过 {MAX_CLOSURE_NODES} 个条目"
                                        f"（已达 {oversized}），疑似起点或依赖配置过大；"
                                        "请收窄起点或检查依赖边。")}],
                "resolved_at": time.time()}

    # ── 3. 选用原因 ──
    reasons = {}
    for uid in best:
        entry_reasons = []
        if uid in root_reasons:
            entry_reasons.append(root_reasons[uid])
        if path_of[uid]["root"] != uid:
            entry_reasons.append("requires")
        reasons[uid] = entry_reasons

    resolved_edges = [{"from_uid": a, "to_uid": b, "relation": "requires",
                       "active": (a, b) in used_edges}
                      for a, b in sorted({(e["from_uid"], e["to_uid"]) for e in requires_edges})]
    resolved_edges.extend({"from_uid": e["from_uid"], "to_uid": e["to_uid"],
                           "relation": "related", "active": False}
                          for e in related_edges)

    # ── 4. 稳定主路径树 ──
    # 按 (深度, uid) 排序：父节点深度必然小于子节点，因此父总在子之前，
    # 同一层内按 uid 稳定排序 → 同一份输入永远得到同一棵树。
    ordered = sorted(best, key=lambda u: (path_of[u]["depth"], u))
    children = {}
    for uid in ordered:
        parent = path_of[uid]["parent"]
        if parent is not None and parent in best:
            children.setdefault(parent, []).append(uid)

    display_tree = []
    for uid in ordered:
        info = path_of[uid]
        display_tree.append({
            "uid": uid, "name": field(uid, "name", "") or uid,
            "root_uid": info["root"], "depth": info["depth"], "parent_uid": info["parent"],
            "child_uids": sorted(children.get(uid, [])),
            "remaining": best[uid],
            "is_root": uid in root_reasons,
        })

    # ── 5. 交叉引用（环内 / 非树边）──
    tree_edges = {(info["parent"], uid) for uid, info in path_of.items() if info["parent"]}
    cross = [{"from_uid": a, "to_uid": b} for a, b in sorted(used_edges) if (a, b) not in tree_edges]

    # ── 6. 问题清单（已激活必要依赖的停用/缺失/空正文必须可解释）──
    issues = []
    for uid in sorted(best):
        if uid not in by_uid:
            issues.append({"code": "missing_entry", "severity": "error", "uid": uid,
                           "message": f"依赖引用了不存在的条目 {uid}"})
            continue
        if not field(uid, "enabled", True):
            issues.append({"code": "disabled_entry", "severity": "warning", "uid": uid,
                           "message": f"{field(uid, 'name', '') or uid} 已停用，不会注入"})
        content = field(uid, "content", "")
        if not isinstance(content, str) or not content.strip():
            issues.append({"code": "empty_content", "severity": "warning", "uid": uid,
                           "message": f"{field(uid, 'name', '') or uid} 正文为空，不会注入"})

    return {"book_id": book_id, "schema_version": SCHEMA_VERSION_V3,
            "policy_revision": policy_revision, "content_revision": content_revision,
            "roster_character_ids": sorted(roster),
            "active_roots": [{"entry_uid": r["entry_uid"],
                              "activation": r["activation"],
                              "expansion": r["expansion"],
                              "character_ids": r["character_ids"],
                              **({"max_depth": r["max_depth"]} if "max_depth" in r else {})}
                             for r in active_roots],
            "resolved_entry_uids": sorted(best),
            "resolved_edges": resolved_edges,
            "selection_reasons": {uid: reasons[uid] for uid in sorted(reasons)},
            "display_tree": display_tree,
            "cross_references": cross,
            "issues": issues,
            "resolved_at": time.time()}


def v2_rules_from_import_config(import_config, edges):
    """把 v2 配置无损映射为 v3 起点：fixed → always+none，sources → always+legacy_depth。

    世界观 / 阵容来源在 v2 里不是显式起点，先按等价保留——只有用户显式预览并保存后
    才采纳新的按需规则（旧 v2 会话不静默改变语义）。
    """
    roots = []
    for uid in import_config.get("fixed_entry_uids", []):
        roots.append({"entry_uid": uid, "activation": ACTIVATION_ALWAYS,
                      "expansion": EXPANSION_NONE, "character_ids": []})
    for source in import_config.get("dependency_sources", []):
        roots.append({"entry_uid": source["entry_uid"], "activation": ACTIVATION_ALWAYS,
                      "expansion": EXPANSION_LEGACY_DEPTH, "character_ids": [],
                      "max_depth": source["max_depth"]})
    known = {r["entry_uid"] for r in roots}
    return ({"roots": roots, "root_rule": {"entry_uids": sorted(known)}},
            list(edges), [])
