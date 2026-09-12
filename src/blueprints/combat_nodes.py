"""Combat nodes blueprint —— 战斗节点注册表 CRUD、校验、世界书归属与节点图。

端点：
  GET    /api/combat/nodes?book_id=&session_id= — 节点总览（可选按世界书过滤）
  POST   /api/combat/nodes               — 新建节点（按模板，可指定归属世界书）
  GET    /api/combat/nodes/<node_id>     — 节点完整 JSON（编辑器读取）
  PUT    /api/combat/nodes/<node_id>     — 保存（`_hash` 冲突 → 409）
  DELETE /api/combat/nodes/<node_id>     — 删除（被剧情引用时需 `force=1`）
  POST   /api/combat/nodes/validate      — 只校验不落盘（编辑器实时提示）
  GET    /api/combat/nodes/<node_id>/worldbook — 世界书条目预览
  POST   /api/combat/nodes/import-worldbook    — 从世界书条目/书 id 导入节点
  GET    /api/combat/nodes/graph?book_id=&session_id= — 节点图（剧情流程 + 战斗节点）
"""

import logging

from flask import Blueprint, jsonify, request

from shared.helpers import json_error
from combat_nodes import (
    NodeConflictError,
    NodeError,
    create_node,
    decode_worldbook_entry,
    delete_node,
    encode_node_for_worldbook,
    import_worldbook_nodes,
    list_node_files,
    load_node_file,
    node_bindings,
    node_graph,
    node_overview,
    node_progress,
    validate_node,
)

logger = logging.getLogger(__name__)


def _enemy_names() -> set[str]:
    from combat_data_loader import CombatDataLoader
    return set(CombatDataLoader().list_enemy_names())


def register(app, managers):
    session_mgr = managers["session"]
    bp = Blueprint("combat_nodes", __name__)

    def _session(session_id: str):
        if not session_id:
            return None
        return session_mgr.get_session(session_id)

    # ── 列表 / 详情 ──

    @bp.route("/api/combat/nodes", methods=["GET"])
    def list_nodes():
        """节点总览：注册表 + 剧情节拍绑定 + 会话进度 + 待创建。

        `book_id` 传参时只返回归属于该世界书的节点；不传返回全部。
        """
        session = _session(request.args.get("session_id", ""))
        book_id = request.args.get("book_id")
        rows, meta = node_overview(session, book_id=book_id)
        return jsonify({"nodes": rows, "meta": meta})

    @bp.route("/api/combat/nodes/graph", methods=["GET"])
    def graph():
        """节点图数据：剧情流程（章节/节拍/引用）+ 战斗节点，按世界书过滤。"""
        book_id = request.args.get("book_id", "")
        session = _session(request.args.get("session_id", ""))
        return jsonify(node_graph(book_id, session))

    @bp.route("/api/combat/nodes/<path:node_id>", methods=["GET"])
    def get_node(node_id: str):
        node = load_node_file(node_id)
        if not node:
            return json_error(f"战斗节点不存在: {node_id}", 404)
        bindings = node_bindings().get(node_id, [])
        report = validate_node(node, enemy_names=_enemy_names())
        return jsonify({
            "node": node,
            "bindings": bindings,
            "validation": report,
            "worldbook_entry": encode_node_for_worldbook(node),
        })

    # ── 新建 / 保存 / 删除 ──

    @bp.route("/api/combat/nodes", methods=["POST"])
    def create():
        data = request.json or {}
        try:
            node = create_node(str(data.get("node_id") or ""), str(data.get("name") or ""),
                               worldbook_id=str(data.get("worldbook_id") or ""))
        except NodeError as e:
            return json_error("；".join(e.errors), 400)
        return jsonify({"ok": True, "node": node}), 201

    @bp.route("/api/combat/nodes/<path:node_id>", methods=["PUT"])
    def update(node_id: str):
        data = request.json or {}
        payload = data.get("node") if isinstance(data.get("node"), dict) else data
        payload = dict(payload or {})
        payload["node_id"] = node_id          # 路径即真相，避免改名走样
        expected_hash = str(data.get("_hash") or payload.pop("_hash", "") or "")

        from combat_nodes import save_node
        try:
            node = save_node(payload, expected_hash, enemy_names=_enemy_names())
        except NodeConflictError as e:
            return json_error("；".join(e.errors), 409)
        except NodeError as e:
            return json_error("；".join(e.errors), 400)
        return jsonify({"ok": True, "node": node})

    @bp.route("/api/combat/nodes/<path:node_id>", methods=["DELETE"])
    def remove(node_id: str):
        force = request.args.get("force", "") in ("1", "true", "yes")
        from combat_nodes import node_exists
        if not node_exists(node_id):
            return json_error(f"节点不存在: {node_id}", 404)
        try:
            result = delete_node(node_id, force=force)
        except NodeError as e:
            # 被剧情引用 → 409（需 force）；其它校验错误 → 400
            return json_error("；".join(e.errors), 400 if force else 409)
        return jsonify({"ok": True, **result})

    # ── 校验 / 世界书 ──

    @bp.route("/api/combat/nodes/validate", methods=["POST"])
    def validate():
        payload = request.json or {}
        node = payload.get("node") if isinstance(payload.get("node"), dict) else payload
        return jsonify(validate_node(node or {}, enemy_names=_enemy_names()))

    @bp.route("/api/combat/nodes/<path:node_id>/worldbook", methods=["GET"])
    def worldbook_preview(node_id: str):
        node = load_node_file(node_id)
        if not node:
            return json_error(f"战斗节点不存在: {node_id}", 404)
        return jsonify({"entry": encode_node_for_worldbook(node)})

    @bp.route("/api/combat/nodes/import-worldbook", methods=["POST"])
    def import_from_worldbook():
        """从世界书条目导入节点。

        body: `{entries: [...]}`（直接给条目）或 `{book_id: "arknights"}`
        （从 WorldBookManager 取书的所有条目）；返回逐条结果与错误。
        """
        data = request.json or {}
        entries = data.get("entries")
        book_id = str(data.get("book_id") or "")
        if not entries and book_id:
            book_mgr = managers.get("worldbook")
            book = book_mgr.get(book_id) if book_mgr else None
            if not book:
                return json_error(f"世界书不存在: {book_id}", 404)
            entries = [e.to_dict() for e in book.entries]
        if not entries:
            return json_error("缺少 entries 或 book_id", 400)

        result = import_worldbook_nodes(
            entries, book_id=book_id, overwrite=bool(data.get("overwrite", True)),
            enemy_names=_enemy_names())
        status = 200 if not result["errors"] else 207
        return jsonify({"ok": not result["errors"], **result}), status

    # ── 进度（供编辑器显示会话节拍状态）──

    @bp.route("/api/combat/nodes/progress", methods=["GET"])
    def progress():
        session = _session(request.args.get("session_id", ""))
        if session is None:
            return json_error("会话不存在", 404)
        mapping, ctx = node_progress(session)
        return jsonify({"progress": mapping, "context": ctx,
                        "has_plot": bool(ctx.get("plot_id"))})

    app.register_blueprint(bp)
    return bp
