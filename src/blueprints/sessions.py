"""
Sessions blueprint — 会话管理与剧情列表。
"""

import os
import logging
from pathlib import Path

import frontmatter
from flask import Blueprint, jsonify, request

from shared.helpers import json_error

logger = logging.getLogger(__name__)

_SESSION_BG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Project root = src/ (from blueprints/sessions.py)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Repository root for data/ access
_REPO_ROOT = Path(_project_root).parent


def _load_plot_opening(session, plot_id: str):
    """加载剧情的开场配置到会话中。

    从 index.md frontmatter 读取所有开场字段。
    """
    from session_overlay import _resolve_plot_dir, _read_plot_file

    try:
        result = _read_plot_file(plot_id)
        if not result:
            return
        meta, body = result

        # 1. 设置环境
        location = meta.get("initial_location", "")
        time_val = meta.get("initial_time", "")
        atmosphere = meta.get("initial_atmosphere", "")
        if location:
            session.environment.location = location
        if time_val:
            session.environment.time_of_day = time_val
        if atmosphere:
            if isinstance(atmosphere, str):
                session.environment.atmosphere = [atmosphere]
            elif isinstance(atmosphere, list):
                session.environment.atmosphere = atmosphere

        # 2. 加载初始角色（跳过不存在的角色 & 博士=玩家）
        player_identities = {"博士"}
        for char_name in meta.get("initial_characters", []):
            name = char_name.strip()
            if name and name not in player_identities:
                ok = session.scene_manager.load_character(name)
                if ok:
                    logger.debug("开场加载角色: %s", name)

        # 3. 设置默认对话目标（第一个非玩家角色）
        if not session.scene_manager.active:
            chars = session.scene_manager.get_scene_characters()
            if chars:
                session.scene_manager.active = chars[0]

        # 4. 存储开场上下文（首次叙述注入用）
        from session_overlay import _extract_section
        scene_desc = _extract_section(body, "开场设置") if body else ""
        if not scene_desc:
            scene_desc = body.strip()[:500] if body else ""
        if scene_desc:
            session.overlay.set_plot_context(scene_desc)

        logger.info("剧情 %s 开场已加载: loc=%s time=%s chars=%d",
                     plot_id, location, time_val,
                     len(session.scene_manager.get_scene_characters()))
    except Exception as e:
        logger.warning("加载剧情开场失败 %s: %s", plot_id, e)


def register(app, managers):
    bp = Blueprint("sessions", __name__)
    session_mgr = managers["session"]

    # ── 会话 CRUD ──

    @bp.route("/api/sessions", methods=["GET"])
    def list_sessions():
        """列出所有会话。"""
        return jsonify(session_mgr.list_sessions())

    @bp.route("/api/sessions", methods=["POST"])
    def create_session():
        """创建新会话，可选绑定剧情。"""
        data = request.json or {}
        mode = data.get("mode", "free")
        if mode not in ("free", "story"):
            return json_error("mode 必须是 'free' 或 'story'")

        combat_mode = data.get("combat_mode", "narrative")
        if combat_mode not in ("narrative", "tactical"):
            return json_error("combat_mode 必须是 'narrative' 或 'tactical'")

        plot_id = data.get("plot_id", "").strip()
        plot_name = ""
        if plot_id and mode == "story":
            from session_overlay import _resolve_plot_dir, _read_plot_file
            result = _read_plot_file(plot_id)
            if result:
                plot_name = result[0].get("name", "")
            if not plot_name:
                resolved = _resolve_plot_dir(plot_id) or plot_id
                plot_name = resolved

        session = session_mgr.create_session(
            name=data.get("name", ""),
            mode=mode,
            plot_name=plot_name if not data.get("name") else "",
            combat_mode=combat_mode,
        )

        if plot_id and mode == "story":
            from session_overlay import _resolve_plot_dir
            resolved = _resolve_plot_dir(plot_id) or plot_id
            plot_dir = _REPO_ROOT / "data" / "plots" / resolved
            if plot_dir.is_dir():
                session.overlay.load_quests_from_plot(plot_id)
                _load_plot_opening(session, plot_id)
                session.overlay.init_session_docs(plot_id)

        return jsonify(session.to_dict()), 201

    @bp.route("/api/sessions/<session_id>", methods=["GET"])
    def get_session(session_id: str):
        """获取单个会话详情。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        return jsonify(session.to_dict())

    @bp.route("/api/sessions/<session_id>", methods=["DELETE"])
    def delete_session(session_id: str):
        """删除会话。"""
        ok = session_mgr.delete_session(session_id)
        if not ok:
            return json_error("会话不存在", 404)
        return jsonify({"message": "会话已删除"})

    @bp.route("/api/sessions/<session_id>/rename", methods=["PUT"])
    def rename_session(session_id: str):
        """重命名会话。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        data = request.json or {}
        new_name = data.get("name", "").strip()
        if not new_name:
            return json_error("需要 name 参数")
        session_mgr.rename_session(session_id, new_name)
        return jsonify({"message": "已重命名", "name": new_name})

    @bp.route("/api/sessions/<session_id>/custom-prompt", methods=["PUT"])
    def set_custom_prompt(session_id: str):
        """设置会话的自定义提示词。"""
        session_obj = session_mgr.get_session(session_id)
        if not session_obj:
            return json_error("会话不存在", 404)
        data = request.json or {}
        prompt = data.get("prompt", "").strip()
        if prompt:
            session_obj.overlay.set_custom_prompt(prompt)
        else:
            session_obj.overlay.delete_custom_prompt()
        return jsonify({
            "message": "自定义提示词已更新",
            "custom_prompt": session_obj.overlay.get_custom_prompt(),
        })

    @bp.route("/api/sessions/<session_id>/backgrounds/<path:filename>", methods=["GET"])
    def session_background(session_id: str, filename: str):
        """会话级战斗背景覆盖图：data/memory/sessions/<mode>/<id>/backgrounds/<file>。"""
        from flask import send_from_directory

        sessions_dir = _REPO_ROOT / "data" / "memory" / "sessions"
        safe_name = filename.replace("\\", "/")
        for mode in ("story", "free"):
            bg_dir = sessions_dir / mode / session_id / "backgrounds"
            if not bg_dir.is_dir():
                continue
            filepath = (bg_dir / safe_name).resolve()
            # 防路径穿越
            if not str(filepath).startswith(str(bg_dir.resolve()) + os.sep):
                return json_error("无效的文件路径", 403)
            if filepath.suffix.lower() not in _SESSION_BG_EXTS:
                return json_error("不允许的文件类型", 403)
            if filepath.is_file():
                return send_from_directory(str(bg_dir), safe_name)
        return json_error("文件不存在", 404)

    # ── 剧情列表 ──

    @bp.route("/api/plots", methods=["GET"])
    def list_plots():
        """列出所有可用剧情（从 data/plots/ 子目录扫描）。"""
        plots_dir = _REPO_ROOT / "data" / "plots"
        if not plots_dir.is_dir():
            return jsonify([])

        plots = []
        for entry in sorted(plots_dir.iterdir()):
            if not entry.is_dir():
                continue
            md = entry / "index.md"
            if not md.is_file():
                continue
            try:
                with open(md, "r", encoding="utf-8") as f:
                    plot_data = frontmatter.load(f)
                meta = plot_data.metadata
                plots.append({
                    "id": meta.get("id", entry.name),
                    "name": meta.get("name", entry.name),
                    "category": meta.get("category", "main"),
                    "priority": meta.get("priority", 5),
                    "trigger_location": meta.get("trigger", {}).get("location", []),
                    "trigger_character": meta.get("trigger", {}).get("character", []),
                })
            except Exception:
                continue
        plots.sort(key=lambda p: p["priority"], reverse=True)
        return jsonify(plots)

    app.register_blueprint(bp)
