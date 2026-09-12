"""
Story blueprint — 剧情状态展示与节点回档。

端点：
  GET  /api/sessions/<session_id>/story-state  — 当前位置（章节/节拍路线图 + 角色状态）
  POST /api/sessions/<session_id>/rollback-node — 回档到某关键节点并恢复该节点状态
"""

import logging

from flask import Blueprint, jsonify, request

from shared.helpers import json_error

logger = logging.getLogger(__name__)


def _get_session(session_mgr, session_id):
    """获取会话，不存在则返回 None。"""
    return session_mgr.get_session(session_id)


def register(app, managers):
    bp = Blueprint("story", __name__)
    session_mgr = managers["session"]

    # ── 1. GET /api/sessions/<session_id>/story-state ──
    @bp.route("/api/sessions/<session_id>/story-state", methods=["GET"])
    def story_state(session_id: str):
        """剧情状态：玩家当前在节点结构中的位置 + 节拍路线图 + 角色/任务状态。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        state = session.overlay.build_story_state() if session.overlay else {"has_plot": False, "roads": []}
        if not state.get("has_plot"):
            return jsonify(state)

        # 战斗节点进度（仅含 [COMBAT:] 引用的节拍）
        try:
            from combat_nodes import node_progress
            progress, _ = node_progress(session)
            state["combat_nodes"] = progress
        except Exception:
            logger.warning("计算战斗节点进度失败", exc_info=True)
            state["combat_nodes"] = {}
        return jsonify(state)

    # ── 2. POST /api/sessions/<session_id>/rollback-node ──
    @bp.route("/api/sessions/<session_id>/rollback-node", methods=["POST"])
    def rollback_node(session_id: str):
        """回档到某关键节点，恢复该节点时的叙述历史与全部会话状态。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        if session.combat is not None:
            return json_error("战斗进行中，无法回档。请先完成或退出战斗。", 423)

        data = request.json or {}
        node_id = str(data.get("node_id") or "").strip()
        if not node_id:
            return json_error("需要 node_id 参数")

        try:
            result = session.rollback_to_node(node_id)
        except ValueError as e:
            return json_error(str(e), 400)
        except Exception as e:
            logger.error("节点回档失败: %s", e)
            return json_error(f"节点回档失败: {e!s}", 500)

        return jsonify(result)

    app.register_blueprint(bp)
