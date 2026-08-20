"""
Chat blueprint — 对话 / 叙述 API (聊天、群聊、SSE 流式叙述、叙述变体)。
"""

import json
import uuid
import logging

from flask import Blueprint, jsonify, request, Response, stream_with_context

from shared.helpers import json_error, make_sse_response, inject_memory_context
from hooks.base import HookContext

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


def _should_extract_markers(session, choices_count: int) -> bool:
    """判断是否需要标记提取 Call 2。

    当无选项、无战术模式、无节拍状态时跳过，避免无意义的 LLM 往返。
    """
    if choices_count > 0:
        return True
    if getattr(session.scene_manager, '_combat_mode', 'narrative') == "tactical":
        return True
    overlay = session.overlay
    if overlay and overlay.get_beat_state():
        return True
    return False


def _beat_combat_target(session) -> str:
    """确定性战斗目标：当前节拍声明的 `[COMBAT:enc_id]`（推进节拍前读取）。"""
    overlay = getattr(session, "overlay", None)
    if overlay is None:
        return ""
    return overlay.get_current_beat_combat_id()


def _apply_combat_briefing(session, combat_data: dict | None, stream_id: str,
                           beat_combat_id: str = "") -> dict | None:
    """从标记提取结果生成战前简报（含打法列表），不再自动开战。

    玩家在简报面板选择打法后，由前端 POST /combat/start 启动战斗（见
    docs/combat-core-design.md C1）。战斗目标优先级：节拍 `[COMBAT:enc_id]`
    （代码确定性解析）> LLM `combat_trigger` 提取。返回 briefing dict 或 None。
    """
    if getattr(session, 'combat_mode', 'narrative') != "tactical":
        return None
    encounter_id = beat_combat_id or (combat_data or {}).get("encounter_id", "")
    if not encounter_id:
        return None
    try:
        from combat_data_loader import CombatDataLoader
        from combat_approaches import list_approaches
        encounter = CombatDataLoader().load_encounter(encounter_id) or {}
        briefing = {
            "encounter_id": encounter_id,
            "session_id": session.id,
            "stream_id": stream_id,
            "name": encounter.get("name", encounter_id),
            "approaches": list_approaches(encounter),
        }
        logger.info("会话 %s: 标记提取触发战前简报 %s", session.id, encounter_id)
        return briefing
    except Exception as e:
        logger.error("生成战前简报失败: %s", e)
        return None


def _apply_beat_complete(session, beat_complete: bool):
    """从标记提取结果推进节拍。"""
    if not beat_complete:
        return
    overlay = session.overlay
    if overlay and overlay.get_beat_state():
        overlay.advance_beat()
        current = overlay.get_current_beat()
        beat_name = current["id"] if current else "剧情终点"
        logger.info("会话 %s: 标记提取推进节拍 -> %s", session.id, beat_name)


def _build_choices(session, inline_choices: list[str] | None) -> list[str]:
    """格式化最终选项列表，优先使用提取结果，回退到默认选项。"""
    if inline_choices:
        return ["继续推进剧情"] + inline_choices

    # Fallback
    options = ["继续推进剧情"]
    active = session.scene_manager.active
    if active:
        options.append(f"与{active}交谈")
    options.append("观察周围环境")
    return options


# ── Blueprint 注册 ──

def register(app, managers):
    global _doc_mgr
    bp = Blueprint("chat", __name__)
    session_mgr = managers["session"]
    llm_backend = managers["llm_backend"]
    _doc_mgr = managers["document"]
    hook_pipeline = managers.get("hook_pipeline")

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

        def _run_intra_round_hooks(hook_ctx, narrative):
            """Phase 1 和 Phase 2 之间的 hook 执行。

            Returns:
                (events_list, modified_narrative_or_None)
            """
            if not hook_pipeline:
                return [], None
            hook_ctx.narrative_text = narrative
            events = hook_pipeline.execute_between_phases(hook_ctx)
            injection = hook_pipeline.collect_prompt_injections(hook_ctx)
            modified = (injection + "\n\n" + narrative) if injection else None
            return events, modified

        def generate():
            yield f"data: {json.dumps({'type': 'meta', 'data': {'stream_id': stream_id}})}\n\n"

            # ── Hook: inter-round（两轮叙述之间）──
            hook_ctx = HookContext(
                session=session,
                player_info=player_info,
                user_action=user_action,
                env_context=env_context,
                stream_id=stream_id,
            )
            hook_injection_text = ""
            if hook_pipeline:
                try:
                    for event in hook_pipeline.execute_before_narration(hook_ctx):
                        yield f"data: {json.dumps(event)}\n\n"
                    injection = hook_pipeline.collect_prompt_injections(hook_ctx)
                    if injection:
                        hook_injection_text = injection
                except Exception:
                    logger.warning("Hook inter-round 执行异常", exc_info=True)

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
                if hook_injection_text:
                    context_with_memory = context_with_memory + "\n\n" + hook_injection_text

                # — 统一流式叙述生成（所有模式：纯文本 / 气泡 / 选项）—
                # 叙述文本先流式显示：首字延迟 ≈ LLM 首个 token（TTFT），不再等完整响应。
                # 气泡模式由前端实时解析「」对话流动态渲染为气泡（等生成完再整体呈现）。
                # 选项/战斗/节拍标记在文本流完后提取（Call 2），与对话内容分开、不阻塞阅读。
                dialogue_segments = None
                inline_choices = None
                plot_summary = None
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
                        break

                session.accumulate_usage(usage)

                # 检测结构化 JSON（LLM 即使非 structured 模式也可能输出 JSON）
                dialogue_segments, stream_text = _try_extract_structured(
                    narrative, session.scene_manager
                )
                if stream_text:
                    narrative = stream_text

                # ── Hook: intra-round（Phase 1 → Phase 2）──
                intra_events, intra_narrative = _run_intra_round_hooks(hook_ctx, narrative)
                for evt in intra_events:
                    yield f"data: {json.dumps(evt)}\n\n"
                if intra_narrative:
                    narrative = intra_narrative

                # 两阶段提取：从叙事文本中提取标记（Call 2）
                # 文本已流式显示完毕，此阶段不阻塞用户阅读
                if _should_extract_markers(session, choices_count):
                    markers = session.scene_manager.extract_markers(
                        narrative, choices_count=choices_count,
                        beat_state_active=bool(session.overlay and session.overlay.get_beat_state()),
                    )
                    if markers.get("usage"):
                        session.accumulate_usage(markers["usage"])
                    # 节拍确定性战斗目标：推进节拍前读取当前节拍的 [COMBAT:enc_id]
                    beat_combat_id = _beat_combat_target(session)
                    combat_due = bool(markers.get("combat")) or bool(markers.get("beat_complete"))
                    _apply_beat_complete(session, markers.get("beat_complete", False))
                    briefing = _apply_combat_briefing(
                        session, markers.get("combat"), stream_id,
                        beat_combat_id=beat_combat_id if combat_due else "",
                    )
                    if briefing:
                        yield f"data: {json.dumps({'type': 'combat_briefing', 'data': briefing}, ensure_ascii=False)}\n\n"
                    inline_choices = markers.get("choices")
                    plot_summary = markers.get("summary")

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

                # 生成选项：优先使用提取结果，回退到默认选项
                options = _build_choices(session, inline_choices)

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
        user_action = data.get("action", "")

        # 注入记忆上下文
        context_with_memory = inject_memory_context(session, env_context)

        # ── Hook: inter-round ──
        roll_events = []
        hook_ctx = HookContext(
            session=session,
            player_info=player_info,
            user_action=user_action,
            env_context=context_with_memory,
            stream_id="",
        )
        if hook_pipeline:
            try:
                roll_events = hook_pipeline.execute_before_narration(hook_ctx)
                injection = hook_pipeline.collect_prompt_injections(hook_ctx)
                if injection:
                    context_with_memory = context_with_memory + "\n\n" + injection
            except Exception:
                logger.warning("Hook inter-round 执行异常", exc_info=True)

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
                user_action=user_action,
                structured=bubble_mode,
                max_tokens=max_tokens,
                word_limit=word_limit,
                conversation_history=conversation_history,
                is_first_turn=is_first_turn,
            )
            session.accumulate_usage(usage)
            session.environment.apply_update(env_updates)

            # 检测并解析结构化 JSON 输出
            dialogue_segments = None
            dialogue_segments, stream_text = _try_extract_structured(
                narrative, session.scene_manager
            )
            if stream_text:
                narrative = stream_text

            # ── Hook: intra-round ──
            if hook_pipeline:
                try:
                    hook_ctx.narrative_text = narrative
                    intra_events = hook_pipeline.execute_between_phases(hook_ctx)
                    roll_events.extend(intra_events)
                    injection = hook_pipeline.collect_prompt_injections(hook_ctx)
                    if injection:
                        narrative = injection + "\n\n" + narrative
                except Exception:
                    logger.warning("Hook intra-round 执行异常", exc_info=True)

            # 两阶段提取：从叙事文本中提取标记（Call 2）
            inline_choices = None
            plot_summary = None
            combat_briefing = None
            if _should_extract_markers(session, choices_count):
                markers = session.scene_manager.extract_markers(
                    narrative, choices_count=choices_count,
                    beat_state_active=bool(session.overlay and session.overlay.get_beat_state()),
                )
                if markers.get("usage"):
                    session.accumulate_usage(markers["usage"])
                # 节拍确定性战斗目标：推进节拍前读取当前节拍的 [COMBAT:enc_id]
                beat_combat_id = _beat_combat_target(session)
                combat_due = bool(markers.get("combat")) or bool(markers.get("beat_complete"))
                _apply_beat_complete(session, markers.get("beat_complete", False))
                combat_briefing = _apply_combat_briefing(
                    session, markers.get("combat"), "",
                    beat_combat_id=beat_combat_id if combat_due else "",
                )
                inline_choices = markers.get("choices")
                plot_summary = markers.get("summary")

            # 回忆系统
            response_extra = {}
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
                        response_extra["memory"] = memory

            options = _build_choices(session, inline_choices)

            if dialogue_segments:
                response_extra["dialogue_segments"] = dialogue_segments

            if usage:
                response_extra["usage"] = usage

            if combat_briefing:
                response_extra["combat_briefing"] = combat_briefing

            if roll_events:
                response_extra["roll_events"] = roll_events
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
