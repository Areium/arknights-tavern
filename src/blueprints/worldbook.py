"""
Worldbook blueprint — 世界书（酒馆 Lorebook 兼容）管理 API。

路由：
    GET    /api/worldbook                       列出所有书
    POST   /api/worldbook                       新建空书
    POST   /api/worldbook/import               导入（JSON body 或文件上传）
    GET    /api/worldbook/<book_id>            书详情（含条目）
    PUT    /api/worldbook/<book_id>            更新书元信息
    DELETE /api/worldbook/<book_id>            删除书
    POST   /api/worldbook/<book_id>/entries    新增条目
    PUT    /api/worldbook/<book_id>/entries/<entry_id>   更新条目
    DELETE /api/worldbook/<book_id>/entries/<entry_id>   删除条目
    GET    /api/worldbook/<book_id>/export     导出酒馆 v1 格式（回灌用）
    PUT    /api/worldbook/<book_id>/taxonomy   更新分类树与条目归属
    POST   /api/worldbook/<book_id>/auto-classify  按条目元数据自动分类（预览 / 应用）
    POST   /api/worldbook/<book_id>/default    设为/取消全局默认书
    POST   /api/worldbook/<book_id>/bind       绑定到会话（或解绑）
    GET    /api/worldbook/resolve              查询会话当前生效的书
"""

import json
import logging
import threading
import uuid
import copy
import hashlib
from contextlib import contextmanager

from flask import Blueprint, jsonify, request, g

from shared.helpers import json_error
from world_book import (
    RESOLVER_VERSION, WorldBook, WorldBookEntry, apply_auto_classification,
    auto_classification_patch, content_revision, estimate_tokens,
)
from worldbook_classify import classify_entries
from worldbook_builder import (
    AnalysisCache, DependencyJobStore, auto_budget, build_to_v3_rules,
    content_hash, evidence_locatable, model_identity, run_build,
)
from worldbook_scope import (
    ACTIVATION_ALWAYS, ACTIVATION_MANUAL, ACTIVATION_ROSTER_ANY,
    EXPANSION_LEGACY_DEPTH, EXPANSION_NONE, EXPANSION_REQUIRES_CLOSURE,
    SCHEMA_VERSION_V3, validate_categories, validate_policy, validate_v3_rules,
)

logger = logging.getLogger(__name__)

# 依赖构建任务表（进程级）。任务本身持久化到磁盘，重启后仍可查询。
_JOB_STORE = DependencyJobStore()
_ANALYSIS_CACHE = AnalysisCache()


def _union_edges(first, second) -> list[dict]:
    """按 (from, to) 去重合并两组边（用于人工拒绝 / 锁定等持久化集合）。"""
    out, seen = [], set()
    for edge in list(first) + list(second):
        if not isinstance(edge, dict):
            continue
        pair = (edge.get("from_uid"), edge.get("to_uid"))
        if pair in seen or not all(isinstance(x, str) and x for x in pair):
            continue
        seen.add(pair)
        out.append({"from_uid": pair[0], "to_uid": pair[1]})
    return out


def _apply_full_scope(payload: dict, book) -> dict:
    """把预览结果改成「本次会话显式全量兼容」。

    v2 与 v3 都走这一条：范围真的换成全量，预览与实际创建保持一致，
    只影响本次会话，不改动这本书的规则。
    """
    full = [e for e in book.entries if e.enabled and (e.content or "").strip()]
    uids = sorted(e.uid for e in full)
    costs = {e.uid: estimate_tokens(e.content) for e in full}
    total = sum(costs.values())
    scope = dict(payload.get("scope") or {})
    scope.update({
        "resolved_entry_uids": uids,
        "selection_reasons": {uid: ["full_scope"] for uid in uids},
        "legacy_full_scope": True,
        "full_scope": True,
    })
    payload.update({
        "scope": scope,
        "full_scope": True,
        "entry_count": len(uids),
        "resolved_estimated_tokens": total,
        "saved_estimated_tokens": 0,
        "saved_percent": 0.0,
        "warnings": ["已选择「本次会话全量兼容」：这次会载入全部启用条目，"
                     "只影响本会话，不改变这本书的规则。"] + list(payload.get("warnings") or []),
    })
    return payload


def _ai_evidence_issues(book) -> list[dict]:
    """Report stale evidence for applied AI roots/edges without disabling them."""
    by_uid = {entry.uid: entry for entry in book.entries}
    issues = []
    rules = book.dependency_rules or {}
    for root in rules.get("roots", []):
        if not isinstance(root, dict) or root.get("origin") != "llm":
            continue
        uid = root.get("entry_uid")
        entry = by_uid.get(uid)
        stale = (entry is None
                 or root.get("source_content_hash") != content_hash(entry.content or "")
                 or not evidence_locatable(root.get("evidence"), [entry]))
        if stale:
            issues.append({"code": "ai_root_evidence_stale", "severity": "warning", "uid": uid,
                           "message": f"AI 起点 {getattr(entry, 'name', '') or uid} 的原文证据已过期，请重新构建或人工复核"})
    formal = {(edge.get("from_uid"), edge.get("to_uid"))
              for edge in list(book.dependency_edges or []) + list(book.related_edges or [])
              if isinstance(edge, dict)}
    for key, meta in (rules.get("edge_meta") or {}).items():
        if not isinstance(meta, dict) or meta.get("origin") != "llm" or "|" not in key:
            continue
        a, b = key.split("|", 1)
        if (a, b) not in formal:
            continue
        source, target = by_uid.get(a), by_uid.get(b)
        stale = (source is None or target is None
                 or meta.get("source_content_hash") != content_hash(source.content or "")
                 or meta.get("target_content_hash") != content_hash(target.content or "")
                 or not evidence_locatable(meta.get("evidence"), [source, target]))
        if stale:
            issues.append({"code": "ai_edge_evidence_stale", "severity": "warning", "uid": a,
                           "from_uid": a, "to_uid": b,
                           "message": f"AI 关系 {a} → {b} 的原文证据已过期；关系仍保留，请重新构建或人工复核"})
    return issues


def _merge_v3_payload(manual: dict, proposal: dict = None, existing: dict = None) -> dict:
    """把人工草稿与 AI 建议并入同一个 v3 规则集（人工优先，重复项跳过）。

    顺序很重要：人工起点先占位，AI 只补人工没有的；边按 (from, to) 去重。
    这样「应用构建结果」是**追加**，不会静默重置用户已配好的起点与依赖。

    `rejected`（人工删除过的建议）与 `edge_meta`（边的来源与证据）一并保留：
    删掉一条 AI 边之后再次应用，不能把它复活。
    """
    proposal = proposal or {}
    existing = existing or {}
    locked = {r.get("entry_uid") for r in existing.get("roots", [])
              if isinstance(r, dict) and r.get("locked")}

    roots = []
    seen = set()
    for root in list(manual.get("roots", [])) + list(proposal.get("roots", [])):
        if not isinstance(root, dict) or not root.get("entry_uid"):
            continue
        uid = root["entry_uid"]
        if uid in seen:
            continue
        seen.add(uid)
        roots.append({**root, "locked": True} if uid in locked else root)
    # 人工锁定但两边都没出现的起点：必须保留
    for root in existing.get("roots", []):
        if not isinstance(root, dict) or not root.get("entry_uid"):
            continue
        if root.get("locked") and root["entry_uid"] not in seen:
            seen.add(root["entry_uid"])
            roots.append({**root, "locked": True})

    def union(first, second):
        out, pairs = [], set()
        for edge in list(first) + list(second):
            if not isinstance(edge, dict):
                continue
            pair = (edge.get("from_uid"), edge.get("to_uid"))
            if pair in pairs:
                continue
            pairs.add(pair)
            out.append(edge)
        return out

    rejected = union(existing.get("rejected", []), manual.get("rejected", []))
    edge_meta = {k: dict(v) for k, v in (existing.get("edge_meta") or {}).items()
                 if isinstance(v, dict)}
    for key, value in (proposal.get("edge_meta") or {}).items():
        if isinstance(value, dict):
            edge_meta[key] = {**edge_meta.get(key, {}), **value}

    manual_requires = union(manual.get("requires_edges", []), [])
    manual_related = union(manual.get("related_edges", []), [])
    manual_requires_pairs = {(e.get("from_uid"), e.get("to_uid")) for e in manual_requires}
    manual_related_pairs = {(e.get("from_uid"), e.get("to_uid")) for e in manual_related}
    proposal_requires = [e for e in proposal.get("requires_edges", [])
                         if (e.get("from_uid"), e.get("to_uid")) not in manual_related_pairs]
    proposal_related = [e for e in proposal.get("related_edges", [])
                        if (e.get("from_uid"), e.get("to_uid")) not in manual_requires_pairs]
    return {
        "roots": roots,
        "requires_edges": union(manual_requires, proposal_requires),
        "related_edges": union(manual_related, proposal_related),
        "rejected": rejected,
        "edge_meta": edge_meta,
    }


def _entry_from_payload(payload: dict, uid: str = None) -> WorldBookEntry:
    """从请求体构建 WorldBookEntry（仅白名单字段）。"""
    if not isinstance(payload, dict):
        raise ValueError("条目数据必须是对象")
    content = str(payload.get("content", "") or "")
    if not content.strip():
        raise ValueError("条目内容不能为空")
    return WorldBookEntry(
        uid=str(uid or payload.get("uid") or uuid.uuid4().hex[:10]),
        name=str(payload.get("name", "") or ""),
        content=content,
        trigger_keys=[str(k) for k in (payload.get("trigger_keys") or [])],
        secondary_keys=[str(k) for k in (payload.get("secondary_keys") or [])],
        always_active=bool(payload.get("always_active", False)),
        selective=bool(payload.get("selective", True)),
        enabled=bool(payload.get("enabled", True)),
        position=1 if int(payload.get("position", 0) or 0) else 0,
        depth=max(0, int(payload.get("depth", 4))),
        scan_depth=max(1, int(payload.get("scan_depth", 4) or 4)),
        probability=max(0, min(100, int(payload.get("probability", 100)))),
        group=str(payload.get("group", "") or ""),
        group_weight=int(payload.get("group_weight", 100) or 100),
        case_sensitive=bool(payload.get("case_sensitive", False)),
        match_whole_words=bool(payload.get("match_whole_words", False)),
        category_id=str(payload.get("category_id", "") or "unclassified"),
        character_id=str(payload.get("character_id", "") or "").strip(),
    )


def _validate_entry_scope(book, entry):
    if entry.category_id not in {c["id"] for c in book.categories}:
        raise ValueError("条目引用了不存在的分类")
    kind = book.category_scope_type(entry.category_id)
    if kind == "character" and not entry.character_id:
        raise ValueError("角色分类的条目必须关联角色标识（角色目录名）")
    if kind != "character" and entry.character_id:
        raise ValueError("非角色分类不可关联角色；请清空角色标识")


def _decode_upload(raw: bytes) -> str:
    """尝试多种编码解码上传文件内容。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _try_json(text: str):
    """尝试把文本解析为单个 JSON 对象，失败返回 None。"""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _looks_like_card(obj) -> bool:
    """判断 JSON 对象是否为 SillyTavern 角色卡（含角色身份字段）。"""
    if not isinstance(obj, dict):
        return False
    data = obj.get("data") if isinstance(obj.get("data"), dict) else obj
    if not isinstance(data, dict) or not data.get("name"):
        return False
    return (
        isinstance(data.get("character_book"), dict)
        or isinstance(obj.get("character_book"), dict)
        or bool(data.get("first_mes"))
        or bool(data.get("personality"))
        or bool(data.get("description"))
        or bool(data.get("scenario"))
    )


def _parse_card_or_error(raw: bytes):
    """尝试解析角色卡（PNG/JSON），失败返回 None。"""
    try:
        from character_card import CharacterCardError, parse_character_card
        return parse_character_card(raw)
    except CharacterCardError as exc:
        logger.warning("角色卡解析失败: %s", exc)
        return None
    except Exception as exc:
        logger.warning("角色卡解析异常: %s", exc)
        return None


def _import_card_character(card_result: dict, managers: dict):
    """把角色卡中的角色写入 data/characters（连带导入内嵌世界书场景共用）。"""
    from character_card import write_character_dir
    from shared.cache import invalidate_all_caches
    character = write_character_dir(
        card_result["meta"], card_result["image_bytes"])
    try:
        import index_manager as idxmgr
        invalidate_all_caches(idxmgr, managers.get("wiki"))
    except Exception:
        pass
    return character


def _import_combat_nodes(book) -> dict:
    """把世界书里的战斗节点条目落地为 `data/combat/nodes/*.json`。

    失败不影响世界书本身导入成功：错误逐条返回，编辑器可提示用户修正。
    """
    try:
        from combat_data_loader import CombatDataLoader
        from combat_nodes import import_worldbook_nodes
        entries = [e.to_dict() for e in book.entries]
        enemies = set(CombatDataLoader().list_enemy_names())
        return import_worldbook_nodes(entries, book_id=book.id, enemy_names=enemies)
    except Exception as exc:  # 节点导入是附加能力，绝不阻断世界书导入
        logger.warning("世界书战斗节点导入失败 (%s): %s", getattr(book, "id", "?"), exc)
        return {"imported": [], "skipped": [], "errors": [str(exc)]}


def _refresh_combat_node_entries(book) -> int:
    """导出前把战斗节点条目的 content 从注册表回灌（节点侧编辑不丢）。"""
    from combat_nodes import (
        NodeError, encode_node_for_worldbook, decode_worldbook_entry, load_node_file,
    )

    updated = 0
    for entry in book.entries:
        payload = entry.to_dict()
        try:
            # 以围栏块内容为准解析 node_id（raw.extensions 在部分导入路径会被规范化掉）
            data = decode_worldbook_entry(payload)
        except NodeError as exc:
            logger.warning("战斗节点条目解析失败，导出时跳过: %s", exc)
            continue
        if not data:
            continue
        node_id = str(data.get("node_id") or "")
        node = load_node_file(node_id) if node_id else None
        if not node:
            continue
        fresh = encode_node_for_worldbook(node)
        entry.content = fresh["content"]
        entry.trigger_keys = fresh["trigger_keys"]
        entry.name = fresh["name"]
        entry.raw = {**(payload.get("raw") or {}), **fresh["raw"]}
        updated += 1
    return updated


def register(app, managers):
    bp = Blueprint("worldbook", __name__)
    wb_mgr = managers["worldbook"]
    session_mgr = managers.get("session")

    @bp.before_request
    def serialize_book_operations():
        # Also covers export refresh, reinstall, metadata and job start/retry.
        book_id = (request.view_args or {}).get("book_id")
        if book_id:
            lock = wb_mgr.book_lock(book_id)
            lock.acquire()
            g.worldbook_lock = lock

    @bp.teardown_request
    def release_book_lock(_error):
        lock = g.pop("worldbook_lock", None)
        if lock is not None:
            lock.release()

    def _get_book_or_404(book_id):
        book = wb_mgr.load(book_id)
        if not book:
            return None, json_error("世界书不存在", 404)
        return copy.deepcopy(book), None

    @contextmanager
    def _locked_book(book_id):
        """所有写路径共用同一把每书锁，覆盖「读取 → 校验 → 提交」全过程。

        之前只有 `/configuration` 加锁，条目 CRUD / 分类 / 自动分类 / 导入配置
        仍在锁外做整书读改写：两个请求交错时，后提交的会把先提交的更新整段覆盖掉
        （例如先改了条目、再保存起点，起点保存会把条目改动回滚）。
        """
        with wb_mgr.book_lock(book_id):
            book = wb_mgr.load(book_id)
            if not book:
                yield None, json_error("世界书不存在", 404)
                return
            yield copy.deepcopy(book), None

    def _book_detail(book: "WorldBook", include_entries: bool = True) -> dict:
        detail = {
            "id": book.id,
            "name": book.name,
            "source_format": book.source_format,
            "source": book.source,
            "is_preinstalled": wb_mgr.is_preinstalled(book.id),
            "enabled": book.enabled,
            "budget_tokens": book.budget_tokens,
            "created_at": book.created_at,
            "updated_at": book.updated_at,
            "entry_count": len(book.entries),
            "is_default": wb_mgr.get_default_book_id() == book.id,
            "schema_version": book.schema_version,
            "scope_mode": book.scope_mode,
            "categories": book.categories,
            "dependency_edges": book.dependency_edges,
            "import_config": book.import_config,
            "dependency_rules": book.dependency_rules,
            "related_edges": book.related_edges,
            "content_revision": content_revision(book.entries),
            "resolver_version": RESOLVER_VERSION,
            "policy_revisions": [{"revision": item["revision"],
                                  "resolver_version": item["resolver_version"],
                                  "created_at": item["created_at"]}
                                 for item in book.policy_revisions],
            "evidence_issues": _ai_evidence_issues(book),
        }
        if include_entries:
            detail["entries"] = [e.to_dict() for e in book.entries]
        return detail

    # ── 1. 书列表 / 创建 ──

    @bp.route("/api/worldbook", methods=["GET"])
    def list_books():
        return jsonify({"books": wb_mgr.list_books()})

    @bp.route("/api/worldbook", methods=["POST"])
    def create_book():
        data = request.json or {}
        name = str(data.get("name", "") or "").strip() or "未命名世界书"
        try:
            budget = int(data.get("budget_tokens", 0) or 0)
        except (TypeError, ValueError):
            budget = 0
        book = wb_mgr.create_book(name, budget_tokens=max(0, budget))
        return jsonify({"book": _book_detail(book, include_entries=False)}), 201

    # ── 2. 导入 ──

    @bp.route("/api/worldbook/import", methods=["POST"])
    def import_book():
        name = ""
        source = None
        card_result = None  # 角色卡解析结果；非 None 时连带导入角色（角色/开场白可入队使用）

        if "file" in request.files and request.files["file"]:
            f = request.files["file"]
            name = str(request.form.get("name", "") or "").strip() or f.filename
            raw = f.read()
            if raw.startswith(b"\x89PNG"):
                # PNG 角色卡：提取内嵌世界书 + 角色
                card_result = _parse_card_or_error(raw)
                if card_result is None:
                    return json_error("PNG 角色卡解析失败（未找到内嵌 chara JSON）", 400)
                source = card_result["book_data"]
                if source is None:
                    return json_error(
                        "该 PNG 角色卡未包含内嵌世界书（character_book / extensions.world）", 400)
            else:
                text = _decode_upload(raw)
                obj = _try_json(text)
                if _looks_like_card(obj):
                    card_result = _parse_card_or_error(raw)
                    if card_result is None:
                        return json_error("角色卡解析失败", 400)
                    source = card_result["book_data"] or obj
                else:
                    source = text
        elif request.json is not None:
            data = request.json
            name = str(data.get("name", "") or "").strip()
            source = data.get("data") or data.get("book")
            if source is None:
                # 允许直接把整本书 JSON 作为 body（无 name/data 包装）
                source = {k: v for k, v in data.items() if k != "name"}
            if _looks_like_card(source):
                card_result = _parse_card_or_error(
                    json.dumps(source, ensure_ascii=False).encode("utf-8"))
                if card_result is None:
                    return json_error("角色卡解析失败", 400)
                source = card_result["book_data"] or source
        else:
            return json_error("需要上传文件或 JSON body")

        if not source:
            return json_error("导入内容为空")

        try:
            book, report = wb_mgr.import_book(name, source)
        except Exception as e:
            logger.exception("世界书导入失败")
            return json_error(f"导入失败: {e!s}", 500)

        # 角色卡连带导入角色：角色卡自带角色/开场白等内容可正常使用
        character = None
        if card_result is not None:
            try:
                character = _import_card_character(card_result, managers)
            except Exception as exc:
                logger.warning("角色卡连带导入角色失败: %s", exc)

        # 世界书里的战斗节点条目 → 落地为 data/combat/nodes/*.json
        combat_nodes = _import_combat_nodes(book)

        resp = {
            "book": _book_detail(book, include_entries=False),
            "report": report.to_dict(),
            "character": character,
            "combat_nodes": combat_nodes,
        }
        return jsonify(resp), 201

    # ── 3. 书详情 / 更新 / 删除 / 导出 ──

    @bp.route("/api/worldbook/<book_id>", methods=["GET"])
    def get_book(book_id):
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        return jsonify(_book_detail(book))

    @bp.route("/api/worldbook/<book_id>", methods=["PUT"])
    def update_book(book_id):
        with _locked_book(book_id) as (book, err):
            if err:
                return err
            data = request.json or {}
            if "name" in data:
                new_name = str(data["name"] or "").strip()
                if new_name:
                    book.name = new_name
            if "budget_tokens" in data:
                try:
                    book.budget_tokens = max(0, int(data["budget_tokens"] or 0))
                except (TypeError, ValueError):
                    return json_error("budget_tokens 必须是整数")
            if "enabled" in data:
                book.enabled = bool(data["enabled"])
            wb_mgr.save(book)
            return jsonify({"book": _book_detail(book, include_entries=False)})

    @bp.route("/api/worldbook/<book_id>", methods=["DELETE"])
    def delete_book(book_id):
        """统一删除。预装包删除后可通过 /reinstall 从分发源一键重装还原。"""
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        wb_mgr.delete_book(book_id)
        return jsonify({"message": "已删除"})

    @bp.route("/api/worldbook/<book_id>/duplicate", methods=["POST"])
    def duplicate_book(book_id):
        """复制任意书为新的导入书（做变体/备份）。body: {name?}"""
        data = request.json or {}
        try:
            new_book = wb_mgr.duplicate_book(
                book_id,
                new_name=str(data.get("name", "") or "").strip() or None,
            )
        except ValueError as e:
            return json_error(str(e), 404)
        return jsonify({"book": _book_detail(new_book, include_entries=False)}), 201

    @bp.route("/api/worldbook/<book_id>/reinstall", methods=["POST"])
    def reinstall_book(book_id):
        """从分发源一键重装预装整合包（恢复出厂内容）。"""
        try:
            book = wb_mgr.reinstall_book(book_id)
        except ValueError as e:
            return json_error(str(e), 404)
        return jsonify({"book": _book_detail(book, include_entries=False)})

    @bp.route("/api/worldbook/<book_id>/export", methods=["GET"])
    def export_book(book_id):
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        # 战斗节点条目：从节点注册表回灌最新规格，保证"节点侧编辑"随书导出
        refreshed = _refresh_combat_node_entries(book)
        if refreshed:
            wb_mgr.save(book)
        return jsonify({"name": book.name, "format": "sillytavern_v1",
                        "data": book.export_st(),
                        "combat_nodes_refreshed": refreshed})

    # ── 4. 条目 CRUD ──

    @bp.route("/api/worldbook/<book_id>/entries", methods=["POST"])
    def create_entry(book_id):
        with _locked_book(book_id) as (book, err):
            if err:
                return err
            try:
                entry = _entry_from_payload(request.json or {})
                _validate_entry_scope(book, entry)
                if any(e.uid == entry.uid for e in book.entries):
                    raise ValueError("条目 UID 已存在")
            except (TypeError, ValueError) as e:
                return json_error(str(e))
            book.entries.append(entry)
            book.import_config["revision"] += 1
            wb_mgr.save(book)
            return jsonify({"entry": entry.to_dict()}), 201

    @bp.route("/api/worldbook/<book_id>/entries/<entry_id>", methods=["PUT"])
    def update_entry(book_id, entry_id):
        with _locked_book(book_id) as (book, err):
            if err:
                return err
            for i, e in enumerate(book.entries):
                if e.uid == entry_id:
                    try:
                        if not isinstance(request.json, dict):
                            raise ValueError("条目数据必须是对象")
                        payload = {**e.to_dict(), **request.json}
                        updated = _entry_from_payload(payload, uid=entry_id)
                        _validate_entry_scope(book, updated)
                    except (TypeError, ValueError) as exc:
                        return json_error(str(exc))
                    # 保留 raw 以便导出回灌（编辑过的字段在 export_st 时会被覆盖）
                    updated.raw = e.raw
                    book.entries[i] = updated
                    book.import_config["revision"] += 1
                    wb_mgr.save(book)
                    return jsonify({"entry": updated.to_dict()})
            return json_error("条目不存在", 404)

    @bp.route("/api/worldbook/<book_id>/entries/<entry_id>", methods=["DELETE"])
    def delete_entry(book_id, entry_id):
        with _locked_book(book_id) as (book, err):
            if err:
                return err
            for i, e in enumerate(book.entries):
                if e.uid == entry_id:
                    book.entries.pop(i)
                    affected = {"dependency_edges": sum(entry_id in (edge["from_uid"], edge["to_uid"]) for edge in book.dependency_edges),
                                "fixed_entries": int(entry_id in book.import_config["fixed_entry_uids"]),
                                "dependency_sources": sum(s["entry_uid"] == entry_id for s in book.import_config["dependency_sources"])}
                    book.dependency_edges = [edge for edge in book.dependency_edges
                                             if entry_id not in (edge["from_uid"], edge["to_uid"])]
                    book.related_edges = [edge for edge in book.related_edges
                                          if entry_id not in (edge["from_uid"], edge["to_uid"])]
                    if book.dependency_rules is not None:
                        book.dependency_rules["roots"] = [
                            root for root in book.dependency_rules["roots"]
                            if root["entry_uid"] != entry_id]
                        book.dependency_rules["root_rule"]["entry_uids"] = [
                            uid for uid in book.dependency_rules["root_rule"]["entry_uids"]
                            if uid != entry_id]
                        # 入边与出边、以及被拒绝建议都要一起清掉（不留悬空引用）
                        book.dependency_rules["rejected"] = [
                            edge for edge in book.dependency_rules.get("rejected", [])
                            if entry_id not in (edge.get("from_uid"), edge.get("to_uid"))]
                        meta = book.dependency_rules.get("edge_meta") or {}
                        book.dependency_rules["edge_meta"] = {
                            key: value for key, value in meta.items()
                            if entry_id not in key.split("|")}
                    config = book.import_config
                    config["fixed_entry_uids"] = [uid for uid in config["fixed_entry_uids"] if uid != entry_id]
                    config["dependency_sources"] = [s for s in config["dependency_sources"]
                                                    if s["entry_uid"] != entry_id]
                    config["revision"] += 1
                    wb_mgr.save(book)
                    return jsonify({"message": "已删除", "affected": affected})
            return json_error("条目不存在", 404)

    # ── 4.1 分类树 / 依赖导入配置 ──

    def _policy_candidate(book, data):
        if not isinstance(data, dict):
            raise ValueError("请求体必须是对象")
        config, edges = validate_policy({e.uid for e in book.entries},
                                        {**book.import_config, **data}, book.dependency_edges)
        mode = data.get("scope_mode", book.scope_mode)
        if mode not in ("legacy", "selective"):
            raise ValueError("scope_mode 必须是 legacy 或 selective")
        candidate = copy.deepcopy(book)
        candidate.import_config = {**config, "revision": book.import_config["revision"] + 1}
        candidate.dependency_edges, candidate.scope_mode = edges, mode
        return candidate

    @bp.route("/api/worldbook/<book_id>/taxonomy", methods=["PUT"])
    def update_taxonomy(book_id):
        with _locked_book(book_id) as (book, err):
            if err:
                return err
            data = request.json
            try:
                if not isinstance(data, dict):
                    raise ValueError("请求体必须是对象")
                if data.get("expected_revision", book.import_config["revision"]) != book.import_config["revision"]:
                    return json_error("配置已变更，请重新加载后再保存", 409)
                old_kinds = {e.uid: book.category_scope_type(e.category_id) for e in book.entries}
                book.categories = validate_categories(data.get("categories"))
                moves = data.get("entry_moves", {})
                if not isinstance(moves, dict) or any(uid not in {e.uid for e in book.entries} for uid in moves):
                    raise ValueError("entry_moves 必须按有效条目 UID 指定目标分类")
                category_ids = {c["id"] for c in book.categories}
                for entry in book.entries:
                    if entry.uid in moves:
                        target = moves[entry.uid]
                        if not isinstance(target, str) or target not in category_ids:
                            raise ValueError(f"条目 {entry.uid} 的目标分类不存在")
                        entry.category_id = target
                        if book.category_scope_type(target) != "character":
                            entry.character_id = ""
                    if entry.category_id not in category_ids:
                        raise ValueError(f"请先为分类中的条目 {entry.uid} 指定迁移目标")
                    if entry.uid in moves or old_kinds[entry.uid] != book.category_scope_type(entry.category_id):
                        _validate_entry_scope(book, entry)
            except (TypeError, ValueError) as exc:
                return json_error(str(exc))
            # 编辑分类不隐式退出旧书兼容模式；用户检查预览后显式启用按需模式。
            book.import_config["revision"] += 1
            wb_mgr.save(book)
            return jsonify(_book_detail(book))

    @bp.route("/api/worldbook/<book_id>/auto-classify", methods=["POST"])
    def auto_classify(book_id):
        """按条目自带的可信元数据分类：默认只出方案（apply=false），apply=true 才写盘。

        只认 uid 前缀 / group 字段 / 名称后缀三类显式线索，不按名字或正文猜测。只改
        「条目属于哪一类」与随之而来的角色关联，不改载入模式、固定导入与依赖策略。
        """
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        result = classify_entries(book.entries)
        payload = result.to_payload()
        payload["proposal"] = result.categories(existing=book.categories)
        payload["apply"] = False
        # 统一草稿补丁：让「应用自动分类」也走草稿 + 一次原子保存，而不是绕过草稿写盘。
        payload["draft_patch"] = auto_classification_patch(book, result) if result.matched else None
        if not result.matched:
            payload["reason"] = "这本书的条目没有可用的分类线索（uid 前缀 / group 字段 / 名称后缀），已保持原样。"
            return jsonify(payload)
        if not data.get("apply"):
            return jsonify(payload)
        # 应用分类会整书写回：与其它写路径共用同一把锁
        with _locked_book(book_id) as (book, err):
            if err:
                return err
            if data.get("expected_revision", book.import_config["revision"]) != book.import_config["revision"]:
                return json_error("配置已变更，请重新加载后再保存", 409)
            try:
                apply_auto_classification(book)
                for entry in book.entries:
                    _validate_entry_scope(book, entry)
            except (TypeError, ValueError) as exc:
                return json_error(str(exc))
            book.import_config["revision"] += 1
            wb_mgr.save(book)
            payload["apply"] = True
            return jsonify({"classification": payload, "book": _book_detail(book)})

    @bp.route("/api/worldbook/<book_id>/import-config", methods=["PUT"])
    def update_import_config(book_id):
        with _locked_book(book_id) as (book, err):
            if err:
                return err
            data = request.json
            try:
                if isinstance(data, dict) and data.get("expected_revision", book.import_config["revision"]) != book.import_config["revision"]:
                    return json_error("配置已变更，请重新加载后再保存", 409)
                book = _policy_candidate(book, data)
            except (TypeError, ValueError) as exc:
                return json_error(str(exc))
            wb_mgr.save(book)
            return jsonify(_book_detail(book))

    @bp.route("/api/worldbook/<book_id>/scope-preview", methods=["POST"])
    def preview_scope(book_id):
        """只读预览：接受完整草稿 / 阵容 / 会话覆盖，返回可解释的候选范围。

        绝不写缓存、磁盘或会话；也不改变已有会话的快照。
        """
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        data = request.json
        try:
            if not isinstance(data, dict):
                raise ValueError("请求体必须是对象")
            candidate = _draft_candidate(book, data, preview=True)
            roster = data.get("roster_character_ids", [])
            manual = data.get("manual_entry_uids", [])
            revision = data.get("policy_revision")
            full_scope = bool(data.get("full_scope"))
            if candidate.v3_enabled:
                payload = candidate.preview_v3_scope(roster, manual, revision, full_scope)
                if full_scope:
                    payload = _apply_full_scope(payload, candidate)
                stale_issues = _ai_evidence_issues(candidate)
                payload["issues"] = list(payload.get("issues") or []) + stale_issues
                if isinstance(payload.get("scope"), dict):
                    payload["scope"]["issues"] = list(payload["scope"].get("issues") or []) + stale_issues
                return jsonify(payload)
            # 未启用 v3 的书沿用 v2 预览（旧语义不静默改变）
            payload = candidate.preview_scope(roster)
            if full_scope:
                payload = _apply_full_scope(payload, candidate)
            payload["draft_hash"] = candidate.policy_draft_hash(roster, manual, revision, full_scope)
            payload["policy_revision"] = candidate.import_config["revision"]
            payload["content_revision"] = content_revision(candidate.entries)
            payload["schema_version"] = candidate.schema_version
            payload["resolver_version"] = RESOLVER_VERSION
            return jsonify(payload)
        except (TypeError, ValueError) as exc:
            return json_error(str(exc))

    # ── 4.2 统一配置写入（分类 + 关联 + 起点 + 边 + AI 建议，一次原子提交）──

    def _draft_candidate(book, data, preview=False):
        """把请求体合成一本候选书。校验失败即抛 ValueError，绝不写盘。"""
        if not isinstance(data, dict):
            raise ValueError("请求体必须是对象")
        candidate = copy.deepcopy(book)
        known = {e.uid for e in candidate.entries}

        if "categories" in data:
            candidate.categories = validate_categories(data.get("categories"))
        category_ids = {c["id"] for c in candidate.categories}

        moves = data.get("entry_moves") or {}
        if not isinstance(moves, dict) or any(uid not in known for uid in moves):
            raise ValueError("entry_moves 必须按有效条目 UID 指定目标分类")
        for entry in candidate.entries:
            if entry.uid in moves:
                target = moves[entry.uid]
                if not isinstance(target, str) or target not in category_ids:
                    raise ValueError(f"条目 {entry.uid} 的目标分类不存在")
                entry.category_id = target
            if entry.category_id not in category_ids:
                raise ValueError(f"请先为分类中的条目 {entry.uid} 指定迁移目标")

        updates = data.get("entry_updates") or {}
        if not isinstance(updates, dict) or any(uid not in known for uid in updates):
            raise ValueError("entry_updates 必须按有效条目 UID 指定")
        for entry in candidate.entries:
            patch = updates.get(entry.uid)
            if not isinstance(patch, dict):
                continue
            if "character_id" in patch:
                entry.character_id = str(patch["character_id"] or "").strip()
            if "category_id" in patch:
                target = patch["category_id"]
                if not isinstance(target, str) or target not in category_ids:
                    raise ValueError(f"条目 {entry.uid} 的目标分类不存在")
                entry.category_id = target

        # 角色分类必须带角色目录名；非角色分类不可关联角色（沿用既有约束）
        for entry in candidate.entries:
            kind = candidate.category_scope_type(entry.category_id)
            if kind == "character" and not entry.character_id:
                raise ValueError(f"角色分类的条目 {entry.uid} 必须关联角色标识（角色目录名）")
            if kind != "character" and entry.character_id:
                raise ValueError(f"非角色分类的条目 {entry.uid} 不可关联角色")

        mode = data.get("scope_mode", candidate.scope_mode)
        if mode not in ("legacy", "selective"):
            raise ValueError("scope_mode 必须是 legacy 或 selective")
        candidate.scope_mode = mode

        # 是否采用 v3 按需规则：**显式**才迁移。
        # v2 书普通保存（改分类、改边）绝不能隐式切到 v3 —— 预装书 fixed/sources
        # 都是空的，一旦隐式启用就会把候选清成空集。
        adopt_v3 = bool(book.v3_enabled or data.get("adopt_v3"))

        existing_rules = dict(candidate.dependency_rules or {})
        request_rejected = [r for r in (data.get("rejected") or []) if isinstance(r, dict)]
        if request_rejected:
            existing_rules["rejected"] = _union_edges(
                existing_rules.get("rejected") or [], request_rejected)

        # AI 建议：服务端按持久化任务复核，客户端 accepted 只是「用户选了哪些」的提示
        proposal = _verified_proposal(book, data.get("proposal"))
        adopt_v3 = adopt_v3 or proposal is not None
        v3_payload = None
        if proposal is not None:
            raw_proposal = data.get("proposal") or {}
            if raw_proposal.get("materialized"):
                # materialized 只是 UI 工作流标记，不是信任边界。仍标成 llm/rule 的根
                # 必须逐字段匹配服务端任务；用户改写后须明确转成 manual。
                data = {**data, "roots": _verified_materialized_roots(
                    data.get("roots") or [], proposal)}
            v3_payload = build_to_v3_rules(candidate, proposal, existing_rules)
            if raw_proposal.get("materialized"):
                # UI has already put the proposal into its editable draft.
                # Retain provenance, but never re-add something the user removed.
                removed = []
                for field in ("requires_edges", "related_edges"):
                    keep = {(e.get("from_uid"), e.get("to_uid")) for e in data.get(field, [])}
                    removed.extend(e for e in v3_payload[field]
                                   if (e["from_uid"], e["to_uid"]) not in keep)
                    v3_payload[field] = []
                materialized_roots = set(proposal.get("materialized_root_uids") or [])
                # 新 UI 明确列出已经物化过的根：这些根随后从草稿删除就代表用户
                # 明确删除。旧 UI 没这个字段时不能把服务端生成的完整根计划清空。
                v3_payload["roots"] = [root for root in v3_payload.get("roots", [])
                                       if root.get("entry_uid") not in materialized_roots]
                existing_rules["rejected"] = _union_edges(existing_rules.get("rejected", []), removed)

        manual_keys = ("roots", "requires_edges", "related_edges")
        migrating = adopt_v3 and not book.v3_enabled
        if adopt_v3 and (any(key in data for key in manual_keys) or migrating
                         or v3_payload is not None or "rejected" in data):
            if migrating:
                # 显式迁移：把旧来源（世界观 / 阵容 / 固定 / 导入源）按**等价**映射
                # 并入起点。用并集而不是「客户端没给才补」——否则只要草稿漏了一类
                # 旧来源，保存一次就会静默少载入一批条目。
                base = candidate.equivalent_v3_rules()
                # 客户端（用户当前草稿）在前：用户显式改过的起点优先，
                # 等价映射只补草稿没提到的旧来源。
                manual = {
                    "roots": [r for r in ((data.get("roots") or []) + base["roots"])
                              if isinstance(r, dict)],
                    "requires_edges": [e for e in ((data.get("requires_edges") or [])
                                                   + base["requires_edges"]) if isinstance(e, dict)],
                    "related_edges": [e for e in ((data.get("related_edges") or [])
                                                  + base["related_edges"]) if isinstance(e, dict)],
                }
            else:
                # 已经是 v3：**已持久化的规则**就是草稿基线。
                # 只覆盖本次请求显式给出的列表，没给的键保持不动 —— 否则一个
                # 「只带 proposal」或「只带 rejected」的部分请求会把用户配好的
                # 起点 / 依赖静默清空；反过来也不能把 v2 等价映射重新并进来，
                # 那会让「收窄起点」永远不生效（P1-3 的第二段反证）。
                manual = {
                    "roots": data.get("roots", existing_rules.get("roots") or []),
                    "requires_edges": data.get("requires_edges", candidate.dependency_edges),
                    "related_edges": data.get("related_edges", candidate.related_edges),
                }

            # 正式人工锁定关系优先。即使旧/恶意客户端把相反类型的 AI 建议也放进
            # materialized 草稿，服务端仍恢复锁定类型并剔除相反类型；其他建议继续应用。
            locked_meta = {key for key, meta in (existing_rules.get("edge_meta") or {}).items()
                           if isinstance(meta, dict) and meta.get("locked")}
            existing_requires = {(e["from_uid"], e["to_uid"]) for e in candidate.dependency_edges}
            existing_related = {(e["from_uid"], e["to_uid"]) for e in candidate.related_edges}
            manual_requires = {(e.get("from_uid"), e.get("to_uid")): e
                               for e in manual.get("requires_edges", []) if isinstance(e, dict)}
            manual_related = {(e.get("from_uid"), e.get("to_uid")): e
                              for e in manual.get("related_edges", []) if isinstance(e, dict)}
            for key in locked_meta:
                if "|" not in key:
                    continue
                pair = tuple(key.split("|", 1))
                edge = {"from_uid": pair[0], "to_uid": pair[1]}
                if pair in existing_requires:
                    manual_related.pop(pair, None)
                    manual_requires[pair] = edge
                elif pair in existing_related:
                    manual_requires.pop(pair, None)
                    manual_related[pair] = edge
            manual["requires_edges"] = list(manual_requires.values())
            manual["related_edges"] = list(manual_related.values())
            v3_payload = _merge_v3_payload(manual, v3_payload, existing_rules)

        if migrating and v3_payload is None:
            # 显式迁移但请求体什么都没带（例如只有 {"adopt_v3": true}）：整体走等价映射
            v3_payload = candidate.equivalent_v3_rules()

        if v3_payload is not None and adopt_v3:
            final_pairs = {(e["from_uid"], e["to_uid"]) for field in ("requires_edges", "related_edges")
                           for e in v3_payload.get(field, [])}
            removed_ai = [{"from_uid": k.split("|", 1)[0], "to_uid": k.split("|", 1)[1]}
                          for k, meta in existing_rules.get("edge_meta", {}).items()
                          if meta.get("origin") == "llm" and tuple(k.split("|", 1)) not in final_pairs]
            v3_payload["rejected"] = _union_edges(v3_payload.get("rejected", []), removed_ai)
            candidate.dependency_rules, candidate.dependency_edges, candidate.related_edges = (
                validate_v3_rules(known, v3_payload, candidate.dependency_edges))
            candidate.schema_version = SCHEMA_VERSION_V3
            # v2 字段与 v3 起点保持同步，旧消费者（导出、旧接口）仍可读
            candidate.import_config["fixed_entry_uids"] = sorted(
                r["entry_uid"] for r in candidate.dependency_rules["roots"]
                if r["activation"] == ACTIVATION_ALWAYS and r["expansion"] == EXPANSION_NONE)
            candidate.import_config["dependency_sources"] = [
                {"entry_uid": r["entry_uid"], "max_depth": r["max_depth"]}
                for r in candidate.dependency_rules["roots"]
                if r["expansion"] == EXPANSION_LEGACY_DEPTH]
        elif not adopt_v3:
            # v2 书普通保存：草稿里的起点按 v2 形态写回，范围**逐条等价**，
            # 世界观 / 阵容仍然由分类决定，不因为保存一次而改变候选。
            v2_data = {key: data[key] for key in
                       ("fixed_entry_uids", "dependency_sources", "dependency_edges")
                       if key in data}
            if any(key in data for key in manual_keys):
                roots = [r for r in (data.get("roots") or []) if isinstance(r, dict)]
                v2_data["fixed_entry_uids"] = sorted({
                    r.get("entry_uid") for r in roots
                    if r.get("activation") == ACTIVATION_ALWAYS
                    and r.get("expansion") == EXPANSION_NONE and r.get("entry_uid")})
                v2_data["dependency_sources"] = [
                    {"entry_uid": r["entry_uid"], "max_depth": r.get("max_depth", 0)}
                    for r in roots
                    if r.get("expansion") == EXPANSION_LEGACY_DEPTH and r.get("entry_uid")]
                if "requires_edges" in data:
                    v2_data["dependency_edges"] = data.get("requires_edges") or []
            if "related_edges" in data:
                _, _, candidate.related_edges = validate_v3_rules(
                    known, {"roots": [], "requires_edges": [],
                            "related_edges": data.get("related_edges") or []})
            if v2_data:
                config, edges = validate_policy(known, {
                    **candidate.import_config, **v2_data,
                }, candidate.dependency_edges)
                candidate.import_config.update(config)
                candidate.dependency_edges = edges

        if not preview:
            candidate.import_config["revision"] = book.import_config["revision"] + 1
        return candidate

    @bp.route("/api/worldbook/<book_id>/configuration", methods=["PUT"])
    def put_configuration(book_id):
        """统一写入：分类 / 角色关联 / 起点规则 / 依赖边 / AI 建议，一次原子提交。

        按书锁覆盖「检查 → 提交」，因此并发写不会因为原子替换而丢更新；
        版本不一致返回 409，前端保留草稿。
        """
        data = request.json
        if not isinstance(data, dict):
            return json_error("请求体必须是对象")
        with wb_mgr.book_lock(book_id):
            book = wb_mgr.load(book_id)
            if not book:
                return json_error("世界书不存在", 404)
            expected = data.get("expected_revision", book.import_config["revision"])
            if expected != book.import_config["revision"]:
                return json_error("配置已变更，请重新加载后再保存", 409)
            try:
                candidate = _draft_candidate(book, data)
            except (TypeError, ValueError) as exc:
                return json_error(str(exc))
            candidate.record_policy_revision()
            wb_mgr.save(candidate)
        return jsonify({
            "book": _book_detail(candidate),
            "policy_revision": candidate.import_config["revision"],
            "content_revision": content_revision(candidate.entries),
            "applied": {
                "categories": len(candidate.categories),
                "roots": len((candidate.dependency_rules or {}).get("roots", [])),
                "requires_edges": len(candidate.dependency_edges),
                "related_edges": len(candidate.related_edges),
            },
        })

    # ── 4.3 AI 自动构建依赖（后台任务）──

    def _job_input_hash(book) -> str:
        """绑定正文和分析所用名称/别名/分类/角色；规则边编辑不改变该指纹。"""
        payload = [{"uid": e.uid, "content": content_hash(e.content), "name": e.name,
                    "aliases": e.trigger_keys, "category_id": e.category_id,
                    "character_id": e.character_id} for e in book.entries]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _model_identity(backend, backend_id: str, llm=None) -> str:
        """真实模型身份：`类型:模型名`（不含密钥）。

        `LLMBackendManager.get_llm()` 的第二个返回值是**后端 id**（cloud / ollama），
        不是模型名；直接拿它当 model 会让「同一个后端换模型」复用旧缓存。
        """
        if not backend_id:
            return ""
        identity = model_identity(llm, backend_id)
        if identity:
            return identity
        try:
            endpoints = backend.get_status().get("endpoints") or []
        except Exception:
            return backend_id
        for endpoint in endpoints:
            if endpoint.get("id") == backend_id:
                return f"{endpoint.get('type') or backend_id}:{endpoint.get('model') or 'unknown'}"
        return backend_id

    def _verified_proposal(book, raw):
        """服务端校验 AI 建议 —— **不信任客户端传来的 accepted**。

        只认持久化任务里的校验结果，并逐条复核：
        任务身份（job_id + 书 id）、输入指纹、两端正文哈希、证据可定位性。
        任一项不通过就报错要求重新构建，绝不把过期建议写进配置。
        """
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValueError("proposal 必须是对象")
        job_id = raw.get("job_id")
        if not job_id:
            raise ValueError("AI 建议缺少任务标识（job_id），无法校验来源；请重新构建后再应用")
        job = _JOB_STORE.get(str(job_id))
        if job is None or job.book_id != book.id:
            raise ValueError("找不到这次构建的任务记录，结果已失效；请重新构建")
        if job.cancelled or job.stage != "done" or job.outcome == "failed":
            raise ValueError("任务尚未完成或已取消，不能应用")
        result = job.result
        if not isinstance(result, dict):
            raise ValueError("这次构建没有可用的校验结果；请重新构建")
        if job.input_hash != _job_input_hash(book):
            raise ValueError("这本书在构建开始后已被修改，AI 结果已过期；请重新构建后再应用")

        wanted = raw.get("accepted_pairs")
        if wanted is None:
            wanted = [[item.get("from_uid"), item.get("to_uid")]
                      for item in (raw.get("accepted") or []) if isinstance(item, dict)]
        wanted_set = {(item[0], item[1]) for item in wanted
                      if isinstance(item, (list, tuple)) and len(item) == 2}

        by_uid = {e.uid: e for e in book.entries}
        accepted, skipped = [], 0
        seen = set()
        for record in result.get("records") or []:
            if not isinstance(record, dict):
                continue
            pair = (record.get("from_uid"), record.get("to_uid"))
            if pair in seen or pair not in wanted_set:
                continue
            seen.add(pair)
            a, b = pair
            if a not in by_uid or b not in by_uid:
                raise ValueError(f"AI 建议引用了不存在的条目：{a} → {b}")
            if record.get("source_content_hash") != content_hash(by_uid[a].content or "") or \
                    record.get("target_content_hash") != content_hash(by_uid[b].content or ""):
                raise ValueError(f"条目正文已变化（{a} → {b}），AI 证据已过期；请重新构建")
            relation = record.get("relation")
            if relation not in ("requires", "related"):
                skipped += 1
                continue
            if not evidence_locatable(record.get("evidence"), [by_uid[a], by_uid[b]]):
                skipped += 1
                continue
            accepted.append({**record, "relation": relation})
        verified_roots = []
        known_characters = set(_character_directory_ids()) or {
            entry.character_id for entry in book.entries if entry.character_id}
        for root in result.get("roots") or []:
            if not isinstance(root, dict):
                continue
            uid = root.get("entry_uid")
            entry = by_uid.get(uid)
            if entry is None:
                skipped += 1
                continue
            if root.get("origin") != "llm":
                skipped += 1
                continue
            if root.get("source_content_hash") != content_hash(entry.content or ""):
                raise ValueError(f"条目正文已变化（{uid}），AI 起点证据已过期；请重新构建")
            if not evidence_locatable(root.get("evidence"), [entry]):
                skipped += 1
                continue
            chars = root.get("character_ids") or []
            if root.get("activation") == "roster_any" and (
                    not chars or any(cid not in known_characters for cid in chars)):
                skipped += 1
                continue
            verified_roots.append(dict(root))

        # 服务端重建确定性分类根，只把上面逐条验过的 AI 根作为输入；不信客户端
        # 传来的 configuration_roots。该完整计划会交给物化草稿。
        configuration_roots = build_to_v3_rules(
            book, {"roots": verified_roots, "accepted": []},
            existing_rules=book.dependency_rules or {})["roots"]
        return {
            "accepted": accepted,
            "roots": configuration_roots,
            "model": result.get("model") or job.model,
            "proposal_version": result.get("proposal_version"),
            "job_id": job.id,
            "skipped": skipped,
            "materialized_root_uids": [uid for uid in (raw.get("materialized_root_uids") or [])
                                       if isinstance(uid, str)],
        }

    def _verified_materialized_roots(roots, proposal):
        """复核 UI 已物化根的来源，返回只含服务端或明确人工数据的根列表。"""
        if not isinstance(roots, list):
            raise ValueError("roots 必须是数组")

        def signature(root):
            chars = root.get("character_ids") or []
            if not isinstance(chars, list):
                chars = []
            return (
                root.get("entry_uid"), root.get("origin"), root.get("activation"),
                tuple(sorted({str(cid) for cid in chars if isinstance(cid, str)})),
                root.get("expansion"), root.get("max_depth"),
                root.get("source_content_hash"), root.get("evidence"),
                root.get("model"), root.get("prompt_version"),
            )

        verified = {}
        for root in proposal.get("roots") or []:
            if isinstance(root, dict) and root.get("origin") in ("llm", "rule"):
                verified[signature(root)] = root

        sanitized = []
        for root in roots:
            if not isinstance(root, dict):
                raise ValueError("roots 的每一项必须是对象")
            origin = root.get("origin") or "manual"
            if origin == "manual":
                sanitized.append({**root, "origin": "manual"})
                continue
            if origin not in ("llm", "rule"):
                raise ValueError(f"起点 {root.get('entry_uid') or '?'} 的 origin 无效；人工改写请使用 manual")
            expected = verified.get(signature(root))
            if expected is None:
                label = "AI" if origin == "llm" else "规则"
                raise ValueError(
                    f"物化草稿中的{label}起点 {root.get('entry_uid') or '?'} "
                    "与服务端构建任务的已验证建议不一致；人工改写请将 origin 设为 manual")
            item = dict(expected)
            if origin == "llm":
                item["job_id"] = proposal.get("job_id") or ""
                item["review_status"] = "applied"
            if root.get("locked"):
                item["locked"] = True
            sanitized.append(item)
        return sanitized

    def _character_directory_ids() -> list[str]:
        """真实角色目录 ID：AI 角色关联建议必须对着它校验，而不是「已关联过的角色」。"""
        doc_mgr = managers.get("document")
        if not doc_mgr:
            return []
        try:
            docs = doc_mgr.list_documents("characters", include_content=False)
        except Exception:
            return []
        return sorted({str(d.get("id") or "") for d in docs if d.get("id")})

    def _active_job(book_id: str):
        """这本书正在跑的任务（同一本书同时只允许一个，避免重复点击重复付费）。"""
        for item in _JOB_STORE.list_for_book(book_id):
            current = _JOB_STORE.get(item["job_id"])
            if current.running or item.get("stage") not in ("done", "failed", "cancelled"):
                return item
        return None

    def _start_job(book, data):
        """创建并启动构建任务。无可用模型时返回 503，前端据此引导去设置。"""
        backend = managers.get("llm_backend")
        llm, backend_id = (backend.get_llm() if backend else (None, ""))
        if not llm:
            return None, json_error(
                "尚未配置可用的 LLM。请先在「设置」里配置模型，再运行 AI 自动构建。", 503)
        running = _active_job(book.id)
        if running is not None:
            return None, json_error(
                f"这本书已有一个构建任务在进行中（{running.get('stage')}），"
                "请先等待或取消它，避免重复消耗调用额度。", 409)
        model = _model_identity(backend, backend_id, llm)
        job = _JOB_STORE.create(book.id, _job_input_hash(book), model)
        job.message = "已排队，正在准备条目"
        job.save()
        max_calls = data.get("max_calls") if isinstance(data, dict) else None
        try:
            max_calls = max(1, min(5000, int(max_calls))) if max_calls else None
        except (TypeError, ValueError):
            max_calls = None
        snapshot = copy.deepcopy(book)
        kwargs = {"max_calls": max_calls} if max_calls else {}
        character_ids = _character_directory_ids()

        def worker():
            try:
                run_build(job, snapshot, llm, model=model, cache=_ANALYSIS_CACHE,
                          character_ids=character_ids, **kwargs)
            finally:
                job.running = False
                job.save()

        job.running = True
        threading.Thread(target=worker, name=f"wb-build-{job.id}", daemon=True).start()
        return job, None

    @bp.route("/api/worldbook/<book_id>/dependency-proposals", methods=["POST"])
    def create_dependency_proposal(book_id):
        """一次点击即开始后台构建；不需要用户提供提示词或 JSON。"""
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        job, err = _start_job(book, data)
        if err:
            return err
        return jsonify({"job": job.to_dict(include_result=False)}), 202

    @bp.route("/api/worldbook/<book_id>/dependency-proposals", methods=["GET"])
    def list_dependency_proposals(book_id):
        """列出这本书的任务，并指出「当前该看哪一个」。

        前端据此在切视图 / 重开页面后恢复入口：后台任务不会因为面板卸载而消失，
        也不该让用户再点一次（那是重复付费）。
        """
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        jobs = _JOB_STORE.list_for_book(book_id)
        active = _active_job(book_id)
        latest = jobs[0] if jobs else None
        return jsonify({
            "jobs": jobs,
            "input_hash": _job_input_hash(book),
            "active_job_id": active.get("job_id") if active else None,
            "latest_job_id": latest.get("job_id") if latest else None,
        })

    @bp.route("/api/worldbook/<book_id>/dependency-proposals/<job_id>", methods=["GET"])
    def get_dependency_proposal(book_id, job_id):
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        job = _JOB_STORE.get(job_id)
        if job is None or job.book_id != book_id:
            return json_error("任务不存在", 404)
        payload = job.to_dict(include_result=False)
        payload["stale"] = job.input_hash != _job_input_hash(book)
        result = job.result
        if isinstance(result, dict):
            offset = max(0, request.args.get("offset", type=int) or 0)
            limit = min(500, max(1, request.args.get("limit", type=int) or 100))
            records = result.get("records", [])
            payload["result"] = {**result, "records": records[offset:offset + limit],
                                 "records_total": len(records)}
            payload["result"]["record_offset"] = offset
        else:
            payload["result"] = result
        return jsonify({"job": payload})

    @bp.route("/api/worldbook/<book_id>/dependency-proposals/<job_id>/cancel", methods=["POST"])
    def cancel_dependency_proposal(book_id, job_id):
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        job = _JOB_STORE.get(job_id)
        if job is None or job.book_id != book_id:
            return json_error("任务不存在", 404)
        _JOB_STORE.cancel(job_id)
        return jsonify({"job": _JOB_STORE.get(job_id).to_dict(include_result=False)})

    @bp.route("/api/worldbook/<book_id>/dependency-proposals/<job_id>/retry", methods=["POST"])
    def retry_dependency_proposal(book_id, job_id):
        """只重跑失败批次（含预算耗尽留下的剩余工作）：分析卡走缓存，不重复付费。"""
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        job = _JOB_STORE.get(job_id)
        if job is None or job.book_id != book_id:
            return json_error("任务不存在", 404)
        if job.stage not in ("done", "failed", "cancelled") or _active_job(book_id):
            return json_error("这本书已有构建正在运行", 409)
        if job.input_hash != _job_input_hash(book):
            return json_error("正文已变化，请重新构建以更新入边和出边", 409)
        # 预算耗尽留下的剩余工作也算「失败批次」，同样可续跑
        pairs = [{"from_uid": a, "to_uid": b}
                 for batch in job.failed_batches for a, b in batch.get("pairs", [])]
        uids = sorted({uid for batch in job.failed_batches
                       for uid in batch.get("uids", [])})
        if not pairs and not uids and not job.pending_pairs and not job.pending_card_uids and not job.resumable:
            return json_error("没有失败批次需要重试")
        if not pairs:
            pairs = list(job.pending_pairs)
        if not uids:
            uids = list(job.pending_card_uids)
        backend = managers.get("llm_backend")
        llm, backend_id = (backend.get_llm() if backend else (None, ""))
        if not llm:
            return json_error("尚未配置可用的 LLM，无法重试", 503)
        model = _model_identity(backend, backend_id, llm) or job.model
        if model != job.model:
            return json_error("模型已变化，请重新构建", 409)
        data = request.json if isinstance(request.json, dict) else {}
        try:
            max_calls = int(data.get("max_calls")) if data.get("max_calls") else None
        except (TypeError, ValueError):
            max_calls = None
        if max_calls is None:
            # 重试必须带足够预算，否则会在同一处再次撞墙
            max_calls = auto_budget(int((job.workload or {}).get("estimated_calls") or 0))
        job.cancelled = False
        job.failed_batches = []
        job.resumable = False
        job.stage = "adjudication" if pairs and not uids else "cards"
        job.save()
        snapshot = copy.deepcopy(book)
        character_ids = _character_directory_ids()

        def worker():
            try:
                run_build(job, snapshot, llm, model=model, cache=_ANALYSIS_CACHE,
                          only_pairs=(pairs or None) if not uids else None, only_uids=uids or None,
                          max_calls=max_calls, character_ids=character_ids)
            finally:
                job.running = False
                job.save()

        job.running = True
        threading.Thread(target=worker, name=f"wb-retry-{job.id}", daemon=True).start()
        return jsonify({"job": job.to_dict(include_result=False)}), 202

    # ── 5. 默认书 / 会话绑定 ──

    @bp.route("/api/worldbook/<book_id>/default", methods=["POST"])
    def set_default(book_id):
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        data = request.json or {}
        is_default = bool(data.get("default", True))
        wb_mgr.set_default_book_id(book_id if is_default else None)
        return jsonify({"default_book_id": wb_mgr.get_default_book_id()})

    @bp.route("/api/worldbook/<book_id>/bind", methods=["POST"])
    def bind_session(book_id):
        """绑定世界书到会话。body: {session_id, bound}。

        bound=false 时显式不使用世界书，不回落全局默认书。
        """
        data = request.json or {}
        session_id = str(data.get("session_id", "") or "").strip()
        bound = bool(data.get("bound", True))
        if not session_id:
            return json_error("需要 session_id 参数")
        if not session_mgr:
            return json_error("会话服务不可用", 503)
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        if bound:
            book, err = _get_book_or_404(book_id)
            if err:
                return err
            if not book.enabled:
                return json_error("世界书已停用")
            roster = session.scene_manager.get_scene_characters()
            # v3 书绑定完整规则快照（不只是版本号），会话可据此恢复它创建时的规则。
            scope = (book.session_scope_snapshot(roster) if book.v3_enabled
                     else book.resolve_import_scope(roster))
        else:
            scope = {"book_id": None, "resolved_entry_uids": []}
        session.overlay.set_worldbook_id(book_id if bound else None)
        session.overlay.set_worldbook_scope(scope)
        return jsonify({
            "session_id": session_id,
            "worldbook_id": session.overlay.get_worldbook_id(),
            "worldbook_scope": session.overlay.get_worldbook_scope(),
        })

    @bp.route("/api/worldbook/search", methods=["GET"])
    def search_books():
        """跨书/条目检索：书名、条目名、条目内容、触发词。"""
        q = request.args.get("q", "").strip()
        limit = request.args.get("limit", "30")
        try:
            limit = max(1, min(100, int(limit)))
        except (TypeError, ValueError):
            limit = 30
        return jsonify({"results": wb_mgr.search_books(q, limit)})

    @bp.route("/api/worldbook/resolve", methods=["GET"])
    def resolve_book():
        """查询会话当前生效的世界书（会话绑定 > 全局默认）。"""
        session_id = request.args.get("session_id", "").strip()
        overlay = None
        if session_id and session_mgr:
            session = session_mgr.get_session(session_id)
            if not session:
                return json_error("会话不存在", 404)
            overlay = session.overlay
        book = wb_mgr.resolve(overlay)
        if not book:
            return jsonify({"book": None, "default_book_id": wb_mgr.get_default_book_id()})
        return jsonify({
            "book": _book_detail(book, include_entries=False),
            "default_book_id": wb_mgr.get_default_book_id(),
        })

    app.register_blueprint(bp)
