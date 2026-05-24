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
import random
import re
import frontmatter
from flask import Flask, jsonify, request, Response, stream_with_context, send_from_directory
from flask_cors import CORS

from llm_backend_manager import LLMBackendManager
from session_manager import SessionManager
from document_manager import DocumentManager, ConflictError, DocumentNotFoundError
import index_manager as idxmgr

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


def _load_plot_opening(session, plot_id: str):
    """加载剧情的开场配置到会话中。

    解析 opening.md，设置环境、加载初始角色、存储开场上下文，
    使首次叙述调用能生成匹配剧情的开场描述。
    """
    from session_overlay import _resolve_plot_dir
    import os as _os3

    resolved = _resolve_plot_dir(plot_id) or plot_id
    plot_dir = _os3.path.join(_os3.path.dirname(__file__), "..", "data", "plots", resolved)
    opening_path = _os3.path.join(plot_dir, "opening.md")
    if not _os3.path.isfile(opening_path):
        logger.debug("剧情 %s 无 opening.md，跳过开场加载", plot_id)
        return

    try:
        with open(opening_path, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)  # noqa
        meta = post.metadata

        # 1. 设置环境
        location = meta.get("initial_location", "")
        time_val = meta.get("initial_time", "")
        atmosphere = meta.get("initial_atmosphere", "")
        if location:
            session.environment.location = location
        if time_val:
            session.environment.time_of_day = time_val
        if atmosphere:
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
        scene_desc = meta.get("opening_scene", "").strip()
        if not scene_desc:
            scene_desc = post.content.strip()[:500]
        if scene_desc:
            session.overlay.set_plot_context(scene_desc)

        logger.info("剧情 %s 开场已加载: loc=%s time=%s chars=%d",
                     plot_id, location, time_val, len(session.scene_manager.get_scene_characters()))
    except Exception as e:
        logger.warning("加载剧情开场失败 %s: %s", plot_id, e)


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

    plot_id = data.get("plot_id", "").strip()
    plot_name = ""
    if plot_id and mode == "story":
        from session_overlay import _resolve_plot_dir
        resolved = _resolve_plot_dir(plot_id) or plot_id
        import os as _os2
        plot_dir = _os2.path.join(_os2.path.dirname(__file__), "..", "data", "plots", resolved)
        plot_index = _os2.path.join(plot_dir, "index.md")
        if _os2.path.isfile(plot_index):
            try:
                with open(plot_index, "r", encoding="utf-8") as _pf:
                    import frontmatter
                    _pfm = frontmatter.load(_pf)
                    plot_name = _pfm.metadata.get("name", resolved)
            except Exception:
                plot_name = resolved
        else:
            plot_name = resolved

    session = session_manager.create_session(
        name=data.get("name", ""),
        mode=mode,
        plot_name=plot_name if not data.get("name") else "",
    )

    if plot_id and mode == "story":
        from session_overlay import _resolve_plot_dir
        resolved = _resolve_plot_dir(plot_id) or plot_id
        import os as _os2
        plot_dir = _os2.path.join(_os2.path.dirname(__file__), "..", "data", "plots", resolved)
        if _os2.path.isdir(plot_dir):
            session.overlay.load_quests_from_plot(plot_id)
            _load_plot_opening(session, plot_id)

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
    """列出所有可用剧情（从 data/plots/ 子目录扫描）。"""
    plots_dir = os.path.join(os.path.dirname(__file__), "..", "data", "plots")
    if not os.path.isdir(plots_dir):
        return jsonify([])

    plots = []
    for entry in sorted(os.listdir(plots_dir)):
        entry_path = os.path.join(plots_dir, entry)
        index_md = os.path.join(entry_path, "index.md")
        if not os.path.isdir(entry_path) or not os.path.isfile(index_md):
            continue
        try:
            with open(index_md, "r", encoding="utf-8") as f:
                data = frontmatter.load(f)
            meta = data.metadata
            plots.append({
                "id": meta.get("id", entry),
                "name": meta.get("name", entry),
                "category": meta.get("category", "main"),
                "priority": meta.get("priority", 5),
                "trigger_location": meta.get("trigger", {}).get("location", []),
                "trigger_character": meta.get("trigger", {}).get("character", []),
            })
        except Exception:
            continue
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

    # 解析地点索引（扫描实体目录）
    locations = []
    loc_dir = os.path.join(os.path.dirname(__file__), "..", "environment", "Location")
    if os.path.isdir(loc_dir):
        for entry in sorted(os.listdir(loc_dir)):
            entry_path = os.path.join(loc_dir, entry)
            index_md = os.path.join(entry_path, "index.md")
            if os.path.isdir(entry_path) and os.path.isfile(index_md):
                try:
                    with open(index_md, "r", encoding="utf-8") as f:
                        fm_data = frontmatter.load(f)
                    meta = fm_data.metadata
                    locations.append({
                        "name": meta.get("name", entry),
                        "region": meta.get("region", ""),
                        "summary": meta.get("summary", ""),
                        "tags": meta.get("tags", []),
                    })
                except Exception:
                    pass

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
    """获取文档类别列表及层级分组。"""
    return jsonify({
        "categories": doc_manager.list_categories(),
        "hierarchy": doc_manager.get_hierarchy(),
    })


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
        idxmgr.invalidate_cache()
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
# 10. 实体索引 / 文档引用管理
# ══════════════════════════════════════════════════════

_entities_cache: dict = {"data": None, "timestamp": 0.0}


def _load_all_entities() -> dict:
    """扫描所有实体目录，返回 {category: [{id, name, summary}]}，带 30s 缓存。"""
    global _entities_cache
    now = time.time()
    if _entities_cache["data"] and now - _entities_cache["timestamp"] < 30:
        return _entities_cache["data"]

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    yaml_path = os.path.join(root, "data", "categories.yaml")
    if not os.path.isfile(yaml_path):
        return {}

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    categories = data.get("categories", {})
    entities: dict = {}

    for cat_name, cat_info in categories.items():
        dir_path = cat_info if isinstance(cat_info, str) else cat_info.get("dir", "")
        full_dir = os.path.join(root, dir_path)
        if not os.path.isdir(full_dir):
            continue

        cat_list = []
        # 实体文件夹
        for item in sorted(os.listdir(full_dir)):
            item_path = os.path.join(full_dir, item)
            index_md = os.path.join(item_path, "index.md")
            if os.path.isdir(item_path) and os.path.isfile(index_md):
                try:
                    with open(index_md, "r", encoding="utf-8") as f:
                        fm_data = frontmatter.load(f)
                    cat_list.append({
                        "id": item,
                        "name": fm_data.metadata.get("name", item),
                        "summary": fm_data.metadata.get("summary", ""),
                    })
                except Exception:
                    continue

        if cat_list:
            cat_list.sort(key=lambda e: e["name"])
            entities[cat_name] = cat_list

    _entities_cache = {"data": entities, "timestamp": now}
    return entities


def _load_hierarchy() -> list:
    """从 categories.yaml 读取索引层级定义，返回 levels 列表。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    yaml_path = os.path.join(root, "data", "categories.yaml")
    if not os.path.isfile(yaml_path):
        return []
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        hierarchy = data.get("hierarchy", {})
        levels = hierarchy.get("levels", [])
        levels.sort(key=lambda x: x["level"])
        return levels
    except Exception:
        return []


@app.route("/api/entities", methods=["GET"])
def list_entities():
    """列出所有已知实体，按类别分组。可选 ?categories=characters,factions 过滤。"""
    entities = _load_all_entities()
    cats = request.args.get("categories", "")
    if cats:
        wanted = set(c.strip() for c in cats.split(",") if c.strip())
        entities = {k: v for k, v in entities.items() if k in wanted}
    return jsonify(entities)


# ══════════════════════════════════════════════════════
# 12a. 文档依赖导入（imports 管理）
# ══════════════════════════════════════════════════════


@app.route("/api/documents/search", methods=["GET"])
def search_documents():
    """搜索同级别或更高级别的文档，用于依赖导入。

    查询参数：
    - q: 搜索关键词（匹配文档 ID 或标题）
    - category: 来源文档类别（用于限定可导入的级别范围）
    - doc_id: 来源文档 ID（排除自身）
    """
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    doc_id = request.args.get("doc_id", "").strip()

    hierarchy = _load_hierarchy()
    cat_level = {}
    for h in hierarchy:
        for c in h.get("categories", []):
            cat_level[c] = h["level"]

    source_level = cat_level.get(category, 99)

    allowed_cats = set()
    for h in hierarchy:
        if h["level"] <= source_level:
            for c in h.get("categories", []):
                allowed_cats.add(c)

    results = []
    for cat_name in allowed_cats:
        try:
            docs = doc_manager.list_documents(cat_name, include_content=False)
        except (ValueError, Exception):
            continue
        for doc in docs:
            doc_path = f"{cat_name}/{doc['id']}"
            if cat_name == category and doc["id"] == doc_id:
                continue
            if q:
                match_id = q.lower() in doc.get("id", "").lower()
                match_title = q.lower() in doc.get("title", doc.get("id", "")).lower()
                if not match_id and not match_title:
                    continue
            results.append({
                "path": doc_path,
                "category": cat_name,
                "id": doc["id"],
                "title": doc.get("title", doc["id"]),
                "level": cat_level.get(cat_name, 99),
            })

    results.sort(key=lambda r: (r["level"], r["path"]))
    return jsonify(results)


@app.route("/api/documents/<category>/<path:doc_id>/imports", methods=["GET"])
def get_doc_imports(category: str, doc_id: str):
    """读取文档 frontmatter 中的 imports 依赖列表。"""
    try:
        doc = doc_manager.read_document(category, doc_id)
    except DocumentNotFoundError:
        return _json_error("文档不存在", 404)
    except Exception as e:
        return _json_error(str(e), 500)

    filepath = doc.get("filepath", "")
    if not filepath or not os.path.isfile(filepath):
        return _json_error("文档文件不存在", 404)

    # 读取原始 frontmatter 以获取完整的 "path | name" 格式
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
    except Exception:
        return jsonify({"imports": []})

    raw_imports = post.metadata.get("imports", [])
    result = []
    seen_paths = set()
    for entry in raw_imports:
        if isinstance(entry, str) and entry.strip():
            path, name = idxmgr.parse_import_entry(entry.strip())
            if path in seen_paths:
                continue
            seen_paths.add(path)
            if not name:
                name = idxmgr.resolve_doc_display_name(path, doc_manager)
            result.append({"path": path, "name": name})

    return jsonify({"imports": result})


@app.route("/api/documents/<category>/<path:doc_id>/imports", methods=["PUT"])
def update_doc_imports(category: str, doc_id: str):
    """更新文档 frontmatter 中的 imports 依赖列表。"""
    data = request.json or {}
    new_imports = data.get("imports", [])

    if not isinstance(new_imports, list):
        return _json_error("imports 必须是一个列表")

    try:
        doc = doc_manager.read_document(category, doc_id)
    except DocumentNotFoundError:
        return _json_error("文档不存在", 404)
    except Exception as e:
        return _json_error(str(e), 500)

    filepath = doc.get("filepath", "")
    if not filepath or not os.path.isfile(filepath):
        return _json_error("文档文件不存在", 404)

    idxmgr.write_imports_to_file(filepath, new_imports, doc_manager)
    idxmgr.invalidate_cache()

    # 返回结构化数据
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
    except Exception:
        return jsonify({"imports": [{"path": p, "name": p} for p in new_imports]})

    raw_imports = post.metadata.get("imports", [])
    result = []
    seen = set()
    for entry in raw_imports:
        if isinstance(entry, str) and entry.strip():
            path, name = idxmgr.parse_import_entry(entry.strip())
            if path in seen:
                continue
            seen.add(path)
            result.append({"path": path, "name": name or idxmgr.resolve_doc_display_name(path, doc_manager)})
    return jsonify({"imports": result})


@app.route("/api/documents/<category>/<path:doc_id>/imports/scan", methods=["POST"])
def scan_doc_imports(category: str, doc_id: str):
    """扫描文档内容，推荐可能需要导入的同级/上级文档。"""
    try:
        doc = doc_manager.read_document(category, doc_id)
    except DocumentNotFoundError:
        return _json_error("文档不存在", 404)
    except Exception as e:
        return _json_error(str(e), 500)

    content = doc.get("content", "")
    current_imports = set(idxmgr.read_imports_from_file(doc.get("filepath", "")))

    hierarchy = _load_hierarchy()
    cat_level = {}
    for h in hierarchy:
        for c in h.get("categories", []):
            cat_level[c] = h["level"]

    source_level = cat_level.get(category, 99)
    allowed_cats = set()
    for h in hierarchy:
        if h["level"] <= source_level:
            for c in h.get("categories", []):
                allowed_cats.add(c)

    # 收集所有可导入文档的 title 和 path
    candidates: list[dict] = []
    for cat_name in allowed_cats:
        try:
            docs = doc_manager.list_documents(cat_name, include_content=True)
        except (ValueError, Exception):
            continue
        for d in docs:
            cand_path = f"{cat_name}/{d['id']}"
            if cand_path == f"{category}/{doc_id}":
                continue
            candidates.append({
                "path": cand_path,
                "category": cat_name,
                "id": d["id"],
                "title": d.get("title", d["id"]),
                "level": cat_level.get(cat_name, 99),
            })

    # 按标题长度降序（长名称优先匹配避免短名误匹配）
    candidates.sort(key=lambda x: len(x["title"]), reverse=True)

    new_suggestions: list[dict] = []
    existing_imports: list[dict] = []
    matched_titles: set = set()

    for cand in candidates:
        title = cand["title"]
        if title in matched_titles:
            continue
        if title in content:
            matched_titles.add(title)
            if cand["path"] in current_imports:
                existing_imports.append(cand)
            else:
                new_suggestions.append(cand)

    # 按级别排序
    new_suggestions.sort(key=lambda x: (x["level"], x["path"]))
    existing_imports.sort(key=lambda x: (x["level"], x["path"]))

    return jsonify({
        "suggestions": new_suggestions,
        "existing": existing_imports,
    })


@app.route("/api/documents/<category>/<path:doc_id>/imports/verify", methods=["GET"])
def verify_doc_imports(category: str, doc_id: str):
    """验证文档的所有 imports 依赖是否指向存在的文档。"""
    try:
        doc = doc_manager.read_document(category, doc_id)
    except DocumentNotFoundError:
        return _json_error("文档不存在", 404)
    except Exception as e:
        return _json_error(str(e), 500)

    filepath = doc.get("filepath", "")
    raw_imports = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
        raw_imports = post.metadata.get("imports", [])
    except Exception:
        pass

    results = []
    for entry in raw_imports:
        if not isinstance(entry, str) or not entry.strip():
            continue
        path, name = idxmgr.parse_import_entry(entry.strip())
        if "/" not in path:
            continue
        imp_cat, imp_id = path.split("/", 1)
        exists = False
        try:
            doc_manager.read_document(imp_cat, imp_id)
            exists = True
        except Exception:
            exists = False
        results.append({
            "path": path,
            "name": name or idxmgr.resolve_doc_display_name(path, doc_manager),
            "exists": exists,
        })

    return jsonify({"results": results})


# ══════════════════════════════════════════════════════
# 12b. 索引管理（基于 imports 的全局依赖聚合）
# ══════════════════════════════════════════════════════


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@app.route("/api/index/overview", methods=["GET"])
def get_index_overview():
    """获取所有文档的分组概览，包含前向引用和反向引用。"""
    try:
        data = idxmgr.build_overview(os.path.join(_project_root(), "data"), doc_manager)
        return jsonify(data)
    except Exception as e:
        logger.error("构建索引概览失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/index/graph", methods=["GET"])
def get_index_graph():
    """获取依赖关系图的节点和边数据。"""
    try:
        data = idxmgr.build_graph_data(os.path.join(_project_root(), "data"), doc_manager)
        return jsonify(data)
    except Exception as e:
        logger.error("构建索引图失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/sessions/<session_id>/index-config", methods=["GET"])
def get_session_index_config(session_id: str):
    """获取会话的索引配置。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    try:
        config = session.overlay.get_index_config()
        return jsonify(config)
    except Exception as e:
        logger.error("读取会话索引配置失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/sessions/<session_id>/index-config", methods=["PUT"])
def save_session_index_config(session_id: str):
    """保存会话的索引配置。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    data = request.json or {}
    try:
        session.overlay.set_index_config(data)
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error("保存会话索引配置失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/sessions/<session_id>/index-config", methods=["DELETE"])
def reset_session_index_config(session_id: str):
    """重置会话的索引配置为默认。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)
    try:
        session.overlay.reset_index_config()
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error("重置会话索引配置失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/index/export", methods=["GET"])
def export_index_yaml():
    """将所有文档的 imports 依赖关系导出为 YAML。"""
    try:
        data_root = os.path.join(_project_root(), "data")
        overview = idxmgr.build_overview(data_root, doc_manager)
        documents = []
        for cat in overview.get("categories", []):
            for doc in cat.get("docs", []):
                imports_list = [f"{imp['path']} | {imp['name']}" if imp.get('name') else imp['path']
                                for imp in doc.get("imports", [])]
                documents.append({
                    "path": doc["path"],
                    "imports": imports_list,
                })
        yaml_str = yaml.dump({"index": {"documents": documents}},
                             allow_unicode=True, default_flow_style=False, sort_keys=False)
        return jsonify({"yaml": yaml_str})
    except Exception as e:
        logger.error("导出索引 YAML 失败: %s", e)
        return _json_error(str(e), 500)


@app.route("/api/index/import", methods=["POST"])
def import_index_yaml():
    """从 YAML 批量更新文档 imports。支持 Dry-run/POST 两阶段写入。"""
    data = request.json or {}
    yaml_str = data.get("yaml", "")
    if not yaml_str:
        return _json_error("需要 yaml 字段")

    try:
        parsed = yaml.safe_load(yaml_str)
        docs = parsed.get("index", {}).get("documents", [])
    except Exception as e:
        return _json_error(f"YAML 解析失败: {e}")

    if not docs:
        return _json_error("YAML 中没有找到 index.documents")

    data_root = os.path.join(_project_root(), "data")

    # Phase 1: Dry-run 校验
    errors = []
    validated = []
    for entry in docs:
        doc_path = entry.get("path", "").strip()
        if not doc_path or "/" not in doc_path:
            errors.append(f"无效路径: {doc_path}")
            continue
        cat, doc_id = doc_path.split("/", 1)
        # 查找文件（多种可能路径）
        candidate_dirs = [
            os.path.join(data_root, "data", cat, doc_id, "index.md"),
            os.path.join(data_root, "data", cat, f"{doc_id}.md"),
            os.path.join(data_root, cat, doc_id, "index.md"),
            os.path.join(data_root, cat, f"{doc_id}.md"),
        ]
        resolved = None
        for cd in candidate_dirs:
            if os.path.isfile(cd):
                resolved = cd
                break
        if not resolved:
            errors.append(f"文件未找到: {doc_path}")
            continue
        # 校验 frontmatter 可解析
        try:
            with open(resolved, "r", encoding="utf-8") as f:
                frontmatter.load(f)
        except Exception:
            errors.append(f"Frontmatter 解析失败: {doc_path}")
            continue
        raw_imports = entry.get("imports", [])
        validated.append((resolved, raw_imports))

    if errors:
        return jsonify({"status": "validation_error", "errors": errors}), 422

    # Phase 2: 批量写入
    write_errors = []
    for filepath, imports_list in validated:
        try:
            idxmgr.write_imports_to_file(filepath, imports_list, doc_manager)
        except Exception as e:
            write_errors.append(f"{os.path.basename(os.path.dirname(filepath))}: {e}")

    idxmgr.invalidate_cache()

    if write_errors:
        return jsonify({"status": "partial", "errors": write_errors,
                        "success_count": len(validated) - len(write_errors)}), 207

    return jsonify({"status": "ok", "count": len(validated)})


@app.route("/api/index/verify", methods=["GET"])
def verify_index_integrity():
    """扫描所有文档的 imports，检查断裂引用（引用了不存在的文档）。"""
    try:
        data_root = os.path.join(_project_root(), "data")
        overview = idxmgr.build_overview(data_root, doc_manager)
    except Exception as e:
        return _json_error(str(e), 500)

    broken_refs = []
    total_imports = 0

    for cat in overview.get("categories", []):
        for doc in cat.get("docs", []):
            doc_broken = []
            for imp in doc.get("imports", []):
                total_imports += 1
                imp_path = imp.get("path", "")
                if not imp_path or "/" not in imp_path:
                    continue
                imp_cat, imp_id = imp_path.split("/", 1)
                try:
                    doc_manager.read_document(imp_cat, imp_id)
                except DocumentNotFoundError:
                    doc_broken.append({
                        "import_path": imp_path,
                        "name": imp.get("name", imp_path),
                    })
            if doc_broken:
                broken_refs.append({
                    "doc_path": doc["path"],
                    "doc_name": doc.get("name", doc["path"]),
                    "broken_imports": doc_broken,
                })

    total_docs = sum(len(c.get("docs", [])) for c in overview.get("categories", []))

    return jsonify({
        "total_docs": total_docs,
        "total_imports": total_imports,
        "broken_refs": broken_refs,
    })


@app.route("/api/sessions/<session_id>/index/verify", methods=["GET"])
def verify_session_index(session_id: str):
    """验证会话白名单依赖树的完整性。

    根据会话的索引配置（白名单），检查已启用的实体是否完整包含其 imports 依赖。
    返回可补全的依赖（存在但未启用）和断裂的依赖（不存在）。
    """
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)

    try:
        config = session.overlay.get_index_config()
        data_root = os.path.join(_project_root(), "data")
        overview = idxmgr.build_overview(data_root, doc_manager)

        # Build enabled entity paths from config
        enabled_paths = set()
        all_entity_paths = set()
        for cat in overview.get("categories", []):
            for doc in cat.get("docs", []):
                all_entity_paths.add(doc["path"])

        if config.get("mode") == "all":
            # All entities enabled — same as global verify
            enabled_paths = all_entity_paths
        else:
            # Whitelist mode
            enabled_cats = config.get("enabled_categories", [])
            enabled_entities = config.get("enabled_entities", {})

            for cat in overview.get("categories", []):
                if cat["category"] in enabled_cats:
                    for doc in cat["docs"]:
                        enabled_paths.add(doc["path"])

            for cat_name, doc_ids in enabled_entities.items():
                for doc_id in doc_ids:
                    enabled_paths.add(f"{cat_name}/{doc_id}")

        # Build path -> doc info lookup
        path_to_doc = {}
        for cat in overview.get("categories", []):
            for doc in cat.get("docs", []):
                path_to_doc[doc["path"]] = doc

        # Verify each enabled entity's imports
        broken_refs = []
        total_imports = 0
        total_docs = len(enabled_paths)

        for doc_path in enabled_paths:
            doc = path_to_doc.get(doc_path)
            if not doc:
                continue
            doc_broken = []
            for imp in doc.get("imports", []):
                total_imports += 1
                imp_path = imp.get("path", "")
                if not imp_path or "/" not in imp_path:
                    continue
                if imp_path in enabled_paths:
                    continue  # dependency is already enabled
                # Check if it exists globally
                if imp_path in all_entity_paths:
                    doc_broken.append({
                        "import_path": imp_path,
                        "name": imp.get("name", imp_path),
                        "type": "missing",
                    })
                else:
                    doc_broken.append({
                        "import_path": imp_path,
                        "name": imp.get("name", imp_path),
                        "type": "broken",
                    })
            if doc_broken:
                broken_refs.append({
                    "doc_path": doc_path,
                    "doc_name": doc.get("name", doc_path),
                    "broken_imports": doc_broken,
                })

        return jsonify({
            "total_docs": total_docs,
            "total_imports": total_imports,
            "broken_refs": broken_refs,
            "mode": config.get("mode", "all"),
        })
    except Exception as e:
        logger.error("验证会话索引失败: %s", e)
        return _json_error(str(e), 500)
# 11. 会话覆盖（角色/物品/环境的会话级修改）
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
    """开始一场战斗。请求体: {encounter_id: str, characters: [str]}

    未提供角色列表时，使用场景中已加载的角色。
    会话中编辑过的角色属性（overrides）会自动应用到战斗数值。
    """
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)

    data = request.json or {}
    encounter_id = data.get("encounter_id", "初遇整合运动")
    character_names = data.get("characters", [])

    # Default to scene characters when none specified
    if not character_names:
        character_names = session.scene_manager.get_scene_characters()

    if not character_names:
        return _json_error("没有可用角色，请先加载角色到场景中", 400)

    # Build character_metas list with session overrides applied
    from pathlib import Path as _Path
    character_metas = []
    for name in character_names:
        char_path = _Path(_project_root) / "data" / "characters" / name / "index.md"
        if not char_path.exists():
            logger.warning("Character file not found: %s", char_path)
            continue
        try:
            with open(char_path, "r", encoding="utf-8") as f:
                doc = frontmatter.load(f)
            meta = dict(doc.metadata)
            content = doc.content or ""
            merged_meta, _merged_content = session.overlay.apply_character_overrides(
                name, meta, content
            )
            character_metas.append(merged_meta)
        except Exception as e:
            logger.error("Failed to load character %s: %s", name, e)
            continue

    if not character_metas:
        return _json_error("无法加载角色数据", 500)

    try:
        combat = CombatSession(session_id)
        state = combat.start(encounter_id, character_metas=character_metas)
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


@app.route("/api/sessions/<session_id>/combat/complete", methods=["POST"])
def combat_complete(session_id: str):
    """战斗结算：将战斗结果写入会话 overrides，然后清除战斗状态。"""
    session = session_manager.get_session(session_id)
    if not session:
        return _json_error("会话不存在", 404)

    data = request.json or {}
    import time

    result = {
        "timestamp": time.time(),
        "encounter_id": data.get("encounter_id", ""),
        "winner": data.get("winner", ""),
        "survivors": data.get("survivors", []),
        "rounds": data.get("rounds", 0),
        "character_stats": data.get("character_stats", {}),
    }

    overlay_data = session.overlay._data
    if "combat_history" not in overlay_data:
        overlay_data["combat_history"] = []
    overlay_data["combat_history"].append(result)

    # Keep only last 20 entries
    if len(overlay_data["combat_history"]) > 20:
        overlay_data["combat_history"] = overlay_data["combat_history"][-20:]

    session.overlay._save()

    # Clear combat from session
    session.combat = None

    logger.info("会话 %s: 战斗结果已记录 (winner=%s, rounds=%d)",
                 session_id, data.get("winner"), data.get("rounds", 0))
    return jsonify({"message": "战斗结果已记录", "result": result})


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
# 12.  Combat Test — 无会话战斗测试
# ══════════════════════════════════════════════════════

_test_combats: dict[str, "CombatSession"] = {}


def _load_combat_test_plot() -> dict:
    """Load the combat test plot config from data/plots/combat-test/index.md."""
    from pathlib import Path
    plot_path = Path(_project_root) / "data" / "plots" / "combat-test" / "index.md"
    if not plot_path.exists():
        raise ValueError("战斗测试配置文件不存在: data/plots/combat-test/index.md")
    with open(plot_path, "r", encoding="utf-8") as f:
        return dict(frontmatter.load(f).metadata)


@app.route("/api/combat/test/start", methods=["POST"])
def combat_test_start():
    """Start a test combat session (no session required).
    Reads config from data/plots/combat-test/index.md."""
    try:
        config = _load_combat_test_plot()
    except ValueError as e:
        return _json_error(str(e), 404)

    data = request.json or {}
    encounter_id = data.get("encounter_id", config.get("default_encounter", "初遇整合运动"))
    character_names = data.get("characters", config.get("characters", ["阿米娅", "博士", "银灰", "霜星"]))

    # Randomly pick enemies from pool
    enemy_pool = config.get("enemy_pool", [])
    count_cfg = config.get("enemy_count", {})
    min_enemies = count_cfg.get("min", 2)
    max_enemies = count_cfg.get("max", 4)
    enemy_count = random.randint(min_enemies, max(min_enemies, max_enemies))

    if enemy_pool:
        picked = random.sample(enemy_pool, min(enemy_count, len(enemy_pool)))
    else:
        picked = ["整合运动士兵", "整合运动术师"]

    enemies_override = []
    for name in picked:
        enemies_override.append({"name": name, "count": 1, "positions": []})

    test_id = uuid.uuid4().hex[:12]
    try:
        combat = CombatSession(test_id)
        state = combat.start(encounter_id, character_names=character_names,
                            enemies_override=enemies_override)
        _test_combats[test_id] = combat
        return jsonify({"test_id": test_id, "state": state})
    except Exception as e:
        logger.exception("Failed to start test combat")
        return _json_error(f"战斗测试启动失败: {e}", 500)


@app.route("/api/combat/test/<test_id>/state", methods=["GET"])
def combat_test_state(test_id: str):
    """Get test combat state."""
    combat = _test_combats.get(test_id)
    if not combat:
        return _json_error("测试战斗不存在或已过期", 404)
    return jsonify(combat.get_state())


@app.route("/api/combat/test/<test_id>/action", methods=["POST"])
def combat_test_action(test_id: str):
    """Submit player action for test combat."""
    combat = _test_combats.get(test_id)
    if not combat:
        return _json_error("测试战斗不存在或已过期", 404)

    data = request.json or {}
    result = combat.handle_action(data)

    if not result.get("ok"):
        return _json_error(result.get("error", "操作失败"), 400)

    return jsonify(result.get("state", {}))


@app.route("/api/combat/test/<test_id>/end-turn", methods=["POST"])
def combat_test_end_turn(test_id: str):
    """Manually end current turn in test combat."""
    combat = _test_combats.get(test_id)
    if not combat:
        return _json_error("测试战斗不存在或已过期", 404)

    result = combat.end_turn()

    if not result.get("ok"):
        return _json_error(result.get("error", "操作失败"), 400)

    return jsonify(result.get("state", {}))


@app.route("/api/combat/test/<test_id>/events")
def combat_test_events(test_id: str):
    """SSE endpoint for test combat events."""
    combat = _test_combats.get(test_id)
    if not combat:
        def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'Test combat not found'}})}\n\n"
        return Response(error_stream(), mimetype="text/event-stream")

    def generate():
        stream_id = f"test_{uuid.uuid4().hex[:8]}"
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
