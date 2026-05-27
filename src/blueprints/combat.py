"""
Combat blueprint -- session combat, test combat, and combat-mode routes.
"""

import json
import uuid
import random
import time
import logging
import queue
from pathlib import Path

from flask import Blueprint, jsonify, request

from shared.helpers import json_error, make_sse_response, build_character_metas

logger = logging.getLogger(__name__)

# Project root for loading test combat config
_project_root = Path(__file__).resolve().parent.parent.parent


def _get_session(session_mgr, session_id):
    """Retrieve a session by id, or return None."""
    session = session_mgr.get_session(session_id)
    if not session:
        return None
    return session


def _load_combat_test_config() -> dict:
    """Load the combat test plot config from data/plots/combat-test/plot.md."""
    import frontmatter

    plot_path = _project_root / "data" / "plots" / "combat-test" / "index.md"
    if not plot_path.exists():
        raise ValueError("战斗测试配置文件不存在: data/plots/combat-test/plot.md")
    with open(plot_path, "r", encoding="utf-8") as f:
        return dict(frontmatter.load(f).metadata)


def _build_sse_generator(combat, stream_prefix="combat"):
    """Return a generator function for SSE combat event streams."""
    import uuid as _uuid
    import queue as _queue

    def generate():
        stream_id = f"{stream_prefix}_{_uuid.uuid4().hex[:8]}"
        yield f"data: {json.dumps({'type': 'meta', 'data': {'stream_id': stream_id}}, ensure_ascii=False)}\n\n"

        while combat.engine and not combat.engine.is_battle_over():
            try:
                ev = combat.event_queue.get(timeout=30)
                event_data = {
                    "type": ev.type,
                    "data": ev.data,
                }
                yield f"event: {ev.type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

                if ev.type == "battle_end":
                    yield f"data: {json.dumps({'type': 'done', 'data': {'stream_id': stream_id}}, ensure_ascii=False)}\n\n"
                    break
            except _queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat', 'data': {}}, ensure_ascii=False)}\n\n"

    return generate


def _check_combat_timeout(session, timeout: int = 600):
    """Check if a combat session has timed out. Returns error response or None.

    When a combat times out, the engine is stopped, a battle_end event is pushed
    to wake the SSE generator, and session.combat is cleared.
    """
    if not session.combat:
        return None
    combat = session.combat
    if not hasattr(combat, 'last_activity_at'):
        return None
    if time.time() - combat.last_activity_at <= timeout:
        return None

    encounter_id = getattr(combat, '_encounter_id', '未知')
    logger.warning("会话 %s: 战斗超时 (encounter=%s, idle=%.0fs)",
                   getattr(session, 'id', '?'), encounter_id,
                   time.time() - combat.last_activity_at)

    # Stop the engine and wake the SSE generator
    if combat.engine:
        combat.engine.state.phase = "END"
        try:
            _Event = type("_CombatEvent", (), {})
            ev = _Event()
            ev.type = "battle_end"
            ev.data = {"winner": "timeout", "reason": "战斗超时"}
            combat.event_queue.put_nowait(ev)
        except Exception:
            pass

    session.combat = None
    session.scene_manager._log_event(f"⚔ 战斗超时：遭遇战「{encounter_id}」")
    return json_error("战斗已超时，请重新开始", 410)


def register(app, managers):
    session_mgr = managers["session"]
    combat_test_mgr = managers["combat_test"]
    doc_mgr = managers["document"]

    bp = Blueprint("combat", __name__)

    # ══════════════════════════════════════════════════════
    # Session Combat
    # ══════════════════════════════════════════════════════

    @bp.route("/api/sessions/<session_id>/combat/start", methods=["POST"])
    def combat_start(session_id: str):
        """Start a battle for the session.

        Request body: {encounter_id: str, enemy_overrides: Optional[list]}
        Uses scene characters with session overlay attributes merged in.
        """
        from combat_session import CombatSession

        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        data = request.json or {}
        encounter_id = data.get("encounter_id", "初遇整合运动")
        enemy_overrides = data.get("enemy_overrides")

        # Build character metas with overlay merge
        character_metas = build_character_metas(session, doc_mgr)
        if not character_metas:
            return json_error("没有可用角色，请先加载角色到场景中", 400)

        # Normalize enemy_overrides: list of names -> list of {name, count, positions}
        enemies_override = None
        if enemy_overrides:
            enemies_override = []
            for item in enemy_overrides:
                if isinstance(item, str):
                    enemies_override.append({"name": item, "count": 1, "positions": []})
                elif isinstance(item, dict):
                    enemies_override.append({
                        "name": item.get("name", ""),
                        "count": item.get("count", 1),
                        "positions": item.get("positions", []),
                    })

        try:
            combat = CombatSession(session_id)
            state = combat.start(
                encounter_id,
                character_metas=character_metas,
                enemies_override=enemies_override,
            )
            session.combat = combat
            return jsonify(state)
        except ValueError as e:
            return json_error(str(e), 404)
        except Exception as e:
            logger.exception("Failed to start combat for session %s", session_id)
            return json_error(f"战斗启动失败: {e}", 500)

    @bp.route("/api/sessions/<session_id>/combat/state", methods=["GET"])
    def combat_state(session_id: str):
        """Get current combat state snapshot."""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        if not session.combat:
            return json_error("没有进行中的战斗", 404)

        err = _check_combat_timeout(session)
        if err:
            return err

        return jsonify(session.combat.get_state())

    @bp.route("/api/sessions/<session_id>/combat/action", methods=["POST"])
    def combat_action(session_id: str):
        """Submit a player action.

        Request body: {action: "play_card"|"move", card_index: int, unit_id: str, target: [row, col]}
        """
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        if not session.combat:
            return json_error("没有进行中的战斗", 404)

        err = _check_combat_timeout(session)
        if err:
            return err

        data = request.json or {}
        result = session.combat.handle_action(data)

        if not result.get("ok"):
            return json_error(result.get("error", "操作失败"), 400)

        return jsonify(result.get("state", {}))

    @bp.route("/api/sessions/<session_id>/combat/end-turn", methods=["POST"])
    def combat_end_turn(session_id: str):
        """Manually end the current player turn."""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        if not session.combat:
            return json_error("没有进行中的战斗", 404)

        err = _check_combat_timeout(session)
        if err:
            return err

        result = session.combat.end_turn()

        if not result.get("ok"):
            return json_error(result.get("error", "操作失败"), 400)

        return jsonify(result.get("state", {}))

    @bp.route("/api/sessions/<session_id>/combat/complete", methods=["POST"])
    def combat_complete(session_id: str):
        """Complete combat: record result to session overlay, then clear combat state."""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        if not session.combat:
            return json_error("没有进行中的战斗", 404)

        combat_data = session.combat.to_dict()
        overlay_data = session.overlay._data

        if "combat_history" not in overlay_data:
            overlay_data["combat_history"] = []

        # Accept frontend-submitted details (survivors, character_stats)
        req_data = request.json or {}

        history_entry = {
            "encounter_id": combat_data.get("encounter_id", ""),
            "result": combat_data.get("engine_state", {}).get("winner", ""),
            "rounds": combat_data.get("engine_state", {}).get("round_num", 0),
            "timestamp": time.time(),
        }
        # Store additional details from frontend
        for key in ("survivors", "character_stats"):
            if key in req_data:
                history_entry[key] = req_data[key]

        overlay_data["combat_history"].append(history_entry)

        # Keep only the last 20 entries
        if len(overlay_data["combat_history"]) > 20:
            overlay_data["combat_history"] = overlay_data["combat_history"][-20:]

        session.overlay._save()

        combat_history = overlay_data["combat_history"]
        winner = combat_data.get("engine_state", {}).get("winner", "")
        round_num = combat_data.get("engine_state", {}).get("round_num", 0)
        encounter_id = combat_data.get("encounter_id", "")

        # 将战斗结果注入场景日志，下一轮叙述会自动引用
        result_desc = "玩家" if winner == "player" else ("敌方" if winner else "未知")
        result_text = f"⚔ 战斗结束：遭遇战「{encounter_id}」— {result_desc}获胜，共 {round_num} 回合"
        session.scene_manager._log_event(result_text)

        session.combat = None

        # Generate auto-narrate action for frontend
        auto_narrate_action = f"战斗结束，{result_desc}获胜，描述战斗后的场景"

        logger.info("会话 %s: 战斗结果已记录 (winner=%s, rounds=%d)",
                     session_id, winner, round_num)
        return jsonify({
            "message": "战斗已结束",
            "history": combat_history,
            "auto_narrate_action": auto_narrate_action,
        })

    # ── Combat abandon ──

    @bp.route("/api/sessions/<session_id>/combat/abandon", methods=["POST"])
    def combat_abandon(session_id: str):
        """Abandon the active combat and return to dialogue."""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        if not session.combat:
            return json_error("没有进行中的战斗", 404)

        combat = session.combat
        encounter_id = getattr(combat, '_encounter_id', '未知')

        # Push battle_end event to wake up the SSE generator immediately
        # (otherwise it blocks on event_queue.get(timeout=30) for up to 30s)
        if combat.engine:
            combat.engine.state.phase = "END"
            combat.engine.state.winner = "abandoned"
            try:
                _Event = type("_CombatEvent", (), {})
                ev = _Event()
                ev.type = "battle_end"
                ev.data = {"winner": "abandoned", "reason": "战斗已放弃"}
                combat.event_queue.put_nowait(ev)
            except Exception:
                pass

        session.combat = None

        result_text = f"⚔ 战斗已放弃：遭遇战「{encounter_id}」"
        session.scene_manager._log_event(result_text)

        logger.info("会话 %s: 战斗已放弃 (encounter=%s)", session_id, encounter_id)
        return jsonify({
            "message": "战斗已放弃",
            "auto_narrate_action": "战斗已放弃，描述当前场景",
        })

    @bp.route("/api/sessions/<session_id>/combat/events")
    def combat_events(session_id: str):
        """SSE stream of combat events."""
        session = _get_session(session_mgr, session_id)
        if not session or not session.combat:
            def error_stream():
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'No combat session'}}, ensure_ascii=False)}\n\n"
            return make_sse_response(error_stream)

        return make_sse_response(_build_sse_generator(session.combat, stream_prefix="combat"))

    # ══════════════════════════════════════════════════════
    # Test Combat
    # ══════════════════════════════════════════════════════

    @bp.route("/api/combat/test/start", methods=["POST"])
    def combat_test_start():
        """Start a test combat session (no session required).

        Reads config from data/plots/combat-test/plot.md.
        Randomly samples enemies from the configured enemy pool.
        """
        from combat_session import CombatSession

        try:
            config = _load_combat_test_config()
        except ValueError as e:
            return json_error(str(e), 404)

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
            state = combat.start(
                encounter_id,
                character_names=character_names,
                enemies_override=enemies_override,
            )
            combat_test_mgr.create(test_id, combat)
            return jsonify({"test_id": test_id, "state": state})
        except Exception as e:
            logger.exception("Failed to start test combat")
            return json_error(f"战斗测试启动失败: {e}", 500)

    @bp.route("/api/combat/test/<test_id>/state", methods=["GET"])
    def combat_test_state(test_id: str):
        """Get test combat state."""
        combat = combat_test_mgr.get(test_id)
        if not combat:
            return json_error("测试战斗不存在或已过期", 404)
        return jsonify(combat.get_state())

    @bp.route("/api/combat/test/<test_id>/action", methods=["POST"])
    def combat_test_action(test_id: str):
        """Submit player action for test combat."""
        combat = combat_test_mgr.get(test_id)
        if not combat:
            return json_error("测试战斗不存在或已过期", 404)

        data = request.json or {}
        result = combat.handle_action(data)

        if not result.get("ok"):
            return json_error(result.get("error", "操作失败"), 400)

        return jsonify(result.get("state", {}))

    @bp.route("/api/combat/test/<test_id>/end-turn", methods=["POST"])
    def combat_test_end_turn(test_id: str):
        """Manually end current turn in test combat."""
        combat = combat_test_mgr.get(test_id)
        if not combat:
            return json_error("测试战斗不存在或已过期", 404)

        result = combat.end_turn()

        if not result.get("ok"):
            return json_error(result.get("error", "操作失败"), 400)

        return jsonify(result.get("state", {}))

    @bp.route("/api/combat/test/<test_id>/events")
    def combat_test_events(test_id: str):
        """SSE endpoint for test combat events."""
        combat = combat_test_mgr.get(test_id)
        if not combat:
            def error_stream():
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'Test combat not found'}}, ensure_ascii=False)}\n\n"
            return make_sse_response(error_stream)

        return make_sse_response(_build_sse_generator(combat, stream_prefix="test"))

    @bp.route("/api/combat/test/<test_id>", methods=["DELETE"])
    def combat_test_delete(test_id: str):
        """Delete a test combat session."""
        combat_test_mgr.remove(test_id)
        return jsonify({"ok": True})

    app.register_blueprint(bp)
