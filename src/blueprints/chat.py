"""
Chat blueprint — 对话 / 叙述 API (聊天、群聊、SSE 流式叙述、叙述变体)。
"""

import json
import uuid
import logging

from flask import Blueprint, jsonify, request, Response, stream_with_context

from shared.helpers import json_error, make_sse_response, inject_memory_context

logger = logging.getLogger(__name__)


# ── 辅助函数 ──

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


def _build_choices(session, llm_backend, narrative):
    """根据配置生成选项：LLM 自动生成或内置默认。"""
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
                response_text = response.get("content", "") if isinstance(response, dict) else str(response)
                lines = [l.strip() for l in response_text.strip().split("\n") if l.strip()]
                lines = [l for l in lines if len(l) <= 30 and not l.startswith("#")]
                if lines:
                    llm_choices = lines[:count]
            except Exception:
                pass

    options = ["继续推进剧情"]
    options.extend(llm_choices)
    if len(options) == 1:
        active = session.scene_manager.active
        if active:
            options.append(f"对{active}说话")
    return options


# ── Blueprint 注册 ──

def register(app, managers):
    bp = Blueprint("chat", __name__)
    session_mgr = managers["session"]
    llm_backend = managers["llm_backend"]

    # ── 1. 单角色聊天 ──

    @bp.route("/api/sessions/<session_id>/chat", methods=["POST"])
    def session_chat(session_id):
        """剧情模式：对当前活跃角色说话。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        err = _require_usable(session)
        if err:
            return err

        data = request.json or {}
        user_input = data.get("input", "").strip()
        if not user_input:
            return json_error("需要 input 参数")

        player_info = {"identity": data.get("identity", "博士")}
        env_context = session.environment.build_context()

        try:
            response, env_updates, usage = session.scene_manager.chat(
                user_input, player_info, env_context
            )
            session.accumulate_usage(usage)
            session.environment.apply_update(env_updates)
            result = {
                "response": response,
                "character": session.scene_manager.active,
                "env_updates": env_updates,
            }
            if usage:
                result["usage"] = usage
            return jsonify(result)
        except Exception as e:
            logger.error("对话出错: %s", e)
            return json_error(f"对话处理失败: {e!s}", 500)

    # ── 2. 群聊 ──

    @bp.route("/api/sessions/<session_id>/group-chat", methods=["POST"])
    def session_group_chat(session_id):
        """群聊模式：发送消息给场景中所有角色。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        err = _require_usable(session)
        if err:
            return err

        data = request.json or {}
        user_input = data.get("input", "").strip()
        if not user_input:
            return json_error("需要 input 参数")

        player_info = {"identity": data.get("identity", "博士")}
        env_context = session.environment.build_context()

        try:
            results, total_usage = session.scene_manager.group_chat(
                user_input, player_info, env_context
            )
            session.accumulate_usage(total_usage)
            for r in results:
                session.environment.apply_update(r.get("env_updates", {}))
            resp = {"responses": results}
            if total_usage:
                resp["total_usage"] = total_usage
            return jsonify(resp)
        except Exception as e:
            logger.error("群聊出错: %s", e)
            return json_error(f"群聊处理失败: {e!s}", 500)

    # ── 3. SSE 流式叙述 ──

    @bp.route("/api/sessions/<session_id>/narrate", methods=["GET"])
    def session_narrate(session_id):
        """剧情推进叙述（SSE 流式）。

        返回结构化 SSE 事件：
          data: {"type": "text", "data": {"token": "..."}}
          data: {"type": "scene_event", "data": {"event": "...", ...}}
          data: {"type": "choice", "data": {"options": [...]}}
          data: {"type": "done", "data": {"stream_id": "..."}}
        """
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        err = _require_usable(session)
        if err:
            return err

        stream_id = f"narr_{uuid.uuid4().hex[:12]}"
        player_info = {"identity": request.args.get("identity", "博士")}
        user_action = request.args.get("action", "").strip()
        env_context = session.environment.build_context()

        def generate():
            yield f"data: {json.dumps({'type': 'meta', 'data': {'stream_id': stream_id}})}\n\n"

            try:
                config = llm_backend.get_config()
                bubble_mode = config.get("dialogue_bubble_mode", False)

                # 注入记忆上下文
                context_with_memory = inject_memory_context(session, env_context)

                # — 叙述生成 —
                # 非气泡模式：使用真正的 LLM token 流式，首字可见延迟极低
                # 气泡模式：使用非流式（LLM 输出 JSON，不能逐 token 显示）
                dialogue_segments = None
                if not bubble_mode:
                    # True streaming: yield tokens as they arrive from LLM
                    for event_type, data in session.scene_manager.narrate_stream(
                        player_info, context_with_memory,
                        user_action=user_action, structured=False
                    ):
                        if event_type == "token":
                            yield f"data: {json.dumps({'type': 'text', 'data': {'token': data, 'stream_id': stream_id}})}\n\n"
                        elif event_type == "done":
                            narrative, env_updates, usage = data
                            session.accumulate_usage(usage)
                            break

                    # 检测结构化 JSON（LLM 即使非 structured 模式也可能输出 JSON）
                    if narrative.strip().startswith(("[", "```")):
                        dialogue_segments, stream_text = session.scene_manager.parse_structured(narrative)
                        if stream_text:
                            narrative = stream_text
                else:
                    # Bubble mode: non-streaming (LLM outputs JSON, cannot stream raw JSON to UI)
                    narrative, env_updates, usage = session.scene_manager.narrate(
                        player_info, context_with_memory,
                        user_action=user_action, structured=True
                    )
                    session.accumulate_usage(usage)

                    if narrative.strip().startswith(("[", "```")):
                        dialogue_segments, stream_text = session.scene_manager.parse_structured(narrative)
                        if stream_text:
                            narrative = stream_text

                    # 逐字符发送解析后的纯文本
                    for ch in narrative:
                        yield f"data: {json.dumps({'type': 'text', 'data': {'token': ch, 'stream_id': stream_id}})}\n\n"

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

                # 对话气泡模式：发送结构化片段
                if dialogue_segments:
                    yield f"data: {json.dumps({'type': 'dialogue_segments', 'data': {'segments': dialogue_segments, 'stream_id': stream_id}})}\n\n"

                # 回忆系统：在文本输出后生成回忆（用户已在阅读，不再阻塞首字可见）
                if session.mode == "story":
                    session.add_narration(narrative, user_action)
                    interval = config.get("memory_interval", 5)
                    if session.should_generate_memory(interval):
                        memory = session.generate_memory()
                        if memory:
                            yield f"data: {json.dumps({'type': 'memory_event', 'data': {
                                'memory': memory,
                                'stream_id': stream_id
                            }})}\n\n"

                # 生成选项
                options = _build_choices(session, llm_backend, narrative)

                yield f"data: {json.dumps({'type': 'choice', 'data': {'options': options, 'stream_id': stream_id}})}\n\n"

                # 发送 token 使用量
                if usage:
                    yield f"data: {json.dumps({'type': 'token_usage', 'data': {'usage': usage, 'stream_id': stream_id}})}\n\n"

            except Exception as e:
                logger.error("叙述出错: %s", e)
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e), 'stream_id': stream_id}})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'data': {'stream_id': stream_id}})}\n\n"

        return make_sse_response(generate)

    # ── 4. 非流式叙述回退 ──

    @bp.route("/api/sessions/<session_id>/narrate-continue", methods=["POST"])
    def session_narrate_continue(session_id):
        """非流式叙述（前端不使用 SSE 时的回退）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        err = _require_usable(session)
        if err:
            return err

        data = request.json or {}
        player_info = {"identity": data.get("identity", "博士")}
        env_context = session.environment.build_context()

        # 注入记忆上下文
        context_with_memory = inject_memory_context(session, env_context)

        try:
            config = llm_backend.get_config()
            bubble_mode = config.get("dialogue_bubble_mode", False)

            narrative, env_updates, usage = session.scene_manager.narrate(
                player_info, context_with_memory,
                user_action=data.get("action", ""),
                structured=bubble_mode,
            )
            session.accumulate_usage(usage)
            session.environment.apply_update(env_updates)

            # 检测并解析结构化 JSON 输出
            dialogue_segments = None
            if narrative.strip().startswith(("[", "```")):
                dialogue_segments, stream_text = session.scene_manager.parse_structured(narrative)
                if stream_text:
                    narrative = stream_text

            # 回忆系统
            response_extra = {}
            if session.mode == "story":
                session.add_narration(narrative, data.get("action", ""))
                interval = config.get("memory_interval", 5)
                if session.should_generate_memory(interval):
                    memory = session.generate_memory()
                    if memory:
                        response_extra["memory"] = memory

            options = _build_choices(session, llm_backend, narrative)

            if dialogue_segments:
                response_extra["dialogue_segments"] = dialogue_segments

            if usage:
                response_extra["usage"] = usage

            return jsonify({
                "narrative": narrative,
                "env_updates": env_updates,
                "choices": options,
                **response_extra,
            })
        except Exception as e:
            logger.error("叙述出错: %s", e)
            return json_error(f"叙述失败: {e!s}", 500)

    # ── 5. 叙述变体生成 ──

    @bp.route("/api/sessions/<session_id>/narrate-variant", methods=["POST"])
    def session_narrate_variant(session_id):
        """生成叙述变体（不记录到历史，由前端管理变体列表）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        err = _require_usable(session)
        if err:
            return err

        data = request.json or {}
        player_info = {"identity": data.get("identity", "博士")}
        prompt = data.get("prompt", "").strip()
        env_context = session.environment.build_context()

        # 注入记忆上下文
        context_with_memory = inject_memory_context(session, env_context)

        try:
            config = llm_backend.get_config()
            bubble_mode = config.get("dialogue_bubble_mode", False)

            narrative, env_updates, usage = session.scene_manager.narrate(
                player_info, context_with_memory,
                user_action=prompt,
                structured=bubble_mode,
            )
            session.accumulate_usage(usage)
            response = {"narrative": narrative}
            if usage:
                response["usage"] = usage

            if narrative.strip().startswith(("[", "```")):
                segments, plain = session.scene_manager.parse_structured(narrative)
                if segments:
                    response["dialogue_segments"] = segments
                    if plain:
                        response["narrative"] = plain

            return jsonify(response)
        except Exception as e:
            logger.error("生成叙述变体出错: %s", e)
            return json_error(f"生成失败: {e!s}", 500)

    # ── 6. 更新最新叙述 ──

    @bp.route("/api/sessions/<session_id>/narrate-update", methods=["POST"])
    def session_narrate_update(session_id):
        """更新最新一轮的叙述文本（前端切换变体时同步）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        data = request.json or {}
        text = data.get("text", "")
        session.update_narration(text)
        return jsonify({"ok": True})

    app.register_blueprint(bp)
