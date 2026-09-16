"""
Combat blueprint -- session combat, test combat, and combat-mode routes.
"""

import json
import uuid
import time
import logging
from pathlib import Path

from flask import Blueprint, jsonify, request

from shared.helpers import json_error, make_sse_response, build_character_metas
from combat_approaches import resolve_approach, list_approaches, roll_check
from combat_map import MapError
from combat_nodes import NodeError
from combat_engine.engine import CombatEvent
from combat_resume import (
    clear_resume as _clear_resume_file,
    list_test_resumes as _list_test_resumes,
    read_resume as _read_resume_file,
    session_resume_path as _session_resume_path,
    summarize as _summarize_resume,
    test_resume_path as _test_resume_path,
    write_resume as _write_resume_file,
)
from combat_settlement import (
    SettlementApplyError,
    apply_settlement,
    append_history,
    build_settlement,
)

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
    """Load the combat test plot config from data/plots/combat-test/index.md."""
    import frontmatter

    plot_path = _project_root / "data" / "plots" / "combat-test" / "index.md"
    if not plot_path.exists():
        raise ValueError("战斗测试配置文件不存在: data/plots/combat-test/index.md")
    with open(plot_path, "r", encoding="utf-8") as f:
        return dict(frontmatter.load(f).metadata)


# ── 战斗挂起 / 恢复（临时返回后继续打） ──
#
# 挂起 = 完整快照落盘 + 把战斗从内存摘下来（会话恢复可用、内存释放）；
# 恢复 = 从存档重建引擎。存档是唯一真相，内存态不保留，避免两份状态漂移。

#: 挂起存档有效期：超过则视为过期（惰性清理，避免「继续战斗」入口永久残留）
RESUME_TTL_SECONDS = 7 * 24 * 3600


def _resume_payload(path):
    """读取挂起存档；过期则顺手清掉并返回 None。"""
    payload = _read_resume_file(path)
    if not payload:
        return None
    saved_at = payload.get("suspended_at") or 0
    if saved_at and time.time() - saved_at > RESUME_TTL_SECONDS:
        logger.info("战斗挂起存档已过期，清理: %s", path)
        _clear_resume_file(path)
        return None
    return payload


def _detach_combat(session):
    """把战斗从会话上摘下来：先让 SSE 生成器尽快退出，再释放内存态。

    直接置 None 会让正在 `event_queue.get(timeout=30)` 阻塞的 SSE 线程白等 30 秒，
    因此这里置 suspended 标记并投一个哨兵事件把它唤醒。
    """
    combat = session.combat
    if combat is None:
        return None
    combat.suspended = True
    try:
        combat.event_queue.put_nowait(
            CombatEvent("suspend", {"reason": "战斗已挂起"}))
    except Exception:
        pass
    session.combat = None
    return combat


def _build_sse_generator(combat, stream_prefix="combat", session=None):
    """Return a generator function for SSE combat event streams.

    `session` 非空时，胜利（battle_end, winner=player）会在事件下发前自动
    生成并持久化待结算记录，并随事件 data.settlement 一起推送给前端——
    结算流程因此「不跳过、不延迟」，且多波次战斗只在最后一波清空后触发一次。
    """
    import uuid as _uuid
    import queue as _queue

    def generate():
        stream_id = f"{stream_prefix}_{_uuid.uuid4().hex[:8]}"
        yield f"data: {json.dumps({'type': 'meta', 'data': {'stream_id': stream_id}}, ensure_ascii=False)}\n\n"

        while (combat.engine and not combat.engine.is_battle_over()
               and not getattr(combat, "suspended", False)):
            try:
                ev = combat.event_queue.get(timeout=30)
                data = ev.data

                if ev.type == "battle_end":
                    settlement = _settlement_for_event(session, combat, data)
                    if settlement is not None:
                        data = {**data, "settlement": settlement}

                event_data = {
                    "type": ev.type,
                    "data": data,
                }
                yield f"event: {ev.type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

                if ev.type == "battle_end":
                    yield f"data: {json.dumps({'type': 'done', 'data': {'stream_id': stream_id}}, ensure_ascii=False)}\n\n"
                    break
            except _queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat', 'data': {}}, ensure_ascii=False)}\n\n"

    return generate


def _settlement_for_event(session, combat, data: dict) -> dict | None:
    """battle_end 事件到达时组装/读取待结算数据；失败不影响战斗结束事件下发。"""
    if session is None or (data or {}).get("winner") != "player":
        return None
    try:
        pending = _ensure_pending_settlement(session, combat=combat)
        return pending["data"] if pending else None
    except Exception:
        logger.exception("会话 %s: 战斗结算数据生成失败，前端可稍后重试",
                         getattr(session, "id", "?"))
        return None


def _check_combat_timeout(session, timeout: int = 600):
    """Check if a combat session has timed out. Returns error response or None.

    When a combat times out, the engine is stopped, a battle_end event is pushed
    to wake the SSE generator, and session.combat is cleared.

    已结束的战斗（battle_over）不做 idle 超时清理：结果尚未通过 complete 回写，
    此时清掉 session.combat 会导致 complete 404，玩家被永久卡在结算界面。
    """
    if not session.combat:
        return None
    combat = session.combat
    if not hasattr(combat, 'last_activity_at'):
        return None
    if combat.engine and combat.engine.is_battle_over():
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
            combat.event_queue.put_nowait(
                CombatEvent("battle_end", {"winner": "timeout", "reason": "战斗超时"}))
        except Exception:
            pass

    session.combat = None
    session.scene_manager._log_event(f"⚔ 战斗超时：遭遇战「{encounter_id}」")
    return json_error("战斗已超时，请重新开始", 410)


# ── 战斗奖励结算 ──
#
# 数值计算 / 组装 / 写回逻辑集中在 combat_settlement.py（纯函数，可单测）；
# 本 blueprint 只负责：触发时机、幂等的待结算记录、调用写回、返回 DTO。


def _ensure_pending_settlement(session, combat=None, combat_data: dict | None = None,
                               reward_mult: float | None = None) -> dict | None:
    """幂等地生成/读取待结算记录。

    - 已有待结算记录 → 直接返回（避免重复 roll 掉落 / 重复抽卡）
    - 非胜利 → 返回 None
    - 胜利 → 组装结算 DTO 并持久化到 overrides.json.pending_settlement，
      同时把卡牌候选写入既有的 pending_card_choices 字段（供 card-pick 端点消费）
    """
    existing = session.overlay.get_pending_settlement()
    if existing:
        return existing

    if combat_data is None:
        combat_data = combat.snapshot() if combat is not None else {}
    engine_state = combat_data.get("engine_state", {}) or {}
    winner = engine_state.get("winner") or combat_data.get("winner") or ""
    if winner != "player":
        return None

    if reward_mult is None:
        reward_mult = float(combat_data.get("reward_mult", 1.0) or 1.0)

    data = build_settlement(session, combat_data, reward_mult)
    pending = {
        "settlement_id": data["settlement_id"],
        "encounter_id": data.get("encounter_id", ""),
        "winner": winner,
        "rounds": data.get("rounds", 0),
        "reward_mult": reward_mult,
        "created_at": data.get("created_at"),
        "data": data,
        # 写回进度标记：失败重试时跳过已写回的角色/背包
        "applied": {"characters": [], "inventory": False},
    }
    session.overlay._data["pending_card_choices"] = data.get("rewards", {}).get("cards", [])
    session.overlay.set_pending_settlement(pending)
    logger.info("会话 %s: 待结算记录已生成 (encounter=%s, xp=%d, 角色=%d)",
                getattr(session, "id", "?"), pending["encounter_id"],
                data.get("rewards", {}).get("xp_total", 0), len(data.get("characters", [])))
    return pending


def _build_ephemeral_settlement(session, combat_data: dict, reward_mult: float) -> dict:
    """为战败/撤退等没有待结算记录的场景组装一次性结算 DTO（不落盘）。"""
    data = build_settlement(session, combat_data, reward_mult)
    return {
        "settlement_id": data["settlement_id"],
        "encounter_id": data.get("encounter_id", ""),
        "winner": data.get("winner", ""),
        "rounds": data.get("rounds", 0),
        "reward_mult": reward_mult,
        "created_at": data.get("created_at"),
        "data": data,
        "applied": {"characters": [], "inventory": False},
    }


def _get_combat_inventory(session) -> list[dict]:
    """从会话背包读取战斗中可用的消耗品（category=consumable 且 count>0）。"""
    from combat_data_loader import CombatDataLoader
    loader = CombatDataLoader()
    result = []
    for entry in session.overlay._data.get("inventory", []):
        name = entry.get("name", "")
        if int(entry.get("count", 0)) <= 0:
            continue
        meta = loader.load_item_meta(name)
        if meta and meta.get("category") == "consumable":
            result.append({"name": name, "count": int(entry.get("count", 1))})
    return result


def _use_item(session, data: dict) -> dict:
    """使用消耗品：校验背包 → 应用效果 → 消耗背包 → 返回最新 state。"""
    item_name = data.get("item_name", "")
    target_id = data.get("unit_id", "")

    inventory = session.overlay._data.get("inventory", [])
    entry = next((e for e in inventory if e.get("name") == item_name), None)
    if not entry or int(entry.get("count", 0)) <= 0:
        return {"ok": False, "error": f"背包中没有 '{item_name}'"}

    result = session.combat.use_item(item_name, target_id)
    if not result.get("ok"):
        return result

    # 消耗持久化背包
    entry["count"] = int(entry.get("count", 1)) - 1
    if entry["count"] <= 0:
        inventory.remove(entry)
    session.overlay._save()

    return result


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
        approach_id = data.get("approach_id")

        from combat_data_loader import CombatDataLoader
        encounter = CombatDataLoader().load_node(encounter_id) or {}

        # Build character metas with overlay merge
        character_metas = build_character_metas(session, doc_mgr)
        if not character_metas:
            return json_error("没有可用角色，请先加载角色到场景中", 400)

        # 战前打法（Approach）：遭遇战显式声明 approaches 且未选定时，先返回打法列表
        if approach_id is None and encounter.get("approaches"):
            return jsonify({
                "ok": True, "kind": "approaches", "encounter_id": encounter_id,
                "approaches": list_approaches(encounter),
            })

        resolved = resolve_approach(encounter, approach_id)
        kind = resolved["kind"]
        reward_mult = resolved["reward_mult"]

        # 撤退：直接跳过战斗
        if kind == "avoid":
            return jsonify({
                "ok": True, "kind": "avoid", "encounter_id": encounter_id,
                "label": resolved["label"], "hint": resolved["hint"],
            })

        # 谈判/抉择：d20 剧情投点
        check = None
        combat_params = resolved["combat_params"]
        if kind == "check":
            check = roll_check(character_metas, resolved["check"])
            if check["success"]:
                return jsonify({
                    "ok": True, "kind": "check", "encounter_id": encounter_id,
                    "label": resolved["label"], "hint": resolved["hint"],
                    "check": check, "combat_started": False,
                })
            # 失败 → 以 fail_combat 参数强制开战
            combat_params = resolved["fail_combat_params"]

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
            # 新开一场：清掉上一场遗留的挂起存档，避免「继续战斗」指向旧局
            _clear_resume_file(_session_resume_path(session))
            state = combat.start(
                encounter_id,
                character_metas=character_metas,
                enemies_override=enemies_override,
                combat_params=combat_params,
                location=session.environment.location or "",
                session_dir=str(session.data_dir),
                inventory=_get_combat_inventory(session),
                reward_mult=reward_mult,
                bonus_cards=session.overlay._data.get("combat_deck", []),
            )
            session.combat = combat
            resp = {"ok": True, "kind": kind, "encounter_id": encounter_id,
                    "label": resolved["label"], "state": state}
            if check is not None:
                resp["check"] = check
                resp["combat_started"] = True
            return jsonify(resp)
        except MapError as e:
            return json_error(f"战场配置无效：{e}", 400)
        except NodeError as e:
            # 节点本身没问题但内容不可开战（例如没有敌人）→ 400 而非 404
            return json_error("；".join(e.errors), 400)
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

        selected_unit = request.args.get("selected_unit", "")
        return jsonify(session.combat.get_state(selected_unit_id=selected_unit))

    # ── 挂起 / 恢复：临时返回主页或会话界面，稍后继续打 ──

    @bp.route("/api/sessions/<session_id>/combat/suspend", methods=["POST"])
    def combat_suspend(session_id: str):
        """保存当前战斗态势并离开（角色状态 / 手牌 / 牌堆 / 战场局势全部落盘）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        if not session.combat:
            return json_error("没有进行中的战斗", 404)

        path = _session_resume_path(session)
        try:
            payload = session.combat.suspend_snapshot()
        except ValueError as e:
            return json_error(str(e), 400)

        try:
            _write_resume_file(path, payload)
        except OSError as e:
            logger.exception("会话 %s: 战斗挂起存档写入失败", session_id)
            return json_error(f"战斗状态保存失败：{e}", 500)

        encounter_id = getattr(session.combat, "_encounter_id", "")
        _detach_combat(session)
        logger.info("会话 %s: 战斗已挂起 (encounter=%s, round=%s)",
                    session_id, encounter_id, (payload.get("engine", {}).get("state") or {}).get("round_num"))
        return jsonify({
            "ok": True,
            "message": "战斗状态已保存",
            "resume": _summarize_resume(_read_resume_file(path)),
        })

    @bp.route("/api/sessions/<session_id>/combat/resume", methods=["POST"])
    def combat_resume(session_id: str):
        """恢复挂起的战斗并返回最新态势（内存中仍在时直接返回，不重复重建）。"""
        from combat_session import CombatSession

        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        if session.combat:
            return jsonify({"ok": True, "resumed": False, "state": session.combat.get_state()})

        path = _session_resume_path(session)
        payload = _resume_payload(path)
        if payload is None:
            return json_error("没有可恢复的战斗", 404)

        try:
            combat = CombatSession.from_suspend_snapshot(
                payload, session_id, session_dir=str(session.data_dir))
        except ValueError as e:
            # 节点已删除等不可恢复的情形：清掉存档，避免入口永久卡住
            logger.warning("会话 %s: 战斗恢复失败，清理挂起存档: %s", session_id, e)
            _clear_resume_file(path)
            return json_error(f"战斗恢复失败：{e}", 410)

        session.combat = combat
        # 存档是一次性交接件：恢复后内存态即真相源。留着会让「继续战斗」多出
        # 一条指向进行中战斗的陈旧入口，且进程重启会悄悄回滚到恢复前的态势。
        _clear_resume_file(path)
        logger.info("会话 %s: 战斗已恢复 (encounter=%s, round=%d)",
                    session_id, combat._encounter_id, combat.engine.state.round_num)
        return jsonify({
            "ok": True, "resumed": True,
            "state": combat.get_state(),
            "resume": _summarize_resume(payload),
        })

    @bp.route("/api/sessions/<session_id>/combat/suspend", methods=["DELETE"])
    def combat_discard_suspend(session_id: str):
        """丢弃挂起存档（放弃这场战斗，不再提供恢复入口）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        removed = _clear_resume_file(_session_resume_path(session))
        return jsonify({"ok": True, "removed": removed})

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
        if data.get("action") == "use_item":
            result = _use_item(session, data)
        else:
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

        req_data = request.json or {}
        combat_data = session.combat.snapshot() if session.combat else None
        pending = session.overlay.get_pending_settlement()

        if pending is None and combat_data is None:
            return json_error("没有进行中的战斗", 404)

        # 胜利：待结算记录已在 battle_end 时自动生成并持久化；
        # 战败/撤退/客户端直连旧路径：此处现算一份（不落盘）。
        if pending is None:
            reward_mult = float(combat_data.get("reward_mult", 1.0) or 1.0)
            pending = _build_ephemeral_settlement(session, combat_data, reward_mult)

        settlement = pending["data"]
        winner = settlement.get("winner", "") or req_data.get("winner", "")
        round_num = settlement.get("rounds", 0) or req_data.get("rounds", 0)
        encounter_id = settlement.get("encounter_id", "") or req_data.get("encounter_id", "")
        reward_mult = float(settlement.get("reward_mult", 1.0) or 1.0)

        # 将战斗结果注入场景日志，下一轮叙述会自动引用
        if winner == "player":
            result_desc = "玩家"
        elif winner == "escaped":
            result_desc = "玩家（撤退）"
        elif winner == "enemy":
            result_desc = "敌方"
        else:
            result_desc = "未知"
        result_text = f"⚔ 战斗结束：遭遇战「{encounter_id}」— {result_desc}获胜，共 {round_num} 回合"
        if winner == "escaped":
            result_text = f"⚔ 战斗结束：遭遇战「{encounter_id}」— 玩家撤退，共 {round_num} 回合"
        session.scene_manager._log_event(result_text)

        # ── 写回剧情角色数值（幂等：失败重试不会重复发放）──
        try:
            apply_settlement(session, pending)
        except SettlementApplyError as e:
            # 兜底：保留战斗与待结算记录，玩家可点「重试结算」；不清空 session.combat
            logger.error("会话 %s: 战斗结算写回失败，保留待结算记录: %s", session_id, e)
            return json_error(f"战斗结算写入失败：{e}", 500)

        # ── 战斗历史 + 清理 ──
        history = append_history(
            session,
            encounter_id=encounter_id,
            winner=winner,
            rounds=round_num,
            reward_mult=reward_mult,
            settlement=settlement,
            extra={k: req_data.get(k) for k in ("survivors", "character_stats")},
        )
        session.overlay._data["pending_card_choices"] = []
        session.overlay.clear_pending_settlement()
        session.combat = None
        _clear_resume_file(_session_resume_path(session))

        # Generate auto-narrate action for frontend（fail-forward：撤退/战败都不判死，继续推进）
        if winner == "escaped":
            auto_narrate_action = "战斗以玩家撤退告终，描述撤退后的场景与代价"
        elif winner == "player":
            auto_narrate_action = "战斗结束，玩家获胜，描述战斗后的场景"
        else:
            auto_narrate_action = "战斗失利，描述战败后的场景与代价（fail-forward，剧情继续推进）"

        logger.info("会话 %s: 战斗结果已记录 (winner=%s, rounds=%d, xp=%d)",
                     session_id, winner, round_num,
                     int((settlement.get("rewards", {}) or {}).get("xp_total", 0) or 0))
        return jsonify({
            "message": "战斗已结束",
            "history": history,
            "settlement": settlement,
            "auto_narrate_action": auto_narrate_action,
        })

    # ── 战斗结算（自动触发 + 断线恢复） ──

    @bp.route("/api/sessions/<session_id>/combat/settlement", methods=["POST"])
    def combat_settlement(session_id: str):
        """生成/读取本场战斗的结算数据（幂等，供前端自动展示）。

        胜利判定成立后由前端自动调用（SSE battle_end 也会携带同一份数据）；
        页面刷新、SSE 断线重连时再次调用会拿到同一份记录，不会重复 roll 掉落。
        """
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        pending = session.overlay.get_pending_settlement()
        if pending is None:
            if not session.combat:
                return json_error("没有进行中的战斗，也没有待结算记录", 404)
            try:
                pending = _ensure_pending_settlement(session, combat=session.combat)
            except Exception:
                logger.exception("会话 %s: 结算数据组装失败", session_id)
                return json_error("结算数据生成失败，请重试", 500)

        if pending is None:
            # 未获胜：明确告知（前端展示「本场无结算」而不是空列表）
            engine_state = (session.combat.snapshot().get("engine_state", {})
                            if session.combat else {})
            return jsonify({
                "ok": True,
                "settlement": None,
                "winner": engine_state.get("winner") or "",
                "message": "本场战斗未获胜，没有结算奖励",
            })

        return jsonify({"ok": True, "settlement": pending["data"]})

    # ── Combat abandon ──

    @bp.route("/api/sessions/<session_id>/combat/card-pick", methods=["POST"])
    def combat_card_pick(session_id: str):
        """战后 1 选 1：把选中的卡牌加入会话持久卡组（combat_deck）。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        data = request.json or {}
        card_id = data.get("card_id", "")
        if not card_id:
            return json_error("缺少 card_id", 400)

        pending = session.overlay._data.get("pending_card_choices", [])
        picked = next((c for c in pending if c.get("card_id") == card_id), None)
        if not picked:
            return json_error("该卡牌不在候选列表中", 400)

        deck = session.overlay._data.get("combat_deck", [])
        if any(c.get("card_id") == card_id for c in deck):
            return json_error("已拥有该卡牌", 400)

        deck.append(picked)
        session.overlay._data["combat_deck"] = deck
        session.overlay._data["pending_card_choices"] = []
        session.overlay._save()
        logger.info("会话 %s: 战后选卡 %s，卡组大小 %d", session_id, card_id, len(deck))
        return jsonify({"ok": True, "card_id": card_id, "deck_size": len(deck)})

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
                combat.event_queue.put_nowait(
                    CombatEvent("battle_end", {"winner": "abandoned", "reason": "战斗已放弃"}))
            except Exception:
                pass

        session.combat = None
        _clear_resume_file(_session_resume_path(session))
        # 放弃战斗不结算：清掉可能已生成的待结算记录与卡牌候选，避免泄漏到下一场
        session.overlay._data["pending_card_choices"] = []
        session.overlay.clear_pending_settlement()

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

        return make_sse_response(_build_sse_generator(session.combat, stream_prefix="combat",
                                                       session=session))

    # ══════════════════════════════════════════════════════
    # Test Combat
    # ══════════════════════════════════════════════════════

    @bp.route("/api/combat/test/start", methods=["POST"])
    def combat_test_start():
        """Start an ad-hoc combat from a battle node (no session required).

        直接按节点 JSON 开战：不再走 `data/plots/combat-test` 的敌人池随机采样，
        编排完全由节点决定（便于编辑器"试打这个节点"）。
        """
        from combat_session import CombatSession

        data = request.json or {}
        node_id = data.get("node_id") or data.get("encounter_id") or ""
        if not node_id:
            try:
                config = _load_combat_test_config()
                node_id = config.get("default_encounter", "enc_training")
            except ValueError:
                node_id = "enc_training"
        # 默认队伍：三人均有 Spine 战斗小人（博士/霜星无骨骼，故不作为默认出战单位）
        character_names = data.get("characters")
        if not character_names:
            try:
                character_names = _load_combat_test_config().get("characters")
            except ValueError:
                character_names = None
        character_names = character_names or ["阿米娅", "银灰", "灵知"]

        test_id = uuid.uuid4().hex[:12]
        try:
            combat = CombatSession(test_id)
            _clear_resume_file(_test_resume_path(test_id))
            state = combat.start(node_id, character_names=character_names)
            combat_test_mgr.create(test_id, combat)
            return jsonify({"test_id": test_id, "node_id": node_id, "state": state})
        except MapError as e:
            return json_error(f"战场配置无效：{e}", 400)
        except NodeError as e:
            # 节点本身没问题但内容不可开战（例如没有敌人）→ 400 而非 404
            return json_error("；".join(e.errors), 400)
        except ValueError as e:
            return json_error(str(e), 404)
        except Exception as e:
            logger.exception("Failed to start test combat")
            return json_error(f"战斗测试启动失败: {e}", 500)

    # ── 只读目录（选择器 / 前端下拉；编辑器的节点 CRUD 见 blueprints/combat_nodes.py）──

    @bp.route("/api/combat/enemies", methods=["GET"])
    def combat_enemies():
        """敌人图鉴（叙事字段 + 战斗数值；标记是否为 attributes 派生）。"""
        from combat_data_loader import CombatDataLoader
        return jsonify({"enemies": CombatDataLoader().list_enemy_catalog()})

    @bp.route("/api/combat/tiles", methods=["GET"])
    def combat_tiles():
        """格子类型注册表（内置 + data/combat/tiles/*.json）。"""
        from combat_data_loader import CombatDataLoader
        registry, warnings = CombatDataLoader().load_tile_registry()
        return jsonify({
            "tiles": [tile.to_dict() for tile in registry.values()],
            "warnings": warnings,
        })

    @bp.route("/api/combat/test/<test_id>/state", methods=["GET"])
    def combat_test_state(test_id: str):
        """Get test combat state."""
        combat = combat_test_mgr.get(test_id)
        if not combat:
            return json_error("测试战斗不存在或已过期", 404)
        selected_unit = request.args.get("selected_unit", "")
        return jsonify(combat.get_state(selected_unit_id=selected_unit))

    # ── 战斗测试的挂起 / 恢复（无会话，存档按 test_id 落在 data/memory 下） ──

    @bp.route("/api/combat/test/<test_id>/suspend", methods=["POST"])
    def combat_test_suspend(test_id: str):
        """保存测试战斗态势并离开；测试战斗不写剧情，存档仅为「稍后接着试打」。"""
        combat = combat_test_mgr.get(test_id)
        if not combat:
            return json_error("测试战斗不存在或已过期", 404)

        path = _test_resume_path(test_id)
        try:
            payload = combat.suspend_snapshot()
        except ValueError as e:
            return json_error(str(e), 400)

        try:
            _write_resume_file(path, payload)
        except OSError as e:
            logger.exception("战斗测试 %s: 挂起存档写入失败", test_id)
            return json_error(f"战斗状态保存失败：{e}", 500)

        # 测试战斗没有 SSE 会话外的清理责任：先让流退出再摘掉内存态
        combat.suspended = True
        try:
            combat.event_queue.put_nowait(
                CombatEvent("suspend", {"reason": "战斗已挂起"}))
        except Exception:
            pass
        combat_test_mgr.remove(test_id)
        logger.info("战斗测试 %s: 已挂起 (encounter=%s)", test_id, combat._encounter_id)
        return jsonify({
            "ok": True,
            "message": "战斗状态已保存",
            "resume": _summarize_resume(_read_resume_file(path)),
        })

    @bp.route("/api/combat/test/<test_id>/resume", methods=["POST"])
    def combat_test_resume(test_id: str):
        """恢复挂起的测试战斗（沿用原 test_id，前端无需改上下文）。"""
        from combat_session import CombatSession

        combat = combat_test_mgr.get(test_id)
        if combat:
            return jsonify({"ok": True, "resumed": False, "state": combat.get_state()})

        path = _test_resume_path(test_id)
        payload = _resume_payload(path)
        if payload is None:
            return json_error("没有可恢复的战斗测试", 404)

        try:
            restored = CombatSession.from_suspend_snapshot(payload, test_id)
        except ValueError as e:
            logger.warning("战斗测试 %s: 恢复失败，清理挂起存档: %s", test_id, e)
            _clear_resume_file(path)
            return json_error(f"战斗恢复失败：{e}", 410)

        combat_test_mgr.create(test_id, restored)
        # 同会话战：恢复即消费存档，避免 /api/combat/resumes 里残留已在进行中的入口
        _clear_resume_file(path)
        logger.info("战斗测试 %s: 已恢复 (encounter=%s)", test_id, restored._encounter_id)
        return jsonify({
            "ok": True, "resumed": True,
            "state": restored.get_state(),
            "resume": _summarize_resume(payload),
        })

    @bp.route("/api/combat/test/<test_id>/suspend", methods=["DELETE"])
    def combat_test_discard_suspend(test_id: str):
        """丢弃测试战斗的挂起存档。"""
        removed = _clear_resume_file(_test_resume_path(test_id))
        return jsonify({"ok": True, "removed": removed})

    @bp.route("/api/combat/resumes", methods=["GET"])
    def combat_resumes():
        """全部可恢复的战斗：会话战（按会话挂起存档）+ 战斗测试。

        会话战的判据直接复用会话 DTO 的 `combat_resumable`，避免两处口径漂移。
        """
        sessions = [s for s in session_mgr.list_sessions() if s.get("combat_resumable")]
        return jsonify({
            "sessions": [
                {
                    "session_id": s.get("id"),
                    "name": s.get("name"),
                    "mode": s.get("mode"),
                    "in_memory": bool(s.get("in_combat")),
                    "combat": s.get("combat_resume"),
                }
                for s in sessions
            ],
            "tests": _list_test_resumes(),
        })

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
        """Delete a test combat session（含挂起存档）。"""
        combat_test_mgr.remove(test_id)
        _clear_resume_file(_test_resume_path(test_id))
        return jsonify({"ok": True})

    app.register_blueprint(bp)
