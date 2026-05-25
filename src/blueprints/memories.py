"""
Memories blueprint — 回忆系统：查看、重新生成、会话回退。
"""

import logging

from flask import Blueprint, jsonify, request

from shared.helpers import json_error

logger = logging.getLogger(__name__)


def _get_session(session_mgr, session_id):
    """获取会话，不存在则返回 None。"""
    session = session_mgr.get_session(session_id)
    if not session:
        return None
    return session


def register(app, managers):
    bp = Blueprint("memories", __name__)
    session_mgr = managers["session"]
    llm_backend = managers["llm_backend"]

    # ── 1. GET /api/sessions/<session_id>/memories ──
    @bp.route("/api/sessions/<session_id>/memories", methods=["GET"])
    def get_memories(session_id: str):
        """获取会话的回忆列表。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        return jsonify({
            "memories": session.get_memories(),
            "narration_count": session.narration_count,
            "last_memory_end": session._last_memory_end,
        })

    # ── 2. POST /api/sessions/<session_id>/memories/regenerate ──
    @bp.route("/api/sessions/<session_id>/memories/regenerate", methods=["POST"])
    def regenerate_memories(session_id: str):
        """清除已有回忆并按当前间隔重新生成。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        if not session.get_llm():
            return json_error("LLM 后端不可用，无法重新生成回忆", 503)

        config = llm_backend.get_config()
        interval = config.get("memory_interval", 5)
        new_memories = session.regenerate_memories(interval)

        return jsonify({
            "memories": new_memories,
            "narration_count": session.narration_count,
            "interval_used": interval,
        })

    # ── 3. POST /api/sessions/<session_id>/rollback ──
    @bp.route("/api/sessions/<session_id>/rollback", methods=["POST"])
    def rollback_session(session_id: str):
        """回退会话到指定轮次，删除其后的历史和回忆。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        data = request.json or {}
        target_round = data.get("round")

        if target_round is None:
            return json_error("需要 round 参数")

        try:
            target_round = int(target_round)
        except (ValueError, TypeError):
            return json_error("round 必须是非负整数")

        if target_round < 0:
            return json_error("round 必须是非负整数")

        result = session.rollback_to_round(target_round)
        return jsonify(result)

    app.register_blueprint(bp)
