"""
Scene blueprint — 场景角色/物品/覆盖管理。
"""

import logging
import os
from flask import Blueprint, jsonify, request, send_from_directory, abort

from shared.helpers import json_error
from shared.cache import invalidate_all_caches
from document_manager import DocumentNotFoundError, ConflictError
from avatar_color import find_avatar_path, get_theme_color, ensure_theme_color


def _get_session(session_mgr, session_id):
    """获取会话，不存在则返回 None。"""
    session = session_mgr.get_session(session_id)
    if not session:
        return None
    return session


logger = logging.getLogger(__name__)


def register(app, managers):
    session_mgr = managers["session"]
    doc_mgr = managers["document"]
    wb_mgr = managers["worldbook"]

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
        overrides = session.overlay.get_character_overrides(name) or {}
        progress = overrides.get("progress", {}) or {}

        # 派生战斗数值（与 CombatUnit.from_character_metadata 同源）
        from combat_engine.entity import CombatUnit
        unit = CombatUnit.from_character_metadata(merged_meta, team="player")

        return jsonify({
            "metadata": merged_meta,
            "content": merged_content,
            "has_overrides": session.overlay.has_character_overrides(name),
            "overrides": overrides,
            "progress": {
                "level": int(progress.get("level", 1) or 1),
                "xp": int(progress.get("xp", 0) or 0),
            },
            "combat_stats": {
                "hp": unit.max_hp, "patk": unit.PATK, "matk": unit.MATK, "heal": unit.HEAL,
                "def": unit.DEF, "res": unit.RES, "spd": unit.SPD, "hit": unit.HIT,
                "eva": unit.EVA, "max_ap": unit.MAX_AP,
            },
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

    def _session_media_override(session_id, name: str, media_type: str):
        """会话角色形象覆盖优先：resources/characters/<name>/<type>.<ext>。

        命中返回 (directory, basename)，否则 None（回退全局媒体）。
        """
        if not session_id:
            return None
        session = _get_session(session_mgr, session_id)
        if not session:
            return None
        from session_resources import find_session_media_path
        override = find_session_media_path(session.data_dir, name, media_type)
        if not override:
            return None
        return os.path.dirname(override), os.path.basename(override)

    # 角色头像
    @bp.route("/api/characters/<name>/avatar")
    def character_avatar(name: str):
        override = _session_media_override(request.args.get("session_id"), name, "avatar")
        if override:
            return send_from_directory(override[0], override[1])
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
        override = _session_media_override(request.args.get("session_id"), name, "skin")
        if override:
            return send_from_directory(override[0], override[1])
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
        override = _session_media_override(request.args.get("session_id"), name, "card_face")
        if override:
            return send_from_directory(override[0], override[1])
        path = find_card_face_path(name)
        if not path:
            abort(404)
        directory = os.path.dirname(path)
        basename = os.path.basename(path)
        return send_from_directory(directory, basename)

    # ── 角色卡导入（第三方角色 → data/characters/<name>/ + 内嵌世界书） ──

    @bp.route("/api/characters/import", methods=["POST"])
    def import_character_card():
        """导入 SillyTavern 角色卡（PNG 内嵌 JSON 或纯 JSON）。

        产出：
        1. data/characters/<slug>/index.md（frontmatter 含 source: imported 来源标识，
           scenario/first_mes 供会话首轮叙述注入）
        2. 头像：卡片原图（剥离内嵌 JSON 块）
        3. 内嵌世界书：若有 character_book，自动导入为世界书（与整合包统一管理）
        """
        from character_card import (CharacterCardError, import_character_card)

        f = request.files.get("file")
        if not f:
            return json_error("需要上传角色卡文件（PNG 或 JSON）")
        raw = f.read()
        if not raw:
            return json_error("文件内容为空")
        try:
            result = import_character_card(raw, wb_mgr=wb_mgr)
        except CharacterCardError as exc:
            return json_error(f"角色卡解析失败：{exc}", 400)
        except Exception as exc:
            logger.exception("角色卡解析异常")
            return json_error(f"角色卡解析异常：{exc!s}", 400)

        # 失效文档缓存（角色列表/实体索引）
        try:
            import index_manager as idxmgr
            invalidate_all_caches(idxmgr, managers.get("wiki"))
        except Exception:
            pass

        return jsonify(result), 201

    app.register_blueprint(bp)
