"""
Legacy blueprint — 已弃用的旧版 API 兼容端点。
每个路由在命中时记录弃用警告日志。
"""

import logging

from flask import Blueprint, jsonify, request

from shared.helpers import json_error

logger = logging.getLogger(__name__)

# 旧版会话追踪（单会话模式，动态 ID）
_legacy_sid: str | None = None


def _get_session(session_mgr, session_id):
    """获取会话，不存在则返回 None。"""
    session = session_mgr.get_session(session_id)
    if not session:
        return None
    return session


def register(app, managers):
    bp = Blueprint("legacy", __name__)
    session_mgr = managers["session"]
    doc_mgr = managers["document"]
    llm_backend = managers["llm_backend"]

    # ── 1. POST /api/chat ──
    @bp.route("/api/chat", methods=["POST"])
    def legacy_chat():
        """（已弃用）旧版单角色对话。"""
        logger.warning("Deprecated endpoint /api/chat called")

        data = request.json or {}
        user_input = data.get("input", "").strip()
        character = data.get("character", "").strip()

        if not user_input:
            return json_error("需要 input 参数")
        if not character:
            return json_error("需要 character 参数")

        # 自动创建旧版会话（如果不存在）
        global _legacy_sid
        session = _get_session(session_mgr, _legacy_sid) if _legacy_sid else None
        if not session:
            session = session_mgr.create_session(
                name="旧版对话",
                mode="free",
            )
            _legacy_sid = session.id

        # 确保 LLM 可用
        if not session.is_usable:
            session.refresh_llm()
            if not session.is_usable:
                return json_error("LLM 后端不可用", 503)

        # 加载角色
        if not session.scene_manager.load_character(character):
            return json_error(f"无法加载角色: {character}")

        player_info = {"identity": data.get("identity", "博士")}
        env_context = session.environment.build_context()

        try:
            response, env_updates = session.scene_manager.chat(
                user_input, player_info, env_context
            )
            session.environment.apply_update(env_updates)
            return jsonify({
                "response": response,
                "character": session.scene_manager.active,
                "env_updates": env_updates,
            })
        except Exception as e:
            logger.error("旧版对话出错: %s", e)
            return json_error(f"对话处理失败: {e!s}", 500)

    # ── 2. POST /api/reset ──
    @bp.route("/api/reset", methods=["POST"])
    def legacy_reset():
        """（已弃用）旧版会话重置。"""
        logger.warning("Deprecated endpoint /api/reset called")
        global _legacy_sid
        if _legacy_sid:
            try:
                session_mgr.delete_session(_legacy_sid)
            except Exception:
                pass
            _legacy_sid = None
        return jsonify({"message": "旧版会话已重置"})

    # ── 3. GET /api/characters ──
    @bp.route("/api/characters", methods=["GET"])
    def legacy_characters():
        """（已弃用）列出所有角色文档。"""
        logger.warning("Deprecated endpoint /api/characters called")
        try:
            docs = doc_mgr.list_documents("characters", include_content=True)
        except ValueError:
            return jsonify([])
        return jsonify(docs)

    # ── 4. GET /api/characters/<character_id> ──
    @bp.route("/api/characters/<path:character_id>", methods=["GET"])
    def legacy_character(character_id: str):
        """（已弃用）读取单个角色文档。"""
        logger.warning("Deprecated endpoint /api/characters/<id> called")
        try:
            doc = doc_mgr.read_document("characters", character_id)
        except Exception:
            return json_error(f"角色不存在: {character_id}", 404)
        return jsonify({
            "content": doc["content"],
            "metadata": doc["metadata"],
        })

    # ── 5. GET /api/items ──
    @bp.route("/api/items", methods=["GET"])
    def legacy_items():
        """（已弃用）列出所有物品文档。"""
        logger.warning("Deprecated endpoint /api/items called")
        try:
            docs = doc_mgr.list_documents("items", include_content=True)
        except ValueError:
            return jsonify([])
        return jsonify(docs)

    # ── 6. GET /api/items/<item_id> ──
    @bp.route("/api/items/<path:item_id>", methods=["GET"])
    def legacy_item(item_id: str):
        """（已弃用）读取单个物品文档。"""
        logger.warning("Deprecated endpoint /api/items/<id> called")
        try:
            doc = doc_mgr.read_document("items", item_id)
        except Exception:
            return json_error(f"物品不存在: {item_id}", 404)
        return jsonify({
            "content": doc["content"],
            "metadata": doc["metadata"],
        })

    app.register_blueprint(bp)
