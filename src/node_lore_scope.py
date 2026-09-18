# -*- coding: utf-8 -*-
"""节点级世界书动态载入 —— 绑定解码 + 作用域求解（纯函数，不进注入路径）。

设计文档：docs/node-scoped-worldbook-loading.md（v2.1）。

绑定面是世界书里一条**永不注入**的 `lore_bindings` 条目（围栏 JSON +
`raw.extensions.arknights_tavern.entry_type` 标记，与 plot_graphs / combat_nodes
同一套无损往返模式）。本模块负责三件事：

1. 在书里找到并解出绑定载荷（`find_bindings` / `decode_bindings`）；
2. 按绑定把「当前剧情树节点该看见哪些条目」冻结成作用域 dict
   （`resolve_scope`）——只在节点落盘 / 回档补算时调用，注入路径零解析；
3. 作者侧校验（`validate_bindings`），配置错误显式暴露，不静默吞掉。

冻结作用域存进 `story_tree.nodes[].state.lore_scope`（随回档走），当前生效的
那一份镜像在 `overlay._data["lore_scope_active"]`，由 `eligible_uids_for`
取「会话范围 ∩ 节点作用域」做窄化白名单。
"""

import json
import logging
import re

from world_book import content_revision

logger = logging.getLogger(__name__)

WORLD_BOOK_FENCE = "arknights_tavern_lore_bindings"
_FENCE_RE = re.compile(
    r"```json\s+arknights_tavern_lore_bindings\s*\n(.*?)\n```", re.DOTALL)
_EXT_NAMESPACE = "arknights_tavern"
_ENTRY_TYPE = "lore_bindings"

SCHEMA_VERSION = 1
# 求解器版本：冻结作用域的结构/语义变更时 +1，旧作用域因 revision 不符自动重算。
SCOPE_RESOLVER_VERSION = 1

#: inject_position 允许覆盖的键（其余键忽略并报校验错）
_POSITION_KEYS = ("position", "depth", "group_weight")


def bindings_entry_uid(book_id: str) -> str:
    return f"lore_bindings_{book_id}"


# ── 条目识别与解码 ──

def _raw_ext(entry) -> dict:
    raw = getattr(entry, "raw", None) or {}
    return (raw.get("extensions") or {}).get(_EXT_NAMESPACE) or {}


def is_lore_bindings_entry(entry) -> bool:
    """判断世界书条目是否承载节点绑定（extensions 标记或围栏块）。"""
    if _raw_ext(entry).get("entry_type") == _ENTRY_TYPE:
        return True
    return bool(_FENCE_RE.search(str(getattr(entry, "content", "") or "")))


def decode_bindings(entry) -> dict | None:
    """从世界书条目解出 lore_bindings；非该类型或损坏返回 None（不抛错）。"""
    if not is_lore_bindings_entry(entry):
        return None
    content = str(getattr(entry, "content", "") or "")
    match = _FENCE_RE.search(content)
    if not match:
        logger.warning("lore_bindings 条目缺少 ```json %s 围栏块，忽略", WORLD_BOOK_FENCE)
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        logger.warning("lore_bindings 围栏块 JSON 解析失败，忽略")
        return None
    if not isinstance(data, dict):
        logger.warning("lore_bindings 内容不是 JSON 对象，忽略")
        return None
    return data


def encode_bindings_for_worldbook(payload: dict, book_id: str) -> dict:
    """生成可入库的世界书条目 dict。

    永不注入：空触发键且非常驻（`_entry_matches` 天然不命中）；
    触发键留空与 plot_graphs 的布局条目同一纪律。
    """
    body = dict(payload or {})
    body.setdefault("schema_version", SCHEMA_VERSION)
    body["book_id"] = book_id
    compact = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    lines = [f"```json {WORLD_BOOK_FENCE}", compact, "```"]
    return {
        "uid": bindings_entry_uid(book_id),
        "name": f"节点绑定：{book_id}",
        "content": "\n".join(lines),
        "trigger_keys": [],
        "raw": {
            "extensions": {
                _EXT_NAMESPACE: {
                    "entry_type": _ENTRY_TYPE,
                    "book_id": book_id,
                }
            }
        },
    }


def find_bindings(book) -> tuple[dict | None, str]:
    """在书里找唯一的 lore_bindings 条目，返回 (payload, fingerprint)。

    书内无绑定条目 → (None, "")——这是「默认关闭」的判定来源：
    无绑定的书注入行为与旧版字节一致。多条 → 取第一条并告警（不静默合并）。
    fingerprint = 绑定条目的 content_revision，决定重入是否重算（指纹未变 → 复用）。
    """
    matches = [e for e in (getattr(book, "entries", None) or [])
               if is_lore_bindings_entry(e)]
    if not matches:
        return None, ""
    if len(matches) > 1:
        logger.warning("世界书 %s 存在 %d 条 lore_bindings 条目，取第一条（%s）",
                       getattr(book, "id", "?"), len(matches),
                       getattr(matches[0], "uid", "?"))
    payload = decode_bindings(matches[0])
    if payload is None:
        return None, ""
    # 空 targets 视为「关闭」：避免作者手滑存了空绑定把全书注入清零
    if not (payload.get("targets") or {}):
        return None, ""
    return payload, content_revision([matches[0]])


# ── 关系图展开（冻结） ──

def freeze_neighbours(roots, related_edges, *, depth=1, known_uids=None) -> set:
    """从 roots 沿 related 边 BFS，返回冻结的邻居集合（不含根自身）。

    边是有向的（from_uid → to_uid），对齐 worldbook_scope 的展开语义。
    遍历穿透所有邻居，但只收集 known_uids 内的条目——known 之外的条目
    不影响「再往下一层还有什么」。
    """
    try:
        depth = max(0, int(depth))
    except (TypeError, ValueError):
        depth = 1
    known = set(known_uids) if known_uids is not None else None
    adjacency: dict[str, list[str]] = {}
    for edge in related_edges or []:
        src, dst = edge.get("from_uid"), edge.get("to_uid")
        if isinstance(src, str) and isinstance(dst, str):
            adjacency.setdefault(src, []).append(dst)
    result: set[str] = set()
    visited = {r for r in roots if isinstance(r, str)}
    frontier = sorted(visited)
    remaining = depth
    while frontier and remaining > 0:
        nxt: list[str] = []
        for uid in frontier:
            for tgt in sorted(adjacency.get(uid, [])):
                if tgt in visited:
                    continue
                visited.add(tgt)
                if known is None or tgt in known:
                    result.add(tgt)
                nxt.append(tgt)
        frontier = nxt
        remaining -= 1
    return result


# ── 作用域求解 ──

def resolve_scope(*, node_id: str, path_scopes: list,
                  beat_id: str = "", plot_id: str = "", chapter_title: str = "",
                  combat_id_hint: str = "",
                  bindings: dict, related_edges=None, known_uids=None,
                  bindings_fingerprint: str = "", book_id: str = "") -> dict:
    """算出一个节点的冻结作用域。只在节点落盘 / 回档补算时调用，不在注入路径上。

    Args:
        node_id:        剧情树节点 id（tree: 目标键的组成部分）。
        path_scopes:    祖先链（root → 父）各节点已冻结的 lore_scope，顺序稳定。
        beat_id:        当前节拍 id，由调用方用 (chapter_idx, beat_idx) 反查
                        （beat_state 本身不存 beat_id）。
        chapter_title:  章节绑定键用标题不用序号（章节号 1 起 / chapter_idx 0 起，
                        用序号必踩口径坑，见设计文档附录 B）。
        combat_id_hint: 本轮推进节拍【之前】读到的 [COMBAT:id]，由 chat.py 透传；
                        不能从节点 beat_state 反查（拍到的是推进后的新节拍）。
        known_uids:     会话范围 resolved_entry_uids ∩ enabled 且正文非空。
        bindings_fingerprint: 绑定条目 content_revision，写进作用域做幂等键。

    返回结构直接进 story_tree.nodes[node_id].state.lore_scope。
    """
    keys = [f"tree:{node_id}"]
    if beat_id:
        keys.append(f"beat:{beat_id}")
    if plot_id and chapter_title:
        keys.append(f"chapter:{plot_id}#{chapter_title}")
    if combat_id_hint:
        keys.append(f"combat:{combat_id_hint}")

    targets = (bindings or {}).get("targets") or {}
    known = set(known_uids or ())

    # ① 祖先链：只继承 sticky_uids——祖先的 sticky=false 条目（战斗、
    #    一次性揭示）到此为止，不下传；pinned / overrides 按同一 sticky 边界下传。
    inherited: set[str] = set()
    pinned: set[str] = set()
    overrides: dict[str, dict] = {}
    for sc in path_scopes or []:
        sticky_up = set((sc or {}).get("sticky_uids") or [])
        inherited |= sticky_up
        pinned |= set((sc or {}).get("pinned") or []) & sticky_up
        for uid, ov in ((sc or {}).get("overrides") or {}).items():
            if uid in sticky_up:
                overrides[uid] = ov  # 就近原则：更近的祖先顶替更远的；当前节点最后再顶

    # ② 当前节点命中的 target；sticky 是 target 级属性，分开收集
    explicit: set[str] = set()
    sticky_new: set[str] = set()
    expand_jobs: list[dict] = []
    for key in keys:
        tgt = targets.get(key) or {}
        if not isinstance(tgt, dict):
            continue
        uids = {u for u in (tgt.get("entry_uids") or [])
                if isinstance(u, str) and u in known}
        explicit |= uids
        if tgt.get("sticky", True):
            sticky_new |= uids
        if tgt.get("inject") == "always":
            pinned |= uids
        pos = tgt.get("inject_position")
        if isinstance(pos, dict):
            cleaned = {k: v for k, v in pos.items() if k in _POSITION_KEYS}
            if cleaned:
                for uid in uids:  # 就近原则：当前节点覆盖祖先
                    overrides[uid] = cleaned
        if isinstance(tgt.get("expand"), dict):
            expand_jobs.append(tgt)

    # ③ 关系图展开：冻结当时的结果，此后不再随世界书变更漂移。
    #    v1 只支持 related 语义（root_expansions 在节点作用域里降级为 related）。
    expanded: set[str] = set()
    for tgt in expand_jobs:
        exp = tgt["expand"]
        if str(exp.get("relation") or "related") != "related":
            logger.warning("节点绑定 expand 暂只支持 relation=related，按 related 处理")
        grown = freeze_neighbours(explicit, related_edges or [],
                                  depth=exp.get("depth", 1), known_uids=known)
        expanded |= grown
        if tgt.get("sticky", True):
            sticky_new |= grown

    dormant = {u for u in ((bindings or {}).get("dormant_uids") or [])
               if isinstance(u, str)}
    allowed = (inherited | explicit | expanded) - dormant
    allowed |= explicit & dormant  # 显式写名 = 当场解禁（dormant 是默认休眠，不是永久封印）

    return {
        "node_id": node_id,
        "book_id": book_id or str((bindings or {}).get("book_id") or ""),
        "keys": keys,
        "explicit": sorted(explicit),
        "sticky_uids": sorted(sticky_new),   # 后代只继承这个
        "inherited": sorted(inherited),
        "expanded": sorted(expanded),
        "allowed": sorted(allowed),
        "pinned": sorted(pinned & allowed),          # 钉入不能突破休眠
        "overrides": {u: overrides[u] for u in sorted(overrides) if u in allowed},
        "bindings_fingerprint": bindings_fingerprint,
        "revision": SCOPE_RESOLVER_VERSION,
    }


def build_resolver(book, *, known_uids, beat_id: str = "",
                   plot_id: str = "", chapter_title: str = ""):
    """构造 lore_resolver(node, prev_scope, nodes, combat_id_hint) 闭包。

    书内无绑定条目 → 返回 None（「默认关闭」：调用方按 None 跳过整条链路，
    注入行为与旧版一致）。beat_id / chapter_title 在闭包创建时捕获——
    每次 commit / 回档补算都新建闭包，因此捕获值总是当时刻的状态。
    """
    payload, fingerprint = find_bindings(book)
    if payload is None:
        return None
    related = list(getattr(book, "related_edges", None) or [])
    known = set(known_uids or ())
    book_id = getattr(book, "id", "") or str(payload.get("book_id") or "")

    def resolver(node, prev_scope, nodes, combat_id_hint: str = ""):
        # 幂等键：绑定文件没变 + 求解器版本没变 → 直接复用，零解析
        if (isinstance(prev_scope, dict)
                and prev_scope.get("bindings_fingerprint") == fingerprint
                and prev_scope.get("revision") == SCOPE_RESOLVER_VERSION):
            return prev_scope
        path_scopes: list = []
        seen: set[str] = set()
        pid = (node or {}).get("parent_id")
        nodes = nodes or {}
        while pid and pid in nodes and pid not in seen:
            seen.add(pid)
            ancestor = nodes[pid]
            path_scopes.append((ancestor.get("state") or {}).get("lore_scope"))
            pid = ancestor.get("parent_id")
        path_scopes.reverse()  # root → 父
        return resolve_scope(
            node_id=str((node or {}).get("id") or ""),
            path_scopes=path_scopes,
            beat_id=beat_id, plot_id=plot_id, chapter_title=chapter_title,
            combat_id_hint=combat_id_hint or "",
            bindings=payload, related_edges=related, known_uids=known,
            bindings_fingerprint=fingerprint, book_id=book_id,
        )

    return resolver


def build_overlay_resolver(book, overlay):
    """用 overlay 当前状态构造 lore_resolver；功能关闭时返回 None。

    关闭情形（调用方按 None 跳过整条链路，注入行为与旧版一致）：
    书为 None / overlay 为 None / 书内无 lore_bindings 条目 / 会话无剧情树。
    known_uids = 会话范围 resolved_entry_uids ∩（enabled 且正文非空）；
    老会话无 scope 快照时退化为「全书 enabled 且非空」。
    """
    if book is None or overlay is None:
        return None
    if not overlay.get_story_tree().get("nodes"):
        return None
    enabled = {e.uid for e in (getattr(book, "entries", None) or [])
               if e.enabled and (e.content or "").strip()}
    scope = overlay.get_worldbook_scope() or {}
    scope_uids = set(scope.get("resolved_entry_uids") or [])
    known = (scope_uids & enabled) if scope_uids else enabled
    return build_resolver(
        book, known_uids=known,
        beat_id=overlay.get_current_beat_id(),
        plot_id=str(overlay.get_plot_id() or ""),
        chapter_title=overlay.get_current_chapter_title(),
    )

# ── 作者侧校验 ──

def validate_bindings(book, payload) -> list[str]:
    """校验绑定载荷，返回错误列表（空 = 通过）。

    写入接口严格拒绝坏引用——配置错误必须暴露给作者，
    不能静默丢条目造成「看起来生效了」（对齐 validate_v3_rules 的纪律）。
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["绑定内容必须是 JSON 对象"]
    entries = {e.uid: e for e in (getattr(book, "entries", None) or [])}
    self_uid = next((e.uid for e in (getattr(book, "entries", None) or [])
                     if is_lore_bindings_entry(e)), None)

    targets = payload.get("targets") or {}
    if not isinstance(targets, dict):
        errors.append("targets 必须是对象")
        targets = {}
    for key, tgt in targets.items():
        if not isinstance(tgt, dict):
            errors.append(f"targets[{key}] 必须是对象")
            continue
        uids = tgt.get("entry_uids") or []
        if not isinstance(uids, list):
            errors.append(f"targets[{key}].entry_uids 必须是数组")
            continue
        for uid in uids:
            if not isinstance(uid, str) or not uid:
                errors.append(f"targets[{key}] 含无效 uid: {uid!r}")
                continue
            if self_uid and uid == self_uid:
                errors.append(f"targets[{key}] 不允许引用绑定条目自身: {uid}")
                continue
            entry = entries.get(uid)
            if entry is None:
                errors.append(f"targets[{key}] 引用了不存在的条目: {uid}")
                continue
            if not entry.enabled or not (entry.content or "").strip():
                errors.append(f"targets[{key}] 引用的条目已停用或正文为空: {uid}")
            # 常驻条目进稳定层，节点切换会打碎 API 前缀缓存——绑定层禁止引用
            if entry.always_active:
                errors.append(
                    f"targets[{key}] 引用的条目是常驻条目（always_active），禁止绑定: {uid}")
        inject = tgt.get("inject", "match")
        if inject not in ("match", "always"):
            errors.append(f"targets[{key}].inject 必须是 match / always")
        pos = tgt.get("inject_position")
        if pos is not None:
            if not isinstance(pos, dict):
                errors.append(f"targets[{key}].inject_position 必须是对象")
            else:
                for pk in pos:
                    if pk not in _POSITION_KEYS:
                        errors.append(f"targets[{key}].inject_position 含未知键: {pk}")
        exp = tgt.get("expand")
        if exp is not None and not isinstance(exp, dict):
            errors.append(f"targets[{key}].expand 必须是对象")

    dormant = payload.get("dormant_uids") or []
    if not isinstance(dormant, list):
        errors.append("dormant_uids 必须是数组")
    elif self_uid and self_uid in dormant:
        errors.append(f"dormant_uids 不允许引用绑定条目自身: {self_uid}")
    return errors
