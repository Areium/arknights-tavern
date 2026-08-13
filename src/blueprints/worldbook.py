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

import logging
import uuid

from flask import Blueprint, jsonify, request

from shared.helpers import json_error
from world_book import WorldBookEntry

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

        if "file" in request.files and request.files["file"]:
            f = request.files["file"]
            name = str(request.form.get("name", "") or "").strip() or f.filename
            source = _decode_upload(f.read())
        elif request.json is not None:
            data = request.json
            name = str(data.get("name", "") or "").strip()
            source = data.get("data") or data.get("book")
            if source is None:
                # 允许直接把整本书 JSON 作为 body（无 name/data 包装）
                source = {k: v for k, v in data.items() if k != "name"}
        else:
            return json_error("需要上传文件或 JSON body")

        if not source:
            return json_error("导入内容为空")

        try:
            book, report = wb_mgr.import_book(name, source)
        except Exception as e:
            logger.exception("世界书导入失败")
            return json_error(f"导入失败: {e!s}", 500)

        if report.imported == 0:
            return jsonify({
                "book": _book_detail(book, include_entries=False),
                "report": report.to_dict(),
            })

        return jsonify({
            "book": _book_detail(book, include_entries=False),
            "report": report.to_dict(),
        }), 201

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
        wb_mgr.save(book)
        return jsonify({"book": _book_detail(book, include_entries=False)})

    @bp.route("/api/worldbook/<book_id>", methods=["DELETE"])
    def delete_book(book_id):
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        wb_mgr.delete_book(book_id)
        return jsonify({"message": "已删除"})

    @bp.route("/api/worldbook/<book_id>/export", methods=["GET"])
    def export_book(book_id):
        book, err = _get_book_or_404(book_id)
        if err:
            return err
        return jsonify({"name": book.name, "format": "sillytavern_v1",
                        "data": book.export_st()})

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
