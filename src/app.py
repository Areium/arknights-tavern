"""
Arknight-txt API 服务 (Phase 1 重构版)

架构：
- SessionManager：多会话支持
- LLMBackendManager：多后端检测 + 自动降级
- DocumentManager：文档 CRUD + 冲突检测
- SSE 流式响应 + 结构化事件

设计文档见项目根目录 CLAUDE.md
"""

import os
import sys
import json
import time
import uuid
import queue
import logging
from typing import Optional

# Ensure project root is on sys.path for data/ access
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import yaml
from flask import Flask, jsonify, request, Response, stream_with_context, send_from_directory
from flask_cors import CORS

from llm_backend_manager import LLMBackendManager
from session_manager import SessionManager
from document_manager import DocumentManager, ConflictError, DocumentNotFoundError

# ── 初始化 ──

app = Flask(__name__)
CORS(app)

# 全局管理器
llm_backend = LLMBackendManager()
session_manager = SessionManager(llm_backend)
doc_manager = DocumentManager()

logger = logging.getLogger(__name__)

# ── 辅助函数 ──


def _get_session(session_id: str):
    """获取会话，不存在则返回 404。不检查 is_usable，由各路由自行判断。"""
    session = session_manager.get_session(session_id)
    if not session:
        return None
    return session


def _require_usable(session):
    """检查会话是否可以进行 LLM 操作，不可用则返回 503 错误响应。"""
    if not session.is_usable:
        return _json_error("LLM 后端不可用，无法执行此操作", 503)
    return None


def _json_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


# ══════════════════════════════════════════════════════
# 1.  状态 / 健康检查
# ══════════════════════════════════════════════════════


@app.route("/api/status", methods=["GET"])
def api_status():
    """后端状态 + LLM 后端信息。"""
    return jsonify({
        "status": "ok",
        "llm": llm_backend.get_status(),
        "sessions": len(session_manager.list_sessions()),
    })


# ══════════════════════════════════════════════════════
# 2.  会话管理
# ══════════════════════════════════════════════════════


@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    """列出所有会话。"""
    return jsonify(session_manager.list_sessions())


@app.route("/api/sessions", methods=["POST"])
def create_session():
    """创建新会话，可选绑定剧情。"""
    data = request.json or {}
    mode = data.get("mode", "free")
    if mode not in ("free", "story"):
        return _json_error("mode 必须是 'free' 或 'story'")
    session = session_manager.create_session(
        name=data.get("name", ""),
        mode=mode,
    )

    # 可选：创建时绑定剧情
    plot_id = data.get("plot_id", "").strip()
    if plot_id and mode == "story":
        from session_overlay import _resolve_plot_dir
        resolved = _resolve_plot_dir(plot_id) or plot_id
        import os as _os2
        plot_dir = _os2.path.join(_os2.path.dirname(__file__), "..", "data", "plots", resolved)
        if _os2.path.isdir(plot_dir):
            session.overlay.load_quests_from_plot(plot_id)

    return jsonify(session.to_dict()), 201


@app.route("/api/sessions/<session_id>", methods=["GET"])
def get_session(session_id: str):
    """获取单个会话详情。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    return jsonify(session.to_dict())


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id: str):
    """删除会话。"""
    ok = session_manager.delete_session(session_id)
    if not ok:
        return _json_error("会话不存在", 404)
    return jsonify({"message": "会话已删除"})


@app.route("/api/sessions/<session_id>/rename", methods=["PUT"])
def rename_session(session_id: str):
    """重命名会话。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    new_name = data.get("name", "").strip()
    if not new_name:
        return _json_error("需要 name 参数")
    session_manager.rename_session(session_id, new_name)
    return jsonify({"message": "已重命名", "name": new_name})


# ══════════════════════════════════════════════════════
# 2.5 剧情列表
# ══════════════════════════════════════════════════════


@app.route("/api/plots", methods=["GET"])
def list_plots():
    """列出所有可用剧情（从 plots/_index.md 解析）。"""
    import os as _os3
    import frontmatter as _fm
    index_path = _os3.path.join(_os3.path.dirname(__file__), "..", "data", "plots", "_index.md")
    if not _os3.path.isfile(index_path):
        return jsonify([])

    with open(index_path, "r", encoding="utf-8") as f:
        data = _fm.load(f)

    plots = []
    for pid, info in data.metadata.get("index", {}).items():
        plots.append({
            "id": pid,
            "name": info.get("name", pid),
            "category": info.get("category", "main"),
            "priority": info.get("priority", 5),
            "trigger_location": info.get("trigger_location", []),
            "trigger_character": info.get("trigger_character", []),
        })
    # 按 priority 降序
    plots.sort(key=lambda p: p["priority"], reverse=True)
    return jsonify(plots)


# ══════════════════════════════════════════════════════
# 3.  场景角色管理
# ══════════════════════════════════════════════════════


@app.route("/api/sessions/<session_id>/characters", methods=["GET"])
def list_scene_characters(session_id: str):
    """获取当前场景中的角色列表。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    return jsonify({
        "characters": session.scene_manager.get_scene_characters(),
        "active": session.scene_manager.active,
    })


@app.route("/api/sessions/<session_id>/characters/load", methods=["POST"])
def load_scene_character(session_id: str):
    """加载角色到场景。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    err = _require_usable(session)
    if err:
        return err
    data = request.json or {}
    name = data.get("character")
    if not name:
        return _json_error("需要 character 参数")
    ok = session.scene_manager.load_character(name)
    if not ok:
        return _json_error(f"无法加载角色: {name}")
    return jsonify(session.to_dict())


@app.route("/api/sessions/<session_id>/characters/unload", methods=["POST"])
def unload_scene_character(session_id: str):
    """从场景移除角色。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    name = data.get("character")
    if not name:
        return _json_error("需要 character 参数")
    ok = session.scene_manager.unload_character(name)
    if not ok:
        return _json_error(f"角色不在场景中: {name}")
    return jsonify(session.to_dict())


@app.route("/api/sessions/<session_id>/characters/switch", methods=["POST"])
def switch_scene_character(session_id: str):
    """切换当前对话目标。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    name = data.get("character")
    if not name:
        return _json_error("需要 character 参数")
    ok = session.scene_manager.switch_active(name)
    if not ok:
        return _json_error(f"角色不在场景中: {name}")
    return jsonify(session.to_dict())


# ══════════════════════════════════════════════════════
# 4.  对话 / 叙述 API
# ══════════════════════════════════════════════════════


@app.route("/api/sessions/<session_id>/chat", methods=["POST"])
def session_chat(session_id: str):
    """剧情模式：对当前活跃角色说话。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    err = _require_usable(session)
    if err:
        return err
    data = request.json or {}
    user_input = data.get("input", "").strip()
    if not user_input:
        return _json_error("需要 input 参数")

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
        logger.error("对话出错: %s", e)
        return _json_error(f"对话处理失败: {e!s}", 500)


@app.route("/api/sessions/<session_id>/group-chat", methods=["POST"])
def session_group_chat(session_id: str):
    """群聊模式：发送消息给场景中所有角色。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    err = _require_usable(session)
    if err:
        return err
    data = request.json or {}
    user_input = data.get("input", "").strip()
    if not user_input:
        return _json_error("需要 input 参数")

    player_info = {"identity": data.get("identity", "博士")}
    env_context = session.environment.build_context()

    try:
        results = session.scene_manager.group_chat(
            user_input, player_info, env_context
        )
        # 合并环境更新
        for r in results:
            session.environment.apply_update(r.get("env_updates", {}))
        return jsonify({"responses": results})
    except Exception as e:
        logger.error("群聊出错: %s", e)
        return _json_error(f"群聊处理失败: {e!s}", 500)


def _build_choices(session, narrative: str) -> list[str]:
    """根据配置生成选项：LLM 自动生成或内置默认（不再包含"自行输入..."）。"""
    config = llm_backend.get_config()
    llm_choices = []
    if config.get("auto_generate_choices"):
        count = config.get("choice_count", 3)
        llm = session.get_llm()
        if llm:
            try:
                active = session.scene_manager.active or ""
                chars = session.scene_manager.get_scene_characters()
                prompt = (
                    f"【场景叙述】\n{narrative}\n\n"
                    f"【当前场景角色】{', '.join(chars) if chars else '无'}\n"
                    + (f"【对话目标】{active}\n" if active else "")
                    + f"\n请基于以上叙述，生成恰好 {count} 个合理的后续行动选项，"
                      f"每个选项不超过 15 个字，表达简洁直接。"
                      f"每行一个选项，不要编号，不要加任何前缀或解释。"
                )
                response = llm.chat([
                    {"role": "system", "content": "你是明日方舟文字冒险游戏的选项生成器。根据当前剧情，生成合理且多样化的后续行动选项。"},
                    {"role": "user", "content": prompt},
                ], stream=False)
                lines = [l.strip() for l in response.strip().split("\n") if l.strip()]
                lines = [l for l in lines if len(l) <= 30 and not l.startswith("#")]
                if lines:
                    llm_choices = lines[:count]
            except Exception:
                pass

    # 始终将"继续推进剧情"放在第一位
    options = ["继续推进剧情"]
    options.extend(llm_choices)
    if len(options) == 1:
        active = session.scene_manager.active
        if active:
            options.append(f"对{active}说话")
    return options


@app.route("/api/sessions/<session_id>/narrate", methods=["GET"])
def session_narrate(session_id: str):
    """剧情推进叙述（SSE 流式）。

    返回结构化 SSE 事件：
      data: {"type": "text", "data": {"token": "..."}}
      data: {"type": "scene_event", "data": {"event": "...", ...}}
      data: {"type": "choice", "data": {"options": [...]}}
      data: {"type": "done", "data": {"stream_id": "..."}}
    """
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    err = _require_usable(session)
    if err:
        return err

    stream_id = f"narr_{uuid.uuid4().hex[:12]}"
    player_info = {"identity": request.args.get("identity", "博士")}
    user_action = request.args.get("action", "").strip()
    env_context = session.environment.build_context()

    # 注入最近回忆上下文，帮助 LLM 保持剧情连贯
    recent_memories = session.get_memories()[-3:]
    if recent_memories:
        mem_lines = ["\n【剧情回顾】"]
        for m in recent_memories:
            mem_lines.append(f"- 第{m['round_start']}-{m['round_end']}轮：{m['summary']}")
        env_context += "\n".join(mem_lines)

    def generate():
        yield f"data: {json.dumps({'type': 'meta', 'data': {'stream_id': stream_id}})}\n\n"

        try:
            narrative, env_updates = session.scene_manager.narrate(
                player_info, env_context
            )
            session.environment.apply_update(env_updates)

            # 环境变化时发出 scene_event
            if env_updates:
                yield f"data: {json.dumps({'type': 'scene_event', 'data': {
                    'event': 'environment_changed',
                    'env': {
                        'location': session.environment.location,
                        'weather': session.environment.weather,
                        'time': session.environment.time_of_day,
                    },
                    'stream_id': stream_id
                }})}\n\n"

            # 回忆系统：记录叙述并检查是否需要生成回忆
            if session.mode == "story":
                session.add_narration(narrative, user_action)
                config = llm_backend.get_config()
                interval = config.get("memory_interval", 5)
                if session.should_generate_memory(interval):
                    memory = session.generate_memory()
                    if memory:
                        yield f"data: {json.dumps({'type': 'memory_event', 'data': {
                            'memory': memory,
                            'stream_id': stream_id
                        }})}\n\n"

            # 流式输出叙述文本
            for ch in narrative:
                yield f"data: {json.dumps({'type': 'text', 'data': {'token': ch, 'stream_id': stream_id}})}\n\n"

            # 生成选项
            options = _build_choices(session, narrative)

            yield f"data: {json.dumps({'type': 'choice', 'data': {'options': options, 'stream_id': stream_id}})}\n\n"

        except Exception as e:
            logger.error("叙述出错: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e), 'stream_id': stream_id}})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'data': {'stream_id': stream_id}})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/sessions/<session_id>/narrate-continue", methods=["POST"])
def session_narrate_continue(session_id: str):
    """非流式叙述（前端不使用 SSE 时的回退）。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    err = _require_usable(session)
    if err:
        return err
    data = request.json or {}
    player_info = {"identity": data.get("identity", "博士")}
    env_context = session.environment.build_context()

    # 注入最近回忆上下文
    recent_memories = session.get_memories()[-3:]
    if recent_memories:
        mem_lines = ["\n【剧情回顾】"]
        for m in recent_memories:
            mem_lines.append(f"- 第{m['round_start']}-{m['round_end']}轮：{m['summary']}")
        env_context += "\n".join(mem_lines)

    try:
        narrative, env_updates = session.scene_manager.narrate(
            player_info, env_context,
            user_action=data.get("action", ""),
        )
        session.environment.apply_update(env_updates)

        # 回忆系统
        response_extra = {}
        if session.mode == "story":
            session.add_narration(narrative, data.get("action", ""))
            config = llm_backend.get_config()
            interval = config.get("memory_interval", 5)
            if session.should_generate_memory(interval):
                memory = session.generate_memory()
                if memory:
                    response_extra["memory"] = memory

        options = _build_choices(session, narrative)
        return jsonify({
            "narrative": narrative,
            "env_updates": env_updates,
            "choices": options,
            **response_extra,
        })
    except Exception as e:
        logger.error("叙述出错: %s", e)
        return _json_error(f"叙述失败: {e!s}", 500)


@app.route("/api/sessions/<session_id>/narrate-variant", methods=["POST"])
def session_narrate_variant(session_id: str):
    """生成叙述变体（不记录到历史，由前端管理变体列表）。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    err = _require_usable(session)
    if err:
        return err
    data = request.json or {}
    player_info = {"identity": data.get("identity", "博士")}
    prompt = data.get("prompt", "").strip()
    env_context = session.environment.build_context()

    recent_memories = session.get_memories()[-3:]
    if recent_memories:
        mem_lines = ["\n【剧情回顾】"]
        for m in recent_memories:
            mem_lines.append(f"- 第{m['round_start']}-{m['round_end']}轮：{m['summary']}")
        env_context += "\n".join(mem_lines)

    try:
        narrative, env_updates = session.scene_manager.narrate(
            player_info, env_context,
            user_action=prompt,
        )
        return jsonify({"narrative": narrative})
    except Exception as e:
        logger.error("生成叙述变体出错: %s", e)
        return _json_error(f"生成失败: {e!s}", 500)


@app.route("/api/sessions/<session_id>/narrate-update", methods=["POST"])
def session_narrate_update(session_id: str):
    """更新指定轮次的叙述文本（前端切换变体时同步）。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    round_num = data.get("round")
    narrative = data.get("narrative", "")
    if round_num is None:
        return _json_error("需要 round 参数")
    session.update_narration(int(round_num), narrative)
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════
# 5.  环境控制
# ══════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════
# 4.5 任务系统
# ══════════════════════════════════════════════════════


@app.route("/api/sessions/<session_id>/quests", methods=["GET"])
def get_quests(session_id: str):
    """获取会话的完整任务列表（含状态）。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)

    plot_id = session.overlay.get_plot_id()
    if not plot_id:
        return jsonify({"plot_id": None, "quests": []})

    from session_overlay import _parse_quests_md
    quests = _parse_quests_md(plot_id)
    states = session.overlay.get_quest_states()

    # 合并状态，过滤掉 hidden 任务
    visible_quests = []
    for q in quests:
        qid = q["id"]
        st = states.get(qid, {})
        status = st.get("status", "hidden")
        if status == "hidden":
            continue  # 未触发的任务不返回给前端
        q["status"] = status
        q["updated_at"] = st.get("updated_at", 0)
        visible_quests.append(q)

    return jsonify({"plot_id": plot_id, "quests": visible_quests})


@app.route("/api/sessions/<session_id>/quests/load", methods=["PUT"])
def load_quests(session_id: str):
    """加载指定剧情的任务到当前会话。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)

    data = request.json or {}
    plot_id = data.get("plot_id", "").strip()
    if not plot_id:
        return _json_error("需要 plot_id 参数")

    # 验证剧情目录存在
    from session_overlay import _resolve_plot_dir
    resolved = _resolve_plot_dir(plot_id) or plot_id
    import os as _os
    plot_dir = _os.path.join(_os.path.dirname(__file__), "..", "data", "plots", resolved)
    if not _os.path.isdir(plot_dir):
        return _json_error(f"剧情不存在: {plot_id}", 404)

    session.overlay.load_quests_from_plot(plot_id)

    from session_overlay import _parse_quests_md
    quests = _parse_quests_md(plot_id)
    states = session.overlay.get_quest_states()
    visible_quests = []
    for q in quests:
        status = states.get(q["id"], {}).get("status", "hidden")
        if status == "hidden":
            continue
        q["status"] = status
        q["updated_at"] = states.get(q["id"], {}).get("updated_at", 0)
        visible_quests.append(q)

    return jsonify({"plot_id": plot_id, "quests": visible_quests})


@app.route("/api/sessions/<session_id>/quests/<quest_id>", methods=["PATCH"])
def update_quest_state(session_id: str, quest_id: str):
    """更新单个任务状态。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)

    data = request.json or {}
    status = data.get("status", "").strip()
    if status not in ("hidden", "locked", "visible", "active", "completed", "failed"):
        return _json_error("status 必须是 hidden/locked/visible/active/completed/failed")

    session.overlay.set_quest_state(quest_id, status)
    return jsonify({"quest_id": quest_id, "status": status})


@app.route("/api/sessions/<session_id>/environment", methods=["GET"])
def get_environment(session_id: str):
    """获取当前环境状态。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    return jsonify({
        "location": session.environment.location,
        "weather": session.environment.weather,
        "time": session.environment.time_of_day,
        "atmosphere": session.environment.atmosphere,
    })


@app.route("/api/sessions/<session_id>/environment", methods=["PUT"])
def update_environment(session_id: str):
    """更新环境设置。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不可用", 404)
    data = request.json or {}

    if "location" in data:
        session.environment.set_location(data["location"])
    if "weather" in data:
        session.environment.set_weather(data["weather"])
    if "time" in data:
        session.environment.time_of_day = data["time"]

    return jsonify({
        "location": session.environment.location,
        "weather": session.environment.weather,
        "time": session.environment.time_of_day,
    })


@app.route("/api/environment/presets", methods=["GET"])
def get_environment_presets():
    """返回可用的环境预设（地点、天气、时间）。"""
    import frontmatter

    # 解析地点索引
    locations = []
    index_path = os.path.join(os.path.dirname(__file__), "..", "environment", "Location", "_index.md")
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = frontmatter.load(f)
        for name, info in index_data.metadata.get("index", {}).items():
            locations.append({
                "name": name,
                "region": info.get("region", ""),
                "summary": info.get("summary", ""),
                "tags": info.get("tags", []),
            })
    except Exception as e:
        logger.warning("解析地点索引失败: %s", e)

    # 解析天气预设
    weathers = []
    weather_dir = os.path.join(os.path.dirname(__file__), "..", "environment", "weather")
    try:
        for entry in sorted(os.listdir(weather_dir)):
            entry_path = os.path.join(weather_dir, entry)
            # 实体文件夹
            if os.path.isdir(entry_path):
                index_md = os.path.join(entry_path, "index.md")
                if os.path.isfile(index_md):
                    try:
                        with open(index_md, "r", encoding="utf-8") as f:
                            data = frontmatter.load(f)
                        wt = data.metadata.get("weather_type", {})
                        if wt.get("name"):
                            weathers.append({
                                "name": wt["name"],
                                "id": wt.get("id", ""),
                                "icon": wt.get("icon", ""),
                                "category": wt.get("category", ""),
                            })
                    except Exception:
                        continue
            # 传统 .md 文件（向后兼容）
            elif entry.endswith(".md") and not entry.startswith("_") and entry != "TEMPLATE.md":
                try:
                    with open(entry_path, "r", encoding="utf-8") as f:
                        data = frontmatter.load(f)
                    wt = data.metadata.get("weather_type", {})
                    if wt.get("name"):
                        weathers.append({
                            "name": wt["name"],
                            "id": wt.get("id", ""),
                            "icon": wt.get("icon", ""),
                            "category": wt.get("category", ""),
                        })
                except Exception:
                    continue
    except Exception as e:
        logger.warning("解析天气预设失败: %s", e)

    # 时间预设
    times = ["清晨", "上午", "中午", "下午", "傍晚", "夜晚", "深夜"]

    return jsonify({
        "locations": locations,
        "weathers": weathers,
        "times": times,
    })


# ══════════════════════════════════════════════════════
# 5.5  回忆系统
# ══════════════════════════════════════════════════════


@app.route("/api/sessions/<session_id>/memories", methods=["GET"])
def get_memories(session_id: str):
    """获取会话的回忆列表。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    return jsonify({
        "memories": session.get_memories(),
        "narration_count": session.narration_count,
        "last_memory_end": session._last_memory_end,
    })


@app.route("/api/sessions/<session_id>/memories/regenerate", methods=["POST"])
def regenerate_memories(session_id: str):
    """清除已有回忆，用当前间隔重新从完整历史生成。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    config = llm_backend.get_config()
    interval = config.get("memory_interval", 5)
    memories = session.regenerate_memories(interval)
    return jsonify({
        "memories": memories,
        "narration_count": session.narration_count,
    })


@app.route("/api/sessions/<session_id>/rollback", methods=["POST"])
def rollback_session(session_id: str):
    """回退会话到指定轮次，删除之后的叙述历史和回忆。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    target = data.get("round", 0)
    if not isinstance(target, int) or target < 0:
        return _json_error("round 必须是非负整数", 400)
    result = session.rollback_to_round(target)
    return jsonify(result)


# ══════════════════════════════════════════════════════
# 6.  文档管理
# ══════════════════════════════════════════════════════


@app.route("/api/documents/tree", methods=["GET"])
def document_tree():
    """获取文档树（按类别分组）。"""
    try:
        tree = doc_manager.list_all_documents()
        return jsonify(tree)
    except Exception as e:
        logger.error("获取文档树失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/documents/categories", methods=["GET"])
def document_categories():
    """获取文档类别列表。"""
    return jsonify(doc_manager.list_categories())


@app.route("/api/documents/<category>", methods=["GET"])
def list_documents(category: str):
    """获取指定类别的文档列表。"""
    try:
        docs = doc_manager.list_documents(category, include_content=True)
        return jsonify(docs)
    except ValueError as e:
        return _json_error(str(e), 404)
    except Exception as e:
        logger.error("列举文档失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/documents/<category>/<path:doc_id>", methods=["GET"])
def read_document(category: str, doc_id: str):
    """读取文档内容。"""
    try:
        doc = doc_manager.read_document(category, doc_id)
        return jsonify(doc)
    except DocumentNotFoundError:
        return _json_error("文档不存在", 404)
    except Exception as e:
        logger.error("读取文档失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/documents/<category>/<path:doc_id>", methods=["PUT"])
def save_document(category: str, doc_id: str):
    """保存文档（含冲突检测）。"""
    data = request.json or {}
    content = data.get("content", "")
    metadata = data.get("metadata")
    expected_hash = data.get("expected_hash")
    auto_commit = data.get("auto_commit", False)

    try:
        result = doc_manager.save_document(
            category, doc_id,
            content=content,
            metadata=metadata,
            expected_hash=expected_hash,
        )
        if auto_commit:
            doc_manager.git_commit(
                os.path.join(doc_manager._root, result["path"]),
                message=data.get("commit_message"),
            )
        return jsonify(result)
    except ConflictError as e:
        return jsonify({
            "error": "文件已被修改",
            "current_hash": e.current_hash,
            "expected_hash": e.expected_hash,
            "current_content": e.current_content,
        }), 409
    except DocumentNotFoundError:
        return _json_error("文档不存在", 404)
    except Exception as e:
        logger.error("保存文档失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/documents/<category>", methods=["POST"])
def create_document(category: str):
    """创建新文档。"""
    data = request.json or {}
    doc_id = data.get("id", "").strip()
    if not doc_id:
        return _json_error("需要 id 参数")

    try:
        result = doc_manager.create_document(
            category, doc_id,
            content=data.get("content", ""),
            metadata=data.get("metadata"),
        )
        return jsonify(result), 201
    except FileExistsError as e:
        return _json_error(str(e), 409)
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.error("创建文档失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/documents/<category>/<path:doc_id>", methods=["DELETE"])
def delete_document(category: str, doc_id: str):
    """删除文档。"""
    try:
        doc_manager.delete_document(category, doc_id)
        return jsonify({"message": "文档已删除"})
    except DocumentNotFoundError:
        return _json_error("文档不存在", 404)
    except Exception as e:
        logger.error("删除文档失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/documents/<category>/folders", methods=["POST"])
def create_folder(category: str):
    """在类别中创建文件夹。"""
    data = request.json or {}
    folder_path = data.get("path", "").strip()
    if not folder_path:
        return _json_error("需要 path 参数")
    try:
        result = doc_manager.create_folder(category, folder_path)
        return jsonify(result), 201
    except FileExistsError as e:
        return _json_error(str(e), 409)
    except ValueError as e:
        return _json_error(str(e), 400)


@app.route("/api/documents/<category>/folders/<path:folder_path>", methods=["DELETE"])
def delete_folder(category: str, folder_path: str):
    """删除空文件夹。"""
    try:
        result = doc_manager.delete_folder(category, folder_path)
        return jsonify(result)
    except DocumentNotFoundError:
        return _json_error("文件夹不存在", 404)
    except ValueError as e:
        return _json_error(str(e), 400)


@app.route("/api/documents/<category>/<path:doc_id>/move", methods=["POST"])
def move_document(category: str, doc_id: str):
    """移动/重命名文档。"""
    data = request.json or {}
    new_path = data.get("new_path", "").strip() or None
    if not new_path:
        return _json_error("需要 new_path 参数")
    try:
        result = doc_manager.move_document(category, doc_id, new_path)
        return jsonify(result)
    except DocumentNotFoundError:
        return _json_error("文档不存在", 404)
    except FileExistsError as e:
        return _json_error(str(e), 409)
    except ValueError as e:
        return _json_error(str(e), 400)


@app.route("/api/documents/<category>/folders/<path:folder_path>/move", methods=["POST"])
def move_folder(category: str, folder_path: str):
    """移动/重命名文件夹。"""
    data = request.json or {}
    new_path = data.get("new_path", "").strip() or None
    if not new_path:
        return _json_error("需要 new_path 参数")
    try:
        result = doc_manager.move_folder(category, folder_path, new_path)
        return jsonify(result)
    except DocumentNotFoundError:
        return _json_error("文件夹不存在", 404)
    except FileExistsError as e:
        return _json_error(str(e), 409)
    except ValueError as e:
        return _json_error(str(e), 400)


# ══════════════════════════════════════════════════════
# 10. 会话覆盖（角色/物品/环境的会话级修改）
# ══════════════════════════════════════════════════════


@app.route("/api/sessions/<session_id>/overrides", methods=["GET"])
def get_session_overrides(session_id: str):
    """获取会话的全部覆盖数据。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    return jsonify(session.overlay.to_dict())


@app.route("/api/sessions/<session_id>/overrides/characters/<name>", methods=["GET"])
def get_character_merged(session_id: str, name: str):
    """获取角色的合并后数据（模板 + 会话覆盖）。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    try:
        doc = doc_manager.read_document("characters", name)
    except DocumentNotFoundError:
        return _json_error(f"角色不存在: {name}", 404)
    merged_meta, merged_content = session.overlay.apply_character_overrides(
        name, doc["metadata"], doc["content"]
    )
    return jsonify({
        "metadata": merged_meta,
        "content": merged_content,
        "has_overrides": session.overlay.has_character_overrides(name),
        "overrides": session.overlay.get_character_overrides(name),
    })


@app.route("/api/sessions/<session_id>/overrides/characters/<name>", methods=["PUT"])
def set_character_override(session_id: str, name: str):
    """设置角色覆盖（部分更新）。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    overrides = {}
    if "metadata" in data:
        overrides["metadata"] = data["metadata"]
    if "content" in data:
        overrides["content"] = data["content"]
    if not overrides:
        return _json_error("需要 metadata 或 content 字段")
    session.overlay.set_character_overrides(name, overrides)
    return jsonify({"message": "覆盖已保存", "overrides": session.overlay.get_character_overrides(name)})


@app.route("/api/sessions/<session_id>/overrides/characters/<name>", methods=["DELETE"])
def delete_character_override(session_id: str, name: str):
    """删除角色覆盖，还原为模板。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    ok = session.overlay.delete_character_overrides(name)
    if not ok:
        return _json_error(f"角色没有覆盖数据: {name}")
    return jsonify({"message": "已还原为模板"})


@app.route("/api/sessions/<session_id>/overrides/items/<item_id>", methods=["GET"])
def get_item_merged(session_id: str, item_id: str):
    """获取物品的合并后数据（模板 + 会话覆盖）。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    try:
        doc = doc_manager.read_document("items", item_id)
    except DocumentNotFoundError:
        return _json_error(f"物品不存在: {item_id}", 404)
    merged_meta, merged_content = session.overlay.apply_item_overrides(
        item_id, doc["metadata"], doc["content"]
    )
    return jsonify({
        "metadata": merged_meta,
        "content": merged_content,
        "has_overrides": session.overlay.has_item_overrides(item_id),
        "overrides": session.overlay.get_item_overrides(item_id),
    })


@app.route("/api/sessions/<session_id>/overrides/items/<item_id>", methods=["PUT"])
def set_item_override(session_id: str, item_id: str):
    """设置物品覆盖（部分更新）。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    overrides = {}
    if "metadata" in data:
        overrides["metadata"] = data["metadata"]
    if "content" in data:
        overrides["content"] = data["content"]
    if not overrides:
        return _json_error("需要 metadata 或 content 字段")
    session.overlay.set_item_overrides(item_id, overrides)
    return jsonify({"message": "覆盖已保存", "overrides": session.overlay.get_item_overrides(item_id)})


@app.route("/api/sessions/<session_id>/overrides/items/<item_id>", methods=["DELETE"])
def delete_item_override(session_id: str, item_id: str):
    """删除物品覆盖，还原为模板。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    ok = session.overlay.delete_item_overrides(item_id)
    if not ok:
        return _json_error(f"物品没有覆盖数据: {item_id}")
    return jsonify({"message": "已还原为模板"})


@app.route("/api/sessions/<session_id>/overrides/environment", methods=["PUT"])
def set_environment_override(session_id: str):
    """设置环境覆盖（时间、氛围等）。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    allowed = {"time_of_day", "atmosphere"}
    overrides = {k: v for k, v in data.items() if k in allowed}
    if not overrides:
        return _json_error("无可更新的环境字段")
    session.overlay.set_environment_overrides(overrides)
    # 立即应用到当前环境状态
    if "time_of_day" in overrides:
        session.environment.time_of_day = overrides["time_of_day"]
    if "atmosphere" in overrides:
        session.environment.atmosphere = overrides["atmosphere"]
    return jsonify({"message": "环境覆盖已保存"})


@app.route("/api/sessions/<session_id>/combat-mode", methods=["PUT"])
def set_combat_mode(session_id: str):
    """切换战斗模式（narrative / tactical）。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    mode = data.get("mode", "").strip()
    if mode not in ("narrative", "tactical"):
        return _json_error("mode 必须是 'narrative' 或 'tactical'")
    session.overlay.set_combat_mode(mode)
    return jsonify({"combat_mode": mode})


@app.route("/api/sessions/<session_id>/combat-mode", methods=["GET"])
def get_combat_mode(session_id: str):
    """获取当前战斗模式。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    return jsonify({"combat_mode": session.overlay.get_combat_mode()})


@app.route("/api/sessions/<session_id>/overrides/environment", methods=["DELETE"])
def delete_environment_override(session_id: str):
    """清除环境覆盖。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    session.overlay.delete_environment_overrides()
    return jsonify({"message": "环境覆盖已清除"})


# ══════════════════════════════════════════════════════
# 11.  Combat — 战斗系统
# ══════════════════════════════════════════════════════

from combat_session import CombatSession  # noqa: E402


@app.route("/api/sessions/<session_id>/combat/start", methods=["POST"])
def combat_start(session_id: str):
    """开始一场战斗。请求体: {encounter_id: str, characters: [str]}"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)

    data = request.json or {}
    encounter_id = data.get("encounter_id", "初遇整合运动")
    character_names = data.get("characters", [])

    try:
        combat = CombatSession(session_id)
        state = combat.start(encounter_id, character_names=character_names)
        session.combat = combat
        return jsonify(state)
    except ValueError as e:
        return _json_error(str(e), 404)
    except Exception as e:
        logger.exception("Failed to start combat")
        return _json_error(f"战斗启动失败: {e}", 500)


@app.route("/api/sessions/<session_id>/combat/state", methods=["GET"])
def combat_state(session_id: str):
    """获取当前战斗状态快照。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)

    if not session.combat:
        return _json_error("没有进行中的战斗", 404)

    return jsonify(session.combat.get_state())


@app.route("/api/sessions/<session_id>/combat/action", methods=["POST"])
def combat_action(session_id: str):
    """提交玩家操作。请求体: {action: str, card_index: int, target: [row, col]}"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)

    if not session.combat:
        return _json_error("没有进行中的战斗", 404)

    data = request.json or {}
    result = session.combat.handle_action(data)

    if not result.get("ok"):
        return _json_error(result.get("error", "操作失败"), 400)

    return jsonify(result.get("state", {}))


@app.route("/api/sessions/<session_id>/combat/end-turn", methods=["POST"])
def combat_end_turn(session_id: str):
    """手动结束当前回合。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)

    if not session.combat:
        return _json_error("没有进行中的战斗", 404)

    result = session.combat.end_turn()

    if not result.get("ok"):
        return _json_error(result.get("error", "操作失败"), 400)

    return jsonify(result.get("state", {}))


@app.route("/api/sessions/<session_id>/combat/events")
def combat_events(session_id: str):
    """SSE 端点：流式推送战斗事件。"""
    session = session_manager.get_session(session_id)
    if not session or not session.combat:
        def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'No combat session'}})}\n\n"
        return Response(error_stream(), mimetype="text/event-stream")

    combat = session.combat

    def generate():
        stream_id = f"combat_{uuid.uuid4().hex[:8]}"
        yield f"data: {json.dumps({'type': 'meta', 'data': {'stream_id': stream_id}})}\n\n"

        while combat.engine and not combat.engine.is_battle_over():
            try:
                ev = combat.event_queue.get(timeout=30)
                event_data = {
                    "type": ev.type,
                    "data": ev.data,
                }
                yield f"event: {ev.type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

                if ev.type == "battle_end":
                    yield f"data: {json.dumps({'type': 'done', 'data': {'stream_id': stream_id}})}\n\n"
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat', 'data': {}})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ══════════════════════════════════════════════════════
# 7.  LLM 配置 / 管理
# ══════════════════════════════════════════════════════


@app.route("/api/llm/status", methods=["GET"])
def llm_status():
    """LLM 后端详细状态。"""
    return jsonify(llm_backend.get_status())


@app.route("/api/llm/refresh", methods=["POST"])
def llm_refresh():
    """重新检测 LLM 后端。"""
    llm_backend._detect()
    return jsonify(llm_backend.get_status())


@app.route("/api/llm/switch", methods=["POST"])
def llm_switch():
    """手动切换到指定后端（供前端切换用）。"""
    data = request.json or {}
    endpoint_id = data.get("endpoint")
    if not endpoint_id:
        return _json_error("需要 endpoint 参数")

    llm_backend._ensure_detected()

    # 重新排序优先级
    found = None
    for ep in llm_backend._all_endpoints:
        if ep.id == endpoint_id and ep.available:
            found = ep
            break

    if not found:
        return _json_error(f"后端不可用: {endpoint_id}")

    # 临时将选中后端设为主后端
    llm_backend._primary = found
    llm_backend._fallback = None
    for ep in llm_backend._all_endpoints:
        if ep.id != endpoint_id and ep.available:
            llm_backend._fallback = ep
            break

    return jsonify(llm_backend.get_status())


@app.route("/api/llm/config", methods=["GET"])
def llm_get_config():
    """获取 LLM 配置。"""
    return jsonify(llm_backend.get_config())


@app.route("/api/llm/config", methods=["PUT"])
def llm_update_config():
    """更新 LLM 配置。"""
    data = request.json or {}
    allowed = {"api_key", "base_url", "cloud_model", "ollama_url", "ollama_model", "theme",
               "auto_generate_choices", "choice_count", "memory_interval"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return _json_error("没有可更新的字段")
    config = llm_backend.update_config(updates)
    return jsonify(config)


@app.route("/api/llm/test", methods=["POST"])
def llm_test_connection():
    """测试 LLM 后端连通性（不持久化）。"""
    data = request.json or {}
    endpoint_type = data.get("type", "")
    if endpoint_type not in ("cloud", "ollama"):
        return _json_error("type 必须是 'cloud' 或 'ollama'")

    params: dict = {}
    if endpoint_type == "cloud":
        params = {
            "api_key": data.get("api_key", ""),
            "base_url": data.get("base_url", ""),
            "model": data.get("model", ""),
        }
    else:
        params = {
            "ollama_url": data.get("ollama_url", ""),
            "model": data.get("model", ""),
        }

    result = llm_backend.test_connection(endpoint_type, params)
    return jsonify(result)


# ══════════════════════════════════════════════════════
# 8.  向后兼容端点（原有 app.py 端点）
# ══════════════════════════════════════════════════════


@app.route("/api/characters", methods=["GET"])
def get_characters():
    """兼容：获取角色列表。"""
    try:
        # 直接从 DocumentManager 获取
        from document_manager import DocumentManager
        dm = doc_manager
        chars = dm.list_documents("characters", include_content=True)
        return jsonify([
            {"id": c["id"], "name": c["title"]}
            for c in chars
        ])
    except Exception as e:
        app.logger.error(f"获取角色列表失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/characters/<character_id>", methods=["GET"])
def get_character_config(character_id):
    """兼容：获取指定角色的配置。"""
    try:
        doc = doc_manager.read_document("characters", character_id)
        return jsonify({"metadata": doc["metadata"], "content": doc["content"]})
    except DocumentNotFoundError:
        return jsonify({"error": "Character not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# 9.  物品管理
# ══════════════════════════════════════════════════════


@app.route("/api/items", methods=["GET"])
def get_items():
    """获取所有可用物品列表。"""
    try:
        items = doc_manager.list_documents("items", include_content=True)
        return jsonify([
            {"id": i["id"], "name": i["title"]}
            for i in items
        ])
    except Exception as e:
        app.logger.error(f"获取物品列表失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/items/<item_id>", methods=["GET"])
def get_item_detail(item_id):
    """获取物品详情。"""
    try:
        doc = doc_manager.read_document("items", item_id)
        return jsonify({"metadata": doc["metadata"], "content": doc["content"]})
    except DocumentNotFoundError:
        return jsonify({"error": "物品不存在"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>/items", methods=["GET"])
def get_scene_items(session_id: str):
    """获取场景中的物品列表。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    return jsonify({"items": session.scene_manager.get_scene_items()})


@app.route("/api/sessions/<session_id>/items/add", methods=["POST"])
def add_scene_item(session_id: str):
    """添加物品到场景。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    item_id = data.get("item_id", "").strip()
    if not item_id:
        return _json_error("需要 item_id 参数")
    try:
        doc = doc_manager.read_document("items", item_id)
    except DocumentNotFoundError:
        return _json_error(f"物品不存在: {item_id}", 404)
    ok = session.scene_manager.add_item(item_id, doc["metadata"])
    if not ok:
        return _json_error(f"物品已在场景中: {item_id}")
    return jsonify(session.to_dict())


@app.route("/api/sessions/<session_id>/items/remove", methods=["POST"])
def remove_scene_item(session_id: str):
    """从场景移除物品。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    item_id = data.get("item_id", "").strip()
    if not item_id:
        return _json_error("需要 item_id 参数")
    ok = session.scene_manager.remove_item(item_id)
    if not ok:
        return _json_error(f"物品不在场景中: {item_id}")
    return jsonify(session.to_dict())


@app.route("/api/chat", methods=["POST"])
def legacy_chat():
    """兼容：旧的单角色聊天端点。"""
    data = request.json or {}
    char_id = data.get("character_id")
    user_input = data.get("input", "")

    if not char_id or user_input is None:
        return jsonify({"error": "character_id and input are required"}), 400

    # 自动创建或复用会话
    session = session_manager.get_session(f"legacy_{char_id}")
    if not session:
        session = session_manager.create_session(
            name=f"legacy_{char_id}", mode="story"
        )
        session.scene_manager.load_character(char_id)

    player_info = {"identity": data.get("identity", "博士")}
    env_context = session.environment.build_context()

    try:
        response, env_updates = session.scene_manager.chat(
            user_input, player_info, env_context
        )
        session.environment.apply_update(env_updates)
        return jsonify({"response": response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reset", methods=["POST"])
def legacy_reset():
    """兼容：重置指定角色的对话历史。"""
    data = request.json or {}
    char_id = data.get("character_id")
    if char_id:
        session_manager.delete_session(f"legacy_{char_id}")
    return jsonify({"message": "ok"})


# ══════════════════════════════════════════════════════
# 资产 API（图像等静态资源）
# ══════════════════════════════════════════════════════

# 支持的图片格式
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


def _list_entity_images() -> list[dict]:
    """扫描所有实体文件夹下的图片文件。

    Returns:
        [{category, entity, entity_name, images: [{name, path, url}]}]
    """
    categories = doc_manager.list_categories()
    result = []

    for cat_meta in categories:
        cat = doc_manager.get_category(cat_meta["id"])
        if not cat or not os.path.isdir(cat.directory):
            continue
        cat_dir = cat.directory

        for root, dirs, _files in os.walk(cat_dir):
            for d in sorted(dirs):
                d_full = os.path.join(root, d)
                index_md = os.path.join(d_full, "index.md")
                if not os.path.isfile(index_md):
                    continue
                # 这是实体文件夹，扫描其中的图片
                images = []
                for f in sorted(os.listdir(d_full)):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in _IMAGE_EXTS and f != "index.md":
                        entity_rel = os.path.relpath(d_full, cat_dir).replace("\\", "/")
                        images.append({
                            "name": f,
                            "path": f"{cat['id']}/{entity_rel}/{f}",
                            "url": f"/api/assets/{cat['id']}/{entity_rel}/{f}",
                        })

                if images:
                    # 读取 entity 的 frontmatter 获取显示名
                    entity_name = d
                    try:
                        import frontmatter as _fm
                        with open(index_md, "r", encoding="utf-8") as fh:
                            meta = _fm.load(fh).metadata
                        entity_name = meta.get("name", d)
                    except Exception:
                        pass

                    result.append({
                        "category": cat["id"],
                        "entity": d,
                        "entity_name": entity_name,
                        "images": images,
                    })

    return result


@app.route("/api/assets/images", methods=["GET"])
def list_asset_images():
    """列出所有实体文件夹下的图片资产。"""
    return jsonify(_list_entity_images())


@app.route("/api/assets/data-dir", methods=["GET"])
def get_data_directory():
    """返回 data/ 目录的绝对路径（供 Electron 打开目录使用）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return jsonify({"path": os.path.join(root, "data")})


@app.route("/api/assets/<category>/<path:filename>", methods=["GET"])
def serve_asset(category: str, filename: str):
    """提供静态资产文件（图片等）。

    URL 格式: /api/assets/{category}/{entity}/{image_name}
    例如: /api/assets/characters/银灰/avatar.png
    """
    cat = doc_manager.get_category(category)
    if not cat:
        return jsonify({"error": f"未知类别: {category}"}), 404

    # filename 包含 entity/image_name
    filepath = os.path.join(cat.directory, filename)
    if not os.path.isfile(filepath):
        return jsonify({"error": "文件不存在"}), 404

    directory = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    return send_from_directory(directory, basename)


# ══════════════════════════════════════════════════════
# 启动入口
# ══════════════════════════════════════════════════════

def main():
    """启动 API 服务。"""
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    status = llm_backend.get_status()
    print(f"\n  API 服务启动: http://{host}:{port}")
    print(f"  LLM 后端: {status['primary']['name'] if status['primary'] else '无'} / "
          f"备用: {status['fallback']['name'] if status['fallback'] else '无'}")
    print(f"  文档类别: {len(doc_manager.list_categories())} 个")
    print()

    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    main()
