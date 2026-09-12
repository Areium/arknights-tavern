"""回归测试：战斗结束后 idle 超时不应导致 combat/complete 404。

Bug 背景：战斗结束后玩家停留在结算界面，若距最后一次操作超过 600s，
携带超时检查的请求（combat/state 等）会把 session.combat 清掉；
之后玩家点"返回对话"触发 complete → 404 → 前端弹"战斗结果保存失败"
且不重试成功，玩家被永久卡在战斗界面。
"""
import sys
import time

sys.path.insert(0, "src")

import pytest

from app import create_app


@pytest.fixture()
def client():
    app = create_app()
    return app, app.test_client()


def _start_combat(app, client):
    r = client.post("/api/sessions", json={"mode": "free", "combat_mode": "tactical"})
    sid = r.get_json()["id"]
    client.post(f"/api/sessions/{sid}/characters/load", json={"character": "临光"})
    r = client.post(f"/api/sessions/{sid}/combat/start", json={"encounter_id": "enc_quick_test_1"})
    assert r.status_code == 200 and r.get_json().get("state"), r.get_json()
    return sid


def _force_player_win(app, sid):
    session = app._managers["session"].get_session(sid)
    eng = session.combat.engine
    for u in eng.units.values():
        if u.team == "enemy":
            u.hp = 0
    eng.state.winner = "player"
    eng.state.phase = "END"
    return session


def _complete(client, sid):
    return client.post(f"/api/sessions/{sid}/combat/complete", json={
        "encounter_id": "enc_quick_test_1",
        "winner": "player",
        "survivors": ["临光"],
        "rounds": 1,
        "character_stats": {},
    })


def test_battle_over_immune_to_idle_timeout(client):
    """战斗已结束：idle 超时后 combat/state 不清理，complete 正常回写。"""
    app, c = client
    sid = _start_combat(app, c)
    session = _force_player_win(app, sid)

    # 模拟玩家在结算界面停留超过 600s
    session.combat.last_activity_at = time.time() - 601

    r = c.get(f"/api/sessions/{sid}/combat/state")
    assert r.status_code == 200, r.get_json()
    assert session.combat is not None, "已结束的战斗不应被超时清理"

    r = _complete(c, sid)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["auto_narrate_action"]
    assert session.combat is None, "complete 后应清理战斗状态"


def test_ongoing_battle_still_times_out(client):
    """回归保护：战斗进行中 idle 超时仍应被清理（410）。"""
    app, c = client
    sid = _start_combat(app, c)
    session = app._managers["session"].get_session(sid)
    assert not session.combat.engine.is_battle_over()

    session.combat.last_activity_at = time.time() - 601

    r = c.get(f"/api/sessions/{sid}/combat/state")
    assert r.status_code == 410
    assert session.combat is None
