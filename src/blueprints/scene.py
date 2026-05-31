"""
Scene blueprint — 场景角色/物品/覆盖管理。
"""

import os
from pathlib import Path
from flask import Blueprint, jsonify, request, send_from_directory, abort

from shared.helpers import json_error
from document_manager import DocumentNotFoundError, ConflictError
from avatar_color import find_avatar_path, get_theme_color, ensure_theme_color

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _get_session(session_mgr, session_id):
    """获取会话，不存在则返回 None。"""
    session = session_mgr.get_session(session_id)
    if not session:
        return None
    return session


def _require_usable(session):
    """检查会话是否可以进行 LLM 操作，不可用则返回 503。"""
    if not session.get_llm():
        return json_error("LLM 后端不可用，无法执行此操作", 503)
    return None


def register(app, managers):
    session_mgr = managers["session"]
    doc_mgr = managers["document"]

    bp = Blueprint("scene", __name__)

    # ══════════════════════════════════════════════════════
    # 角色管理
    # ══════════════════════════════════════════════════════

    @bp.route("/api/sessions/<session_id>/characters", methods=["GET"])
    def list_scene_characters(session_id: str):
        """获取当前场景中的角色列表。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        chars = session.scene_manager.get_scene_characters()
        return jsonify({
            "characters": chars,
            "active": session.scene_manager.active,
            "character_colors": {
                name: c for name in chars
                if (c := get_theme_color(name))
            },
        })

    @bp.route("/api/sessions/<session_id>/characters/load", methods=["POST"])
    def load_scene_character(session_id: str):
        """加载角色到场景。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        err = _require_usable(session)
        if err:
            return err
        data = request.json or {}
        name = data.get("character")
        if not name:
            return json_error("需要 character 参数")

        # 自动提取主题色（仅在缺少时）
        ensure_theme_color(name)

        ok = session.scene_manager.load_character(name)
        if not ok:
            return json_error(f"无法加载角色: {name}")
        return jsonify(session.to_dict())

    @bp.route("/api/sessions/<session_id>/characters/unload", methods=["POST"])
    def unload_scene_character(session_id: str):
        """从场景移除角色。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        data = request.json or {}
        name = data.get("character")
        if not name:
            return json_error("需要 character 参数")
        ok = session.scene_manager.unload_character(name)
        if not ok:
            return json_error(f"角色不在场景中: {name}")
        return jsonify(session.to_dict())

    @bp.route("/api/sessions/<session_id>/characters/switch", methods=["POST"])
    def switch_scene_character(session_id: str):
        """切换当前对话目标。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        data = request.json or {}
        name = data.get("character")
        if not name:
            return json_error("需要 character 参数")
        ok = session.scene_manager.switch_active(name)
        if not ok:
            return json_error(f"角色不在场景中: {name}")
        return jsonify(session.to_dict())

    # ══════════════════════════════════════════════════════
    # 物品管理
    # ══════════════════════════════════════════════════════

    @bp.route("/api/sessions/<session_id>/items", methods=["GET"])
    def get_scene_items(session_id: str):
        """获取场景中的物品列表。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        return jsonify({"items": session.scene_manager.get_scene_items()})

    @bp.route("/api/sessions/<session_id>/items/add", methods=["POST"])
    def add_scene_item(session_id: str):
        """添加物品到场景。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        data = request.json or {}
        item_id = data.get("item_id", "").strip()
        if not item_id:
            return json_error("需要 item_id 参数")
        try:
            doc = doc_mgr.read_document("items", item_id)
        except DocumentNotFoundError:
            return json_error(f"物品不存在: {item_id}", 404)
        ok = session.scene_manager.add_item(item_id, doc["metadata"])
        if not ok:
            return json_error(f"物品已在场景中: {item_id}")
        return jsonify(session.to_dict())

    @bp.route("/api/sessions/<session_id>/items/remove", methods=["POST"])
    def remove_scene_item(session_id: str):
        """从场景移除物品。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        data = request.json or {}
        item_id = data.get("item_id", "").strip()
        if not item_id:
            return json_error("需要 item_id 参数")
        ok = session.scene_manager.remove_item(item_id)
        if not ok:
            return json_error(f"物品不在场景中: {item_id}")
        return jsonify(session.to_dict())

    # ══════════════════════════════════════════════════════
    # 会话覆盖（角色/物品/环境的会话级修改）
    # ══════════════════════════════════════════════════════

    @bp.route("/api/sessions/<session_id>/overrides", methods=["GET"])
    def get_session_overrides(session_id: str):
        """获取会话的全部覆盖数据。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        return jsonify(session.overlay.to_dict())

    @bp.route("/api/sessions/<session_id>/overrides/characters/<name>", methods=["GET"])
    def get_character_merged(session_id: str, name: str):
        """获取角色的合并后数据（模板 + 会话覆盖）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        try:
            doc = doc_mgr.read_document("characters", name)
        except DocumentNotFoundError:
            return json_error(f"角色不存在: {name}", 404)
        merged_meta, merged_content = session.overlay.apply_character_overrides(
            name, doc["metadata"], doc["content"]
        )
        return jsonify({
            "metadata": merged_meta,
            "content": merged_content,
            "has_overrides": session.overlay.has_character_overrides(name),
            "overrides": session.overlay.get_character_overrides(name),
        })

    @bp.route("/api/sessions/<session_id>/overrides/characters/<name>", methods=["PUT"])
    def set_character_override(session_id: str, name: str):
        """设置角色覆盖（部分更新）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        data = request.json or {}
        overrides = {}
        if "metadata" in data:
            overrides["metadata"] = data["metadata"]
        if "content" in data:
            overrides["content"] = data["content"]
        if not overrides:
            return json_error("需要 metadata 或 content 字段")
        session.overlay.set_character_overrides(name, overrides)
        return jsonify({
            "message": "覆盖已保存",
            "overrides": session.overlay.get_character_overrides(name),
        })

    @bp.route("/api/sessions/<session_id>/overrides/characters/<name>", methods=["DELETE"])
    def delete_character_override(session_id: str, name: str):
        """删除角色覆盖，还原为模板。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        ok = session.overlay.delete_character_overrides(name)
        if not ok:
            return json_error(f"角色没有覆盖数据: {name}")
        return jsonify({"message": "已还原为模板"})

    @bp.route("/api/sessions/<session_id>/overrides/items/<item_id>", methods=["GET"])
    def get_item_merged(session_id: str, item_id: str):
        """获取物品的合并后数据（模板 + 会话覆盖）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        try:
            doc = doc_mgr.read_document("items", item_id)
        except DocumentNotFoundError:
            return json_error(f"物品不存在: {item_id}", 404)
        merged_meta, merged_content = session.overlay.apply_item_overrides(
            item_id, doc["metadata"], doc["content"]
        )
        return jsonify({
            "metadata": merged_meta,
            "content": merged_content,
            "has_overrides": session.overlay.has_item_overrides(item_id),
            "overrides": session.overlay.get_item_overrides(item_id),
        })

    @bp.route("/api/sessions/<session_id>/overrides/items/<item_id>", methods=["PUT"])
    def set_item_override(session_id: str, item_id: str):
        """设置物品覆盖（部分更新）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        data = request.json or {}
        overrides = {}
        if "metadata" in data:
            overrides["metadata"] = data["metadata"]
        if "content" in data:
            overrides["content"] = data["content"]
        if not overrides:
            return json_error("需要 metadata 或 content 字段")
        session.overlay.set_item_overrides(item_id, overrides)
        return jsonify({
            "message": "覆盖已保存",
            "overrides": session.overlay.get_item_overrides(item_id),
        })

    @bp.route("/api/sessions/<session_id>/overrides/items/<item_id>", methods=["DELETE"])
    def delete_item_override(session_id: str, item_id: str):
        """删除物品覆盖，还原为模板。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        ok = session.overlay.delete_item_overrides(item_id)
        if not ok:
            return json_error(f"物品没有覆盖数据: {item_id}")
        return jsonify({"message": "已还原为模板"})

    # 角色列表与详情（供前端 CharacterBrowser / CharacterDetailCard 使用）
    @bp.route("/api/characters", methods=["GET"])
    def character_list():
        try:
            docs = doc_mgr.list_documents("characters", include_content=True)
        except ValueError:
            return jsonify([])
        return jsonify(docs)

    @bp.route("/api/characters/<path:name>", methods=["GET"])
    def character_detail(name: str):
        try:
            doc = doc_mgr.read_document("characters", name)
        except DocumentNotFoundError:
            return json_error(f"角色不存在: {name}", 404)
        return jsonify({
            "content": doc["content"],
            "metadata": doc["metadata"],
        })

    # 物品列表与详情（供前端 ItemBrowser / ItemDetailCard 使用）
    @bp.route("/api/items", methods=["GET"])
    def item_list():
        try:
            docs = doc_mgr.list_documents("items", include_content=True)
        except ValueError:
            return jsonify([])
        return jsonify(docs)

    @bp.route("/api/items/<path:name>", methods=["GET"])
    def item_detail(name: str):
        try:
            doc = doc_mgr.read_document("items", name)
        except DocumentNotFoundError:
            return json_error(f"物品不存在: {name}", 404)
        return jsonify({
            "content": doc["content"],
            "metadata": doc["metadata"],
            "hash": doc.get("hash", ""),
        })

    @bp.route("/api/items/<path:name>", methods=["PUT"])
    def item_save(name: str):
        """永久保存物品源文件（含 hash 冲突检测）。"""
        data = request.json or {}
        content = data.get("content", "")
        metadata = data.get("metadata")
        expected_hash = data.get("hash", "")

        try:
            result = doc_mgr.save_document(
                "items", name, content,
                metadata=metadata,
                expected_hash=expected_hash or None,
            )
        except ConflictError:
            return json_error(
                "保存冲突：文件已被其他进程修改。请刷新后重试。", 409
            )
        except DocumentNotFoundError:
            return json_error(f"物品不存在: {name}", 404)
        except Exception as e:
            return json_error(f"保存失败: {e}", 500)

        return jsonify(result)

    # 角色头像
    @bp.route("/api/characters/<name>/avatar")
    def character_avatar(name: str):
        path = find_avatar_path(name)
        if not path:
            abort(404)
        directory = os.path.dirname(path)
        basename = os.path.basename(path)
        return send_from_directory(directory, basename)

    # 角色立绘
    @bp.route("/api/characters/<name>/skin")
    def character_skin(name: str):
        from avatar_color import find_skin_path
        path = find_skin_path(name)
        if not path:
            abort(404)
        directory = os.path.dirname(path)
        basename = os.path.basename(path)
        return send_from_directory(directory, basename)

    # 角色卡面
    @bp.route("/api/characters/<name>/card-face")
    def character_card_face(name: str):
        from avatar_color import find_card_face_path
        path = find_card_face_path(name)
        if not path:
            abort(404)
        directory = os.path.dirname(path)
        basename = os.path.basename(path)
        return send_from_directory(directory, basename)

    # 卡面裁剪参数
    @bp.route("/api/characters/<name>/card-face-crop")
    def character_card_face_crop(name: str):
        from avatar_color import get_card_face_crop
        crop = get_card_face_crop(name)
        return jsonify(crop or {})

    app.register_blueprint(bp)
