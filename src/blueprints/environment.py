"""
Environment blueprint — 环境状态管理、预设列表、任务系统。
"""

import os
import logging
from pathlib import Path

import frontmatter
from flask import Blueprint, jsonify, request

from shared.helpers import json_error
from session_overlay import _resolve_plot_dir, _parse_quests_md

logger = logging.getLogger(__name__)

# Project root from inside blueprints/ is two levels up → src/
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = Path(_project_root).parent  # repo root for data/ and environment/ access

# 时间预设列表
_TIME_PRESETS = ["清晨", "上午", "中午", "下午", "傍晚", "夜晚", "深夜"]


def _get_session(session_mgr, session_id):
    """获取会话，不存在则返回 None。"""
    session = session_mgr.get_session(session_id)
    if not session:
        return None
    return session


def register(app, managers):
    bp = Blueprint("environment", __name__)
    session_mgr = managers["session"]

    # ── 1. GET /api/sessions/<session_id>/environment ──
    @bp.route("/api/sessions/<session_id>/environment", methods=["GET"])
    def get_environment(session_id: str):
        """获取当前会话的环境状态。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        env = session.environment
        return jsonify({
            "location": env.location,
            "weather": env.weather,
            "time": env.time_of_day,
            "atmosphere": env.atmosphere,
        })

    # ── 2. PUT /api/sessions/<session_id>/environment ──
    @bp.route("/api/sessions/<session_id>/environment", methods=["PUT"])
    def update_environment(session_id: str):
        """更新会话的环境状态（部分更新）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        data = request.json or {}
        env = session.environment

        if "location" in data:
            env.set_location(data["location"])
        if "weather" in data:
            env.set_weather(data["weather"])
        if "time" in data:
            env.time_of_day = data["time"]
        if "atmosphere" in data:
            if isinstance(data["atmosphere"], list):
                env.atmosphere = data["atmosphere"]
            elif isinstance(data["atmosphere"], str):
                env.atmosphere = [data["atmosphere"]]

        return jsonify({
            "location": env.location,
            "weather": env.weather,
            "time": env.time_of_day,
            "atmosphere": env.atmosphere,
        })

    # ── 3. GET /api/environment/presets ──
    @bp.route("/api/environment/presets", methods=["GET"])
    def environment_presets():
        """扫描环境预设（地点、天气、时间）并返回可用选项。"""
        env_root = _REPO_ROOT / "environment"

        # 扫描地点
        locations: list[dict] = []
        loc_dir = env_root / "Location"
        if loc_dir.is_dir():
            for item in sorted(loc_dir.iterdir()):
                if item.is_dir():
                    index_md = item / "index.md"
                    if index_md.is_file():
                        try:
                            with open(index_md, "r", encoding="utf-8") as f:
                                fm = frontmatter.load(f)
                            locations.append({
                                "id": item.name,
                                "name": fm.metadata.get("name", item.name),
                            })
                        except Exception:
                            locations.append({"id": item.name, "name": item.name})
                elif item.is_file() and item.suffix == ".md":
                    stem = item.stem
                    if stem in ("_index", "_INDEX", "README", "TEMPLATE", "index"):
                        continue
                    try:
                        with open(item, "r", encoding="utf-8") as f:
                            fm = frontmatter.load(f)
                        locations.append({
                            "id": stem,
                            "name": fm.metadata.get("name", stem),
                        })
                    except Exception:
                        locations.append({"id": stem, "name": stem})

        # 扫描天气
        weathers: list[dict] = []
        weather_dir = env_root / "weather"
        if weather_dir.is_dir():
            for item in sorted(weather_dir.iterdir()):
                if item.is_dir():
                    index_md = item / "index.md"
                    if index_md.is_file():
                        try:
                            with open(index_md, "r", encoding="utf-8") as f:
                                fm = frontmatter.load(f)
                            wtype = fm.metadata.get("weather_type", {})
                            weathers.append({
                                "id": item.name,
                                "name": wtype.get("name", item.name),
                            })
                        except Exception:
                            weathers.append({"id": item.name, "name": item.name})
                elif item.is_file() and item.suffix == ".md":
                    stem = item.stem
                    if stem in ("_index", "_INDEX", "README", "TEMPLATE", "index"):
                        continue
                    try:
                        with open(item, "r", encoding="utf-8") as f:
                            fm = frontmatter.load(f)
                        wtype = fm.metadata.get("weather_type", {})
                        weathers.append({
                            "id": stem,
                            "name": wtype.get("name", stem),
                        })
                    except Exception:
                        weathers.append({"id": stem, "name": stem})

        return jsonify({
            "locations": locations,
            "weathers": weathers,
            "times": _TIME_PRESETS,
        })

    # ── 4. GET /api/sessions/<session_id>/quests ──
    @bp.route("/api/sessions/<session_id>/quests", methods=["GET"])
    def get_quests(session_id: str):
        """获取当前会话的任务列表（含状态合并）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        plot_id = session.overlay.get_plot_id()
        if not plot_id:
            return jsonify({"plot_id": None, "quests": []})

        # 解析剧情任务定义
        quests = _parse_quests_md(plot_id)
        states = session.overlay.get_quest_states()

        # 合并状态，过滤 hidden
        visible_quests = []
        for q in quests:
            qid = q.get("id", "")
            state = states.get(qid, {})
            status = state.get("status", "hidden")
            if status == "hidden":
                continue
            entry = dict(q)
            entry["status"] = status
            entry["updated_at"] = state.get("updated_at", 0)
            visible_quests.append(entry)

        return jsonify({"plot_id": plot_id, "quests": visible_quests})

    # ── 5. PUT /api/sessions/<session_id>/quests/load ──
    @bp.route("/api/sessions/<session_id>/quests/load", methods=["PUT"])
    def load_quests(session_id: str):
        """加载指定剧情 ID 的任务到会话。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        data = request.json or {}
        plot_id = data.get("plot_id", "").strip()
        if not plot_id:
            return json_error("需要 plot_id 参数")

        # 验证剧情目录存在
        resolved = _resolve_plot_dir(plot_id) or plot_id
        plot_dir = _REPO_ROOT / "data" / "plots" / resolved
        if not plot_dir.is_dir():
            return json_error(f"剧情不存在: {plot_id}", 404)

        # 加载任务
        session.overlay.load_quests_from_plot(plot_id)

        quests = _parse_quests_md(plot_id)
        states = session.overlay.get_quest_states()

        # 合并状态（返回所有任务，含 hidden 使前端可以管理可见性）
        full_quests = []
        for q in quests:
            qid = q.get("id", "")
            state = states.get(qid, {})
            entry = dict(q)
            entry["status"] = state.get("status", "hidden")
            entry["updated_at"] = state.get("updated_at", 0)
            full_quests.append(entry)

        return jsonify({"plot_id": plot_id, "quests": full_quests})

    # ── 6. PATCH /api/sessions/<session_id>/quests/<quest_id> ──
    @bp.route("/api/sessions/<session_id>/quests/<quest_id>", methods=["PATCH"])
    def update_quest_state(session_id: str, quest_id: str):
        """更新单个任务的状态。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        data = request.json or {}
        status = data.get("status", "").strip()
        allowed = {"hidden", "locked", "active", "completed", "failed"}
        if status not in allowed:
            return json_error(f"无效的任务状态: {status}，可选值: {', '.join(sorted(allowed))}")

        session.overlay.set_quest_state(quest_id, status)
        state = session.overlay.get_quest_states().get(quest_id, {})
        return jsonify({
            "quest_id": quest_id,
            "status": status,
            "updated_at": state.get("updated_at", 0),
        })

    app.register_blueprint(bp)
