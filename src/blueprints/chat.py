"""
Chat blueprint — 对话 / 叙述 API (聊天、群聊、SSE 流式叙述、叙述变体)。
"""

import json
import re
import uuid
import logging

from flask import Blueprint, jsonify, request, Response, stream_with_context

from shared.helpers import json_error, make_sse_response, inject_memory_context, build_character_metas

logger = logging.getLogger(__name__)

# 模块级引用，由 register() 初始化
_doc_mgr = None


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


def _require_no_combat(session):
    """检查会话是否正在进行战斗，战斗中则返回 423。"""
    if session.combat is not None:
        return json_error("战斗进行中，无法执行对话操作。请先完成或退出战斗。", 423)
    return None


_COMBAT_MARKER_RE = re.compile(r'<combat:([^{\s/>]+)(?:\s+(\{.*?\}))?\s*/>', re.IGNORECASE)
_SAFE_COMBAT_MARKER_RE = re.compile(r'<combat:([^{\s/>]+)(?:\s+(\{.*?\}))?\s*/>', re.IGNORECASE)
_BEAT_COMPLETE_RE = re.compile(r'\n?\s*<beat_complete\s*/>\s*\n?')
_CHOICES_MARKER_RE = re.compile(r'\n?<choices\s*/>\n?([\s\S]*?)$')
_SUMMARY_MARKER_RE = re.compile(r'\n?<summary\s*/>\n?([\s\S]*?)$')


def _try_extract_structured(narrative: str, scene_manager):
    """尝试从叙述文本中提取结构化对话片段。

    比 parse_structured 的入口检查更宽松：即使 JSON 数组不是
    严格从文本开头开始，也会尝试查找和解析。

    Returns:
        (dialogue_segments, plain_text) 或 (None, narrative)
    """
    text = narrative.strip()

    # 优先使用标准入口（以 [ 或 ``` 开头）
    if text.startswith(("[", "```")):
        segments, plain = scene_manager.parse_structured(narrative)
        if segments:
            return segments, plain
        return None, narrative

    # 尝试从文本中定位 JSON 数组起始位置 [{ 并提取到匹配的 ]
    idx = text.find("[{")
    if idx == -1:
        idx = text.find("[\n{")
    if idx == -1:
        idx = text.find("[\r\n{")
    if idx >= 0:
        # 从 idx 开始查找匹配的 ]
        depth = 0
        end = -1
        for i in range(idx, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > 0:
            candidate = text[idx:end]
            segments, plain = scene_manager.parse_structured(candidate)
            if segments:
                return segments, plain

    return None, narrative


def _handle_choices_marker(narrative: str) -> tuple[str, list[str] | None]:
    """检测并提取 <choices/> 标记中的选项列表。

    Returns:
        (cleaned_narrative, choices_or_none): 清理后的叙述文本和选项列表
    """
    match = _CHOICES_MARKER_RE.search(narrative)
    if not match:
        return narrative, None
    cleaned = _CHOICES_MARKER_RE.sub("", narrative).strip()
    choices_text = match.group(1).strip()
    lines = [l.strip() for l in choices_text.split("\n") if l.strip()]
    lines = [l for l in lines if len(l) <= 30]
    return cleaned, (lines if lines else None)


def _handle_summary_marker(narrative: str) -> tuple[str, str | None]:
    """检测并提取 <summary/> 标记中的剧情摘要。

    Returns:
        (cleaned_narrative, summary_or_none): 清理后的叙述文本和摘要字符串
    """
    match = _SUMMARY_MARKER_RE.search(narrative)
    if not match:
        return narrative, None
    cleaned = _SUMMARY_MARKER_RE.sub("", narrative).strip()
    summary = match.group(1).strip()
    return cleaned, (summary if summary else None)


def _handle_combat_trigger(session, narrative, stream_id):
    """检测并处理战斗触发标记 <combat:encounter_id/>。

    支持扩展格式：
        <combat:encounter_id/>
        <combat:encounter_id {"status_effects": {...}}/>

    Returns:
        (cleaned_narrative, sse_event_or_none): 清理后的叙述文本和可选的 SSE 事件字符串
    """
    match = _COMBAT_MARKER_RE.search(narrative)
    if not match:
        return narrative, None

    encounter_id = match.group(1).strip()
    cleaned = _COMBAT_MARKER_RE.sub("", narrative).strip()

    combat_mode = getattr(session, 'combat_mode', 'narrative')
    if combat_mode != "tactical":
        return cleaned, None

    # 尝试解析可选的 JSON 参数
    combat_params = None
    if match.group(2):
        try:
            combat_params = json.loads(match.group(2))
        except json.JSONDecodeError:
            logger.warning("会话 %s: 战斗触发 JSON 解析失败，忽略参数: %s",
                          session.id, match.group(2)[:100])

    try:
        character_metas = build_character_metas(session, _doc_mgr) if _doc_mgr else None
        combat = session.start_combat(encounter_id,
                                       character_metas=character_metas,
                                       combat_params=combat_params)
        logger.info("会话 %s: LLM 触发战斗 %s (params=%s)",
                     session.id, encounter_id,
                     "yes" if combat_params else "no")
        event = f"data: {json.dumps({'type': 'combat_trigger', 'data': {'encounter_id': encounter_id, 'session_id': session.id, 'stream_id': stream_id}})}\n\n"
        return cleaned, event
    except Exception as e:
        logger.error("自动触发战斗失败: %s", e)
        return cleaned, None


def _handle_beat_complete(session, narrative):
    """检测并处理节拍完成标记 <beat_complete/>。

    Returns:
        str: 清理后的叙述文本（移除 [BEAT_COMPLETE] 标记）
    """
    if not _BEAT_COMPLETE_RE.search(narrative):
        return narrative

    cleaned = _BEAT_COMPLETE_RE.sub("", narrative).strip()
    overlay = session.overlay
    if overlay and overlay.get_beat_state():
        overlay.advance_beat()
        current = overlay.get_current_beat()
        beat_name = current["id"] if current else "剧情终点"
        logger.info("会话 %s: LLM 标记节拍完成 → %s", session.id, beat_name)
    return cleaned


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
                    {"role": "system", "content": (
                        "<role>你是明日方舟文字冒险游戏的选项生成器。</role>\n"
                        "<core_rules>\n"
                        "- MUST：根据当前剧情生成合理且多样化的后续行动选项\n"
                        "- MUST：每个选项≤15字，表达简洁直接\n"
                        "</core_rules>"
                    )},
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
    global _doc_mgr
    bp = Blueprint("chat", __name__)
    session_mgr = managers["session"]
    llm_backend = managers["llm_backend"]
    _doc_mgr = managers["document"]

    # ── 1. 单角色聊天 ──

    @bp.route("/api/sessions/<session_id>/chat", methods=["POST"])
    def session_chat(session_id):
        """剧情模式：对当前活跃角色说话。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        err = _require_usable(session) or _require_no_combat(session)
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
        err = _require_usable(session) or _require_no_combat(session)
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
        err = _require_usable(session) or _require_no_combat(session)
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
                auto_choices = config.get("auto_generate_choices", False)
                choice_count = config.get("choice_count", 3)
                choices_count = choice_count if auto_choices else 0
                max_tokens = config.get("max_output_tokens", 16384)
                word_limit = config.get("word_limit", 500)

                # 构建对话历史（滑动窗口，最近 ~3000 字符）
                conversation_history = session.scene_manager._build_conversation_history(
                    session._narration_history, structured=bubble_mode
                )
                is_first_turn = session.narration_count == 0

                # 注入记忆上下文
                context_with_memory = inject_memory_context(session, env_context)

                # — 叙述生成 —
                dialogue_segments = None
                inline_choices = None
                plot_summary = None
                if not bubble_mode and choices_count == 0:
                    # True streaming: yield tokens as they arrive from LLM
                    for event_type, data in session.scene_manager.narrate_stream(
                        player_info, context_with_memory,
                        user_action=user_action, structured=False,
                        max_tokens=max_tokens,
                        word_limit=word_limit,
                        conversation_history=conversation_history,
                        is_first_turn=is_first_turn,
                    ):
                        if event_type == "token":
                            yield f"data: {json.dumps({'type': 'text', 'data': {'token': data, 'stream_id': stream_id}})}\n\n"
                        elif event_type == "reasoning":
                            yield f"data: {json.dumps({'type': 'reasoning', 'data': {'token': data, 'stream_id': stream_id}})}\n\n"
                        elif event_type == "done":
                            narrative, env_updates, usage = data
                            session.accumulate_usage(usage)
                            break

                    # 检测结构化 JSON（LLM 即使非 structured 模式也可能输出 JSON）
                    dialogue_segments, stream_text = _try_extract_structured(
                        narrative, session.scene_manager
                    )
                    if stream_text:
                        narrative = stream_text

                    # 检测战斗触发标记 <combat:encounter_id/>
                    narrative, combat_triggered = _handle_combat_trigger(
                        session, narrative, stream_id
                    )
                    if combat_triggered:
                        yield combat_triggered

                    # 检测节拍完成标记 <beat_complete/>
                    narrative = _handle_beat_complete(session, narrative)

                elif not bubble_mode and choices_count > 0:
                    # 全缓冲模式（需提取 <choices/>）：
                    # LLM 非流式获取完整响应，解析标记后逐字符推送纯叙述
                    for _event_type, _data in session.scene_manager.narrate_stream(
                        player_info, context_with_memory,
                        user_action=user_action, structured=False,
                        max_tokens=max_tokens, word_limit=word_limit, choices_count=choices_count,
                        conversation_history=conversation_history,
                        is_first_turn=is_first_turn,
                    ):
                        if _event_type == "done":
                            narrative, env_updates, usage = _data
                            session.accumulate_usage(usage)
                            break

                    # 提取摘要和内联选项（SUMMARY 在末尾，先提取）
                    narrative, plot_summary = _handle_summary_marker(narrative)
                    narrative, inline_choices = _handle_choices_marker(narrative)

                    # 检测结构化 JSON
                    dialogue_segments, stream_text = _try_extract_structured(
                        narrative, session.scene_manager
                    )
                    if stream_text:
                        narrative = stream_text

                    # 检测战斗触发和节拍完成
                    narrative, combat_triggered = _handle_combat_trigger(
                        session, narrative, stream_id
                    )
                    if combat_triggered:
                        yield combat_triggered
                    narrative = _handle_beat_complete(session, narrative)

                    # 逐字符发送解析后的纯文本
                    for ch in narrative:
                        yield f"data: {json.dumps({'type': 'text', 'data': {'token': ch, 'stream_id': stream_id}})}\n\n"

                else:
                    # Bubble mode: non-streaming (LLM outputs JSON, cannot stream raw JSON to UI)
                    narrative, env_updates, usage = session.scene_manager.narrate(
                        player_info, context_with_memory,
                        user_action=user_action, structured=True,
                        max_tokens=max_tokens, word_limit=word_limit, choices_count=choices_count,
                        conversation_history=conversation_history,
                        is_first_turn=is_first_turn,
                    )
                    session.accumulate_usage(usage)

                    # 提取摘要和内联选项
                    narrative, plot_summary = _handle_summary_marker(narrative)
                    if choices_count > 0:
                        narrative, inline_choices = _handle_choices_marker(narrative)

                    dialogue_segments, stream_text = _try_extract_structured(
                        narrative, session.scene_manager
                    )
                    if stream_text:
                        narrative = stream_text

                    # 检测战斗触发标记 <combat:encounter_id/>（先剥离再发送字符）
                    narrative, combat_triggered = _handle_combat_trigger(
                        session, narrative, stream_id
                    )
                    if combat_triggered:
                        yield combat_triggered

                    # 检测节拍完成标记 <beat_complete/>
                    narrative = _handle_beat_complete(session, narrative)

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
                    session.add_narration(narrative, user_action, dialogue_segments)
                    session.overlay.append_plot_log(
                        plot_summary if plot_summary else narrative[:300].replace('\n', ' ')
                    )
                    session.overlay.update_beat_progress()
                    interval = config.get("memory_interval", 5)
                    if session.should_generate_memory(interval):
                        memory = session.generate_memory()
                        if memory:
                            yield f"data: {json.dumps({'type': 'memory_event', 'data': {
                                'memory': memory,
                                'stream_id': stream_id
                            }})}\n\n"

                # 生成选项：优先使用内联选项，回退到 LLM 生成
                if inline_choices:
                    options = ["继续推进剧情"] + inline_choices
                else:
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
        err = _require_usable(session) or _require_no_combat(session)
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
            auto_choices = config.get("auto_generate_choices", False)
            choices_count = config.get("choice_count", 3) if auto_choices else 0
            max_tokens = config.get("max_output_tokens", 16384)
            word_limit = config.get("word_limit", 500)

            conversation_history = session.scene_manager._build_conversation_history(
                session._narration_history, structured=bubble_mode
            )
            is_first_turn = session.narration_count == 0

            narrative, env_updates, usage = session.scene_manager.narrate(
                player_info, context_with_memory,
                user_action=data.get("action", ""),
                structured=bubble_mode,
                max_tokens=max_tokens,
                word_limit=word_limit,
                choices_count=choices_count,
                conversation_history=conversation_history,
                is_first_turn=is_first_turn,
            )
            session.accumulate_usage(usage)
            session.environment.apply_update(env_updates)

            # 提取摘要和内联选项（SUMMARY 在末尾，先提取）
            narrative, plot_summary = _handle_summary_marker(narrative)
            inline_choices = None
            if choices_count > 0:
                narrative, inline_choices = _handle_choices_marker(narrative)

            # 检测并解析结构化 JSON 输出
            dialogue_segments = None
            dialogue_segments, stream_text = _try_extract_structured(
                narrative, session.scene_manager
            )
            if stream_text:
                narrative = stream_text

            # 检测战斗触发和节拍完成
            narrative, _ = _handle_combat_trigger(session, narrative, "")
            combat_triggered = session.combat is not None
            narrative = _handle_beat_complete(session, narrative)

            # 回忆系统
            response_extra = {}
            if session.mode == "story":
                session.add_narration(narrative, data.get("action", ""), dialogue_segments)
                session.overlay.append_plot_log(
                    plot_summary if plot_summary else narrative[:300].replace('\n', ' ')
                )
                session.overlay.update_beat_progress()
                interval = config.get("memory_interval", 5)
                if session.should_generate_memory(interval):
                    memory = session.generate_memory()
                    if memory:
                        response_extra["memory"] = memory

            if inline_choices:
                options = ["继续推进剧情"] + inline_choices
            else:
                options = _build_choices(session, llm_backend, narrative)

            if dialogue_segments:
                response_extra["dialogue_segments"] = dialogue_segments

            if usage:
                response_extra["usage"] = usage

            if combat_triggered:
                response_extra["combat_triggered"] = True
                response_extra["encounter_id"] = session.combat._encounter_id if session.combat else ""

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
        err = _require_usable(session) or _require_no_combat(session)
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
            max_tokens = config.get("max_output_tokens", 16384)
            word_limit = config.get("word_limit", 500)

            conversation_history = session.scene_manager._build_conversation_history(
                session._narration_history
            )
            is_first_turn = session.narration_count == 0

            narrative, env_updates, usage = session.scene_manager.narrate(
                player_info, context_with_memory,
                user_action=prompt,
                structured=bubble_mode,
                conversation_history=conversation_history,
                is_first_turn=is_first_turn,
                max_tokens=max_tokens,
                word_limit=word_limit,
            )
            session.accumulate_usage(usage)
            response = {"narrative": narrative}
            if usage:
                response["usage"] = usage

            segments, plain = _try_extract_structured(narrative, session.scene_manager)
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
