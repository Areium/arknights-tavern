"""会话级世界书依赖覆盖：继承快照 - 屏蔽 + 本地覆盖。"""

from __future__ import annotations

import copy
import hashlib
import json
import time

RELATIONS = ("requires", "related")


def _edge_key(edge):
    if not isinstance(edge, dict):
        return None
    a, b = edge.get("from_uid"), edge.get("to_uid")
    if not isinstance(a, str) or not a or not isinstance(b, str) or not b or a == b:
        return None
    return a, b


def _edges(values):
    out, seen = [], set()
    for raw in values or []:
        pair = _edge_key(raw)
        if pair is None or pair in seen:
            continue
        seen.add(pair)
        out.append({"from_uid": pair[0], "to_uid": pair[1]})
    return out


def _suppressed(values):
    out, seen = [], set()
    for raw in values or []:
        pair = _edge_key(raw)
        relation = raw.get("relation") if isinstance(raw, dict) else None
        if pair is None or relation not in RELATIONS or (relation, pair) in seen:
            continue
        seen.add((relation, pair))
        out.append({"from_uid": pair[0], "to_uid": pair[1], "relation": relation})
    return out


def _inheritance_from_scope(scope: dict) -> dict:
    return {
        "policy_revision": int(scope.get("policy_revision") or 1),
        "content_revision": str(scope.get("content_revision") or ""),
        "resolver_version": scope.get("resolver_version"),
        "rules": copy.deepcopy(scope.get("rules") or {"roots": []}),
        "requires_edges": _edges(scope.get("requires_edges") or scope.get("dependency_edges")),
        "related_edges": _edges(scope.get("related_edges")),
        "captured_at": float(scope.get("resolved_at") or time.time()),
    }


def normalize_scope(scope: dict | None) -> dict:
    value = copy.deepcopy(scope) if isinstance(scope, dict) else {}
    inheritance = value.get("inheritance")
    if not isinstance(inheritance, dict):
        inheritance = _inheritance_from_scope(value)
    else:
        inheritance = {**copy.deepcopy(inheritance),
                       "rules": copy.deepcopy(inheritance.get("rules") or {"roots": []}),
                       "requires_edges": _edges(inheritance.get("requires_edges")),
                       "related_edges": _edges(inheritance.get("related_edges"))}
    overrides = value.get("local_overrides") if isinstance(value.get("local_overrides"), dict) else {}
    value.update({
        "inheritance": inheritance,
        "local_overrides": {
            "requires_edges": _edges(overrides.get("requires_edges")),
            "related_edges": _edges(overrides.get("related_edges")),
            "root_expansions": {str(uid): expansion for uid, expansion in
                (overrides.get("root_expansions") or {}).items()
                if expansion in ("none", "requires_closure", "legacy_depth")},
        },
        "suppressed_edges": _suppressed(value.get("suppressed_edges")),
        "scope_revision": max(1, int(value.get("scope_revision") or 1)),
    })
    value.setdefault("inheritance_conflicts", [])
    return value


def ensure_editable_scope(scope: dict | None, book, roster_character_ids=None) -> dict:
    """把旧书/旧会话范围只在本会话内升级成范围等价的 v3 快照。"""
    value = copy.deepcopy(scope) if isinstance(scope, dict) else {}
    if value.get("schema_version") == 3 and value.get("rules"):
        return normalize_scope(value)
    local_book = copy.deepcopy(book)
    if not local_book.v3_enabled:
        local_book.adopt_v2_as_v3()
    manual = value.get("manual_entry_uids") or []
    full_scope = bool(value.get("full_scope") or value.get("legacy_full_scope")
                      and value.get("scope_mode") == "legacy")
    upgraded = local_book.session_scope_snapshot(
        roster_character_ids or value.get("roster_character_ids") or [], manual,
        full_scope=full_scope)
    return normalize_scope(upgraded)


def effective_graph(scope: dict | None) -> dict:
    value = normalize_scope(scope)
    suppressed = {(x["relation"], x["from_uid"], x["to_uid"])
                  for x in value["suppressed_edges"]}
    maps = {relation: {} for relation in RELATIONS}
    origins = {}
    for relation in RELATIONS:
        field = f"{relation}_edges"
        for edge in value["inheritance"].get(field, []):
            pair = _edge_key(edge)
            if pair and (relation, *pair) not in suppressed:
                maps[relation][pair] = edge
                origins[f"{relation}:{pair[0]}|{pair[1]}"] = "inherited"
    for relation in RELATIONS:
        other = "related" if relation == "requires" else "requires"
        field = f"{relation}_edges"
        for edge in value["local_overrides"].get(field, []):
            pair = _edge_key(edge)
            if pair:
                maps[other].pop(pair, None)
                origins.pop(f"{other}:{pair[0]}|{pair[1]}", None)
                maps[relation][pair] = edge
                origins[f"{relation}:{pair[0]}|{pair[1]}"] = "local"
    return {"requires_edges": _edges(maps["requires"].values()),
            "related_edges": _edges(maps["related"].values()), "origins": origins}


def effective_rules(scope: dict | None) -> dict:
    value = normalize_scope(scope)
    rules = copy.deepcopy(value["inheritance"].get("rules") or {"roots": []})
    expansions = value["local_overrides"].get("root_expansions") or {}
    for root in rules.get("roots") or []:
        uid = root.get("entry_uid") if isinstance(root, dict) else None
        if uid in expansions:
            root["expansion"] = expansions[uid]
            root["session_override"] = True
            if expansions[uid] != "legacy_depth":
                root.pop("max_depth", None)
    return rules


def _fingerprint(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def graph_view(scope: dict | None) -> dict:
    value, graph = normalize_scope(scope), effective_graph(scope)
    return {"scope_revision": value["scope_revision"],
            "inheritance": value["inheritance"],
            "local_overrides": value["local_overrides"],
            "suppressed_edges": value["suppressed_edges"],
            "effective_requires_edges": graph["requires_edges"],
            "effective_related_edges": graph["related_edges"],
            "effective_rules": effective_rules(value),
            "edge_origins": graph["origins"],
            "conflicts": value.get("inheritance_conflicts") or [],
            "revision_hash": _fingerprint({"revision": value["scope_revision"],
                "inheritance": value["inheritance"], "overrides": value["local_overrides"],
                "suppressed": value["suppressed_edges"]})}


def change_relation(scope: dict, from_uid: str, to_uid: str,
                    relation: str | None, expected_revision: int,
                    enable_source_expansion: bool = False) -> dict:
    value = normalize_scope(scope)
    if int(expected_revision) != value["scope_revision"]:
        raise RuntimeError("会话依赖已被其他操作更新，请刷新后重试")
    pair = _edge_key({"from_uid": from_uid, "to_uid": to_uid})
    if pair is None:
        raise ValueError("依赖关系的起点和终点必须是不同的有效 UID")
    if relation not in (*RELATIONS, None, "none"):
        raise ValueError("relation 必须是 requires、related 或 none")
    for rel in RELATIONS:
        field = f"{rel}_edges"
        value["local_overrides"][field] = [e for e in value["local_overrides"][field]
                                             if _edge_key(e) != pair]
    value["suppressed_edges"] = [e for e in value["suppressed_edges"] if _edge_key(e) != pair]
    if relation in RELATIONS:
        value["local_overrides"][f"{relation}_edges"].append(
            {"from_uid": pair[0], "to_uid": pair[1]})
        other = "related" if relation == "requires" else "requires"
        if any(_edge_key(e) == pair for e in value["inheritance"].get(f"{other}_edges", [])):
            value["suppressed_edges"].append(
                {"from_uid": pair[0], "to_uid": pair[1], "relation": other})
        if relation == "requires" and enable_source_expansion:
            value["local_overrides"]["root_expansions"][pair[0]] = "requires_closure"
    else:
        # 删除的是有效 pair，而不是某个来源标签；同时屏蔽两种继承关系，
        # 之后全局把 requires 改成 related 也不会让它在本会话复活。
        for rel in RELATIONS:
            value["suppressed_edges"].append(
                {"from_uid": pair[0], "to_uid": pair[1], "relation": rel})
    if relation != "requires" and not any(
            e["from_uid"] == pair[0]
            for e in value["local_overrides"]["requires_edges"]):
        value["local_overrides"]["root_expansions"].pop(pair[0], None)
    value["scope_revision"] += 1
    return value


def restore_inheritance(scope: dict, expected_revision: int,
                        from_uid: str | None = None, to_uid: str | None = None) -> dict:
    value = normalize_scope(scope)
    if int(expected_revision) != value["scope_revision"]:
        raise RuntimeError("会话依赖已被其他操作更新，请刷新后重试")
    pair = (from_uid, to_uid) if from_uid and to_uid else None
    if bool(from_uid) != bool(to_uid):
        raise ValueError("恢复单条继承时必须同时提供 from_uid 和 to_uid")
    for rel in RELATIONS:
        field = f"{rel}_edges"
        value["local_overrides"][field] = [e for e in value["local_overrides"][field]
                                             if pair is not None and _edge_key(e) != pair]
    value["suppressed_edges"] = [e for e in value["suppressed_edges"]
                                  if pair is not None and _edge_key(e) != pair]
    if pair is None:
        value["local_overrides"]["root_expansions"] = {}
    elif not any(e["from_uid"] == pair[0]
                 for e in value["local_overrides"]["requires_edges"]):
        value["local_overrides"]["root_expansions"].pop(pair[0], None)
    value["scope_revision"] += 1
    return value


def preview_inheritance_update(scope: dict, book) -> dict:
    value = normalize_scope(scope)
    current_book = copy.deepcopy(book)
    if not current_book.v3_enabled:
        current_book.adopt_v2_as_v3()
    fresh = current_book.session_scope_snapshot(value.get("roster_character_ids") or [],
        value.get("manual_entry_uids") or [], None, bool(value.get("full_scope")))
    old, new = value["inheritance"], _inheritance_from_scope(fresh)
    changes, conflicts, rule_changes = [], [], []
    local = {}
    for rel in RELATIONS:
        for edge in value["local_overrides"][f"{rel}_edges"]:
            local[_edge_key(edge)] = rel
        before = {_edge_key(e) for e in old.get(f"{rel}_edges", [])}
        after = {_edge_key(e) for e in new.get(f"{rel}_edges", [])}
        for kind, pairs in (("added", after - before), ("removed", before - after)):
            changes += [{"kind": kind, "relation": rel, "from_uid": p[0], "to_uid": p[1]}
                        for p in sorted(pairs)]
    for pair, local_rel in local.items():
        inherited_rel = next((rel for rel in RELATIONS
            if pair in {_edge_key(e) for e in new.get(f"{rel}_edges", [])}), None)
        if inherited_rel and inherited_rel != local_rel:
            conflicts.append({"from_uid": pair[0], "to_uid": pair[1],
                "inherited_relation": inherited_rel, "local_relation": local_rel,
                "resolution": "local_wins"})
    old_roots = {root.get("entry_uid"): root for root in (old.get("rules") or {}).get("roots", [])
                 if isinstance(root, dict) and root.get("entry_uid")}
    new_roots = {root.get("entry_uid"): root for root in (new.get("rules") or {}).get("roots", [])
                 if isinstance(root, dict) and root.get("entry_uid")}
    for uid in sorted(set(old_roots) | set(new_roots)):
        before, after = old_roots.get(uid), new_roots.get(uid)
        if before != after:
            rule_changes.append({"entry_uid": uid,
                "kind": "added" if before is None else "removed" if after is None else "changed",
                "before": before, "after": after})
    before_scope = set(value.get("resolved_entry_uids") or [])
    simulated = copy.deepcopy(value)
    simulated["inheritance"] = copy.deepcopy(new)
    simulated["inheritance_conflicts"] = copy.deepcopy(conflicts)
    simulated_scope = current_book.refresh_session_scope(
        simulated, value.get("roster_character_ids") or [])
    after_scope = set(simulated_scope.get("resolved_entry_uids") or [])
    result = {"expected_scope_revision": value["scope_revision"],
        "from_policy_revision": old.get("policy_revision"),
        "to_policy_revision": new.get("policy_revision"), "changes": changes,
        "rule_changes": rule_changes,
        "scope_added": sorted(after_scope - before_scope),
        "scope_removed": sorted(before_scope - after_scope),
        "conflicts": conflicts, "new_inheritance": new}
    stable_new = {key: new.get(key) for key in (
        "policy_revision", "content_revision", "resolver_version", "rules",
        "requires_edges", "related_edges")}
    result["preview_hash"] = _fingerprint({**result, "new_inheritance": stable_new})
    return result


def apply_inheritance_update(scope: dict, preview: dict, expected_revision: int,
                             preview_hash: str) -> dict:
    value = normalize_scope(scope)
    if int(expected_revision) != value["scope_revision"] or preview_hash != preview.get("preview_hash"):
        raise RuntimeError("继承更新预览已过期，请重新预览")
    value["inheritance"] = copy.deepcopy(preview["new_inheritance"])
    value["inheritance_conflicts"] = copy.deepcopy(preview.get("conflicts") or [])
    value["scope_revision"] += 1
    return value
