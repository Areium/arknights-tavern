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
import logging
from typing import Optional

import yaml
from flask import Flask, jsonify, request, Response, stream_with_context
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
    """获取会话，不存在则返回 404。"""
    session = session_manager.get_session(session_id)
    if not session:
        return None
    if not session.is_usable:
        return None
    return session


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
    """创建新会话。"""
    data = request.json or {}
    mode = data.get("mode", "free")
    if mode not in ("free", "story"):
        return _json_error("mode 必须是 'free' 或 'story'")
    session = session_manager.create_session(
        name=data.get("name", ""),
        mode=mode,
    )
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


# ══════════════════════════════════════════════════════
# 3.  场景角色管理
# ══════════════════════════════════════════════════════


@app.route("/api/sessions/<session_id>/characters", methods=["GET"])
def list_scene_characters(session_id: str):
    """获取当前场景中的角色列表。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不可用", 404)
    return jsonify({
        "characters": session.scene_manager.get_scene_characters(),
        "active": session.scene_manager.active,
    })


@app.route("/api/sessions/<session_id>/characters/load", methods=["POST"])
def load_scene_character(session_id: str):
    """加载角色到场景。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不可用", 404)
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
        return _json_error("会话不可用", 404)
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
        return _json_error("会话不可用", 404)
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
        return _json_error("会话不可用", 404)
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
        return _json_error("会话不可用", 404)
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
        return _json_error("会话不可用", 404)

    stream_id = f"narr_{uuid.uuid4().hex[:12]}"
    player_info = {"identity": request.args.get("identity", "博士")}
    env_context = session.environment.build_context()

    def generate():
        yield f"data: {json.dumps({'type': 'meta', 'data': {'stream_id': stream_id}})}\n\n"

        try:
            narrative, env_updates = session.scene_manager.narrate(
                player_info, env_context
            )
            session.environment.apply_update(env_updates)

            # 流式输出叙述文本
            for ch in narrative:
                yield f"data: {json.dumps({'type': 'text', 'data': {'token': ch, 'stream_id': stream_id}})}\n\n"

            # 生成选项
            options = ["继续推进剧情"]
            active = session.scene_manager.active
            if active:
                options.append(f"对{active}说话")
            options.append("自行输入...")

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
        return _json_error("会话不可用", 404)
    data = request.json or {}
    player_info = {"identity": data.get("identity", "博士")}
    env_context = session.environment.build_context()

    try:
        narrative, env_updates = session.scene_manager.narrate(
            player_info, env_context,
            user_action=data.get("action", ""),
        )
        session.environment.apply_update(env_updates)
        return jsonify({
            "narrative": narrative,
            "env_updates": env_updates,
        })
    except Exception as e:
        logger.error("叙述出错: %s", e)
        return _json_error(f"叙述失败: {e!s}", 500)


# ══════════════════════════════════════════════════════
# 5.  环境控制
# ══════════════════════════════════════════════════════


@app.route("/api/sessions/<session_id>/environment", methods=["GET"])
def get_environment(session_id: str):
    """获取当前环境状态。"""
    session = _get_session(session_id)
    if not session:
        return _json_error("会话不可用", 404)
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
# 启动入口
# ══════════════════════════════════════════════════════

def main():
    """启动 API 服务。"""
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "true").lower() == "true"

    status = llm_backend.get_status()
    print(f"\n  API 服务启动: http://{host}:{port}")
    print(f"  LLM 后端: {status['primary']['name'] if status['primary'] else '无'} / "
          f"备用: {status['fallback']['name'] if status['fallback'] else '无'}")
    print(f"  文档类别: {len(doc_manager.list_categories())} 个")
    print()

    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
