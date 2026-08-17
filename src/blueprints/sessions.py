"""
Sessions blueprint — 会话管理与剧情列表。
"""

import os
import re
import logging
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

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

        # 玩家身份角色（用户自身，默认"博士"）
        player_identity = str(data.get("identity", "") or "").strip() or "博士"

        session = session_mgr.create_session(
            name=data.get("name", ""),
            mode=mode,
            plot_name=plot_name if not data.get("name") else "",
            combat_mode=combat_mode,
            player_identity=player_identity,
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

    # ── 会话资源空间（角色形象覆盖 + 背景覆盖 + 文档副本） ──

    @bp.route("/api/sessions/<session_id>/resources", methods=["GET"])
    def session_resources_overview(session_id: str):
        """会话资源总览：背景覆盖 + 角色形象覆盖 + 文档副本 + 可用背景 ID。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        session_dir = Path(session.data_dir)

        from combat_data_loader import CombatDataLoader
        from session_resources import list_session_media, session_resources_dir

        loader = CombatDataLoader()

        # 会话背景覆盖
        backgrounds = []
        bg_dir = session_dir / "backgrounds"
        if bg_dir.is_dir():
            for f in sorted(bg_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in _SESSION_BG_EXTS:
                    bg_id = f.stem
                    global_url = loader.background_image_url(bg_id)
                    backgrounds.append({
                        "type": "background",
                        "key": bg_id,
                        "name": f.name,
                        "url": f"/api/sessions/{session_id}/backgrounds/{f.name}",
                        "global_url": global_url,
                        "size": f.stat().st_size,
                        "has_global": global_url is not None,
                    })

        # 会话角色形象覆盖
        _ENDPOINT = {"avatar": "avatar", "skin": "skin", "card_face": "card-face"}
        character_media = []
        for item in list_session_media(session_dir):
            name = item["name"]
            media_type = item["media_type"]
            character_media.append({
                "type": "character_media",
                "key": name,
                "media_type": media_type,
                "name": item["filename"],
                "url": f"/api/characters/{quote(name)}/{_ENDPOINT[media_type]}?session_id={session_id}",
                "global_url": f"/api/characters/{quote(name)}/{_ENDPOINT[media_type]}",
                "size": item["size"],
                "has_global": True,
            })

        return jsonify({
            "session_id": session_id,
            "backgrounds": backgrounds,
            "available_background_ids": loader.list_background_ids(),
            "character_media": character_media,
            "scene_characters": list(session.scene_manager.get_scene_characters()),
            "resources_dir": str(session_resources_dir(session_dir)),
            "backgrounds_dir": str(bg_dir),
        })

    @bp.route("/api/sessions/<session_id>/resources/backgrounds", methods=["POST"])
    def session_bg_upload(session_id: str):
        """上传/替换会话背景覆盖（同 ID 自动替换旧扩展名文件）。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        bg_id = (request.form.get("bg_id") or "").strip()
        if not re.fullmatch(r"[a-z0-9_]+", bg_id):
            return json_error("bg_id 只能包含小写字母、数字、下划线")
        file = request.files.get("file")
        if not file or not file.filename:
            return json_error("需要上传 file")
        ext = Path(file.filename).suffix.lower()
        if ext not in _SESSION_BG_EXTS:
            return json_error("仅支持 png/jpg/jpeg/webp 图片")

        bg_dir = session.data_dir / "backgrounds"
        bg_dir.mkdir(parents=True, exist_ok=True)
        # 同 ID 自动替换：清掉旧扩展名的同 stem 文件
        for old in bg_dir.glob(f"{bg_id}.*"):
            if old.suffix.lower() in _SESSION_BG_EXTS and old.is_file():
                old.unlink()
        target = bg_dir / f"{bg_id}{ext}"
        file.save(str(target))
        return jsonify({
            "message": "上传成功",
            "type": "background",
            "key": bg_id,
            "name": target.name,
            "url": f"/api/sessions/{session_id}/backgrounds/{target.name}",
            "size": target.stat().st_size,
        }), 201

    @bp.route("/api/sessions/<session_id>/resources/backgrounds/<bg_id>", methods=["DELETE"])
    def session_bg_delete(session_id: str, bg_id: str):
        """删除会话背景覆盖（还原为全局背景）。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        if not re.fullmatch(r"[a-z0-9_]+", bg_id):
            return json_error("bg_id 只能包含小写字母、数字、下划线")
        bg_dir = session.data_dir / "backgrounds"
        removed = False
        if bg_dir.is_dir():
            for f in bg_dir.glob(f"{bg_id}.*"):
                if f.suffix.lower() in _SESSION_BG_EXTS and f.is_file():
                    f.unlink()
                    removed = True
        if not removed:
            return json_error("该背景没有会话覆盖", 404)
        return jsonify({"message": "已删除，还原为全局背景", "key": bg_id})

    @bp.route("/api/sessions/<session_id>/resources/characters/<name>/<media_type>", methods=["POST"])
    def session_character_media_upload(session_id: str, name: str, media_type: str):
        """上传/替换会话角色形象覆盖（头像/立绘/卡面，仅影响本会话）。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        from session_resources import (is_safe_entity_name, normalize_media_type,
                                       session_media_dir)
        if not is_safe_entity_name(name):
            return json_error("非法的角色名")
        try:
            media_type = normalize_media_type(media_type)
        except ValueError as e:
            return json_error(str(e))
        file = request.files.get("file")
        if not file or not file.filename:
            return json_error("需要上传 file")
        ext = Path(file.filename).suffix.lower()
        if ext not in _SESSION_BG_EXTS:
            return json_error("仅支持 png/jpg/jpeg/webp 图片")

        media_dir = session_media_dir(session.data_dir, name)
        media_dir.mkdir(parents=True, exist_ok=True)
        for old in media_dir.glob(f"{media_type}.*"):
            if old.suffix.lower() in _SESSION_BG_EXTS and old.is_file():
                old.unlink()
        target = media_dir / f"{media_type}{ext}"
        file.save(str(target))
        return jsonify({
            "message": "上传成功",
            "type": "character_media",
            "key": name,
            "media_type": media_type,
            "name": target.name,
            "size": target.stat().st_size,
        }), 201

    @bp.route("/api/sessions/<session_id>/resources/characters/<name>/<media_type>", methods=["DELETE"])
    def session_character_media_delete(session_id: str, name: str, media_type: str):
        """删除会话角色形象覆盖（还原为全局形象）。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        from session_resources import (is_safe_entity_name, normalize_media_type,
                                       session_media_dir)
        if not is_safe_entity_name(name):
            return json_error("非法的角色名")
        try:
            media_type = normalize_media_type(media_type)
        except ValueError as e:
            return json_error(str(e))
        media_dir = session_media_dir(session.data_dir, name)
        removed = False
        if media_dir.is_dir():
            for f in media_dir.glob(f"{media_type}.*"):
                if f.suffix.lower() in _SESSION_BG_EXTS and f.is_file():
                    f.unlink()
                    removed = True
            try:
                if not any(media_dir.iterdir()):
                    media_dir.rmdir()
            except OSError:
                pass
        if not removed:
            return json_error("该角色没有此类型的会话形象覆盖", 404)
        return jsonify({"message": "已删除，还原为全局形象", "key": name, "media_type": media_type})

    # ── 会话存档导入导出 ──

    @bp.route("/api/sessions/<session_id>/export", methods=["GET"])
    def session_export(session_id: str):
        """导出会话存档 zip（会话目录 + 依赖快照 + manifest），便于社区传播。"""
        from flask import send_file
        from session_export import export_session_zip

        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        session_dir = Path(session.data_dir)
        meta = {
            "name": session.name,
            "combat_mode": session.combat_mode,
            "plot_id": session.overlay.get_plot_id() or None,
            "player_identity": session.player_identity,
        }
        out_dir = tempfile.mkdtemp(prefix="sess_export_")
        out_path = Path(out_dir) / f"session-{session_id}.zip"
        try:
            export_session_zip(session_dir, meta, out_path)
            safe_name = f"session-{session.name}.zip".replace(" ", "_")
            resp = send_file(str(out_path), as_attachment=True, download_name=safe_name)
            resp.call_on_close(
                lambda: (out_path.exists() and out_path.unlink(missing_ok=True),
                         shutil.rmtree(out_dir, ignore_errors=True))
            )
            return resp
        except Exception as e:
            logger.exception("导出会话失败 %s", session_id)
            shutil.rmtree(out_dir, ignore_errors=True)
            return json_error(f"导出失败: {e}", 500)

    @bp.route("/api/sessions/import", methods=["POST"])
    def session_import():
        """导入会话存档 zip：还原依赖到全局库（幂等）、放置并注册会话。"""
        from session_export import import_session_zip

        file = request.files.get("file")
        if not file or not file.filename:
            return json_error("需要上传存档 zip 文件")
        ext = Path(file.filename).suffix.lower()
        if ext != ".zip":
            return json_error("仅支持 .zip 存档")

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
        os.close(tmp_fd)
        try:
            file.save(tmp_path)
            result = import_session_zip(Path(tmp_path), session_mgr)
            return jsonify(result), 201
        except ValueError as e:
            return json_error(str(e), 400)
        except Exception as e:
            logger.exception("导入会话失败")
            return json_error(f"导入失败: {e}", 500)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

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
