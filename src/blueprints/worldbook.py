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
    POST   /api/worldbook/<book_id>/default    设为/取消全局默认书
    POST   /api/worldbook/<book_id>/bind       绑定到会话（或解绑）
    GET    /api/worldbook/resolve              查询会话当前生效的书
"""

import json
import logging
import uuid

from flask import Blueprint, jsonify, request

from shared.helpers import json_error
from world_book import WorldBook, WorldBookEntry

logger = logging.getLogger(__name__)


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
        depth=max(0, int(payload.get("depth", 4) or 4)),
        scan_depth=max(1, int(payload.get("scan_depth", 4) or 4)),
        probability=max(0, min(100, int(payload.get("probability", 100) or 100))),
        group=str(payload.get("group", "") or ""),
        group_weight=int(payload.get("group_weight", 100) or 100),
        case_sensitive=bool(payload.get("case_sensitive", False)),
        match_whole_words=bool(payload.get("match_whole_words", False)),
    )


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

    def _get_book_or_404(book_id):
        book = wb_mgr.load(book_id)
        if not book:
            return None, json_error("世界书不存在", 404)
        return book, None

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
        book, err = _get_book_or_404(book_id)
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
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        try:
            entry = _entry_from_payload(request.json or {})
        except ValueError as e:
            return json_error(str(e))
        book.entries.append(entry)
        wb_mgr.save(book)
        return jsonify({"entry": entry.to_dict()}), 201

    @bp.route("/api/worldbook/<book_id>/entries/<entry_id>", methods=["PUT"])
    def update_entry(book_id, entry_id):
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        for i, e in enumerate(book.entries):
            if e.uid == entry_id:
                try:
                    updated = _entry_from_payload(request.json or {}, uid=entry_id)
                except ValueError as exc:
                    return json_error(str(exc))
                # 保留 raw 以便导出回灌（编辑过的字段在 export_st 时会被覆盖）
                updated.raw = e.raw
                book.entries[i] = updated
                wb_mgr.save(book)
                return jsonify({"entry": updated.to_dict()})
        return json_error("条目不存在", 404)

    @bp.route("/api/worldbook/<book_id>/entries/<entry_id>", methods=["DELETE"])
    def delete_entry(book_id, entry_id):
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        for i, e in enumerate(book.entries):
            if e.uid == entry_id:
                book.entries.pop(i)
                wb_mgr.save(book)
                return jsonify({"message": "已删除"})
        return json_error("条目不存在", 404)

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

        bound=false 时解绑该会话（回落全局默认书）。
        """
        book, err = _get_book_or_404(book_id)
        if err:
            return err
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
        session.overlay.set_worldbook_id(book_id if bound else None)
        return jsonify({
            "session_id": session_id,
            "worldbook_id": session.overlay.get_worldbook_id(),
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
