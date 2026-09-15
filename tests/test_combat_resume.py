"""战斗挂起 / 恢复：临时返回后继续打的存档保真度与接口行为。

对应前端「⏸ 临时返回」→「▶ 继续战斗」链路。核心约束：
- 挂起必须落盘**完整**战斗态（角色状态 / 手牌 / 牌堆 / 战场局势 / 待入场波次），
  恢复后 `get_state()` 与原状态逐字段一致，否则会出现「战场回来了但牌不对」。
- 挂起后内存态释放（`session.combat is None`）但 `combat_resumable` 为真，
  因此会话界面能给出「继续战斗」入口。
- 战斗结束 / 放弃 / 会话删除时挂起存档必须清掉，避免入口永久残留。
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app import create_app  # noqa: E402
# 注意：test_resume_path 名字以 test_ 开头，直接导入会被 pytest 当成用例收集
# （并以 test_id 为 fixture 报 ERROR），故一律加下划线别名。
from combat_resume import (  # noqa: E402
    clear_resume, read_resume, session_resume_path, summarize,
    test_resume_path as _test_resume_path,
)

#: 战斗测试用节点（无 approaches，开局即进战斗）
NODE_ID = "enc_training"
#: 会话战用节点（同上，且被 test_combat_complete_timeout 复用为稳定夹具）
SESSION_NODE_ID = "enc_quick_test_1"
#: 恢复前后允许变化的字段：依赖 selected_unit / 回合内临时计算，不属战斗态势
VOLATILE = ("valid_moves", "valid_targets")


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _norm(state: dict) -> dict:
    s = json.loads(json.dumps(state, ensure_ascii=False, sort_keys=True))
    for k in VOLATILE:
        s.pop(k, None)
    return s


def _diff(a, b, path="") -> list[str]:
    """逐字段比对，返回差异描述（比 assertEqual 的整块 diff 更好定位）。"""
    if type(a) is not type(b):
        return [f"{path}: 类型 {type(a).__name__} != {type(b).__name__}"]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: 恢复后多出")
            elif k not in b:
                out.append(f"{path}.{k}: 恢复后丢失")
            else:
                out += _diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}: 长度 {len(a)} != {len(b)}"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


# ── 战斗测试（无会话）──

def test_test_battle_suspend_resume_round_trip(client):
    start = client.post("/api/combat/test/start", json={"node_id": NODE_ID})
    assert start.status_code == 200, start.get_json()
    test_id = start.get_json()["test_id"]
    before = start.get_json()["state"]

    # 打一张牌 + 结束回合，让「手牌/牌堆/弃牌堆/回合数」都偏离初始值，
    # 否则初始态过于整齐，恢复逻辑漏字段也测不出来。
    hand = before.get("shared_hand") or []
    if hand:
        client.post(f"/api/combat/test/{test_id}/action",
                    json={"action": "play_card", "card_index": 0,
                          "target": hand[0].get("target_pos") or [0, 0]})
    client.post(f"/api/combat/test/{test_id}/end-turn")

    live = client.get(f"/api/combat/test/{test_id}/state").get_json()
    assert not live["battle_over"], "开局即结束，测试前提不成立"

    path = _test_resume_path(test_id)
    clear_resume(path)

    sus = client.post(f"/api/combat/test/{test_id}/suspend")
    assert sus.status_code == 200, sus.get_json()
    assert path.is_file(), "挂起后存档必须落盘"
    payload = read_resume(path)
    assert payload and payload["engine"]["units"], "存档必须含单位状态"

    # 挂起后内存态释放：原 test_id 已不可用（否则「释放内存」是假的）
    assert client.get(f"/api/combat/test/{test_id}/state").status_code == 404

    res = client.post(f"/api/combat/test/{test_id}/resume")
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["resumed"] is True
    assert not path.is_file(), "恢复成功后存档应被消费掉"

    after = res.get_json()["state"]
    assert _diff(_norm(live), _norm(after), "state") == []

    # 恢复后仍可继续操作（引擎真的活了，而不是只把状态回放了一遍）
    assert client.post(f"/api/combat/test/{test_id}/end-turn").status_code == 200
    client.delete(f"/api/combat/test/{test_id}")


def test_resume_without_snapshot_is_404(client):
    assert client.post("/api/combat/test/t_not_exist/resume").status_code == 404


def test_resume_twice_returns_in_memory_state(client):
    """第二次恢复不重建：战斗已在内存，直接返回当前态势（resumed=False）。"""
    start = client.post("/api/combat/test/start", json={"node_id": NODE_ID})
    test_id = start.get_json()["test_id"]
    clear_resume(_test_resume_path(test_id))

    assert client.post(f"/api/combat/test/{test_id}/suspend").status_code == 200
    assert client.post(f"/api/combat/test/{test_id}/resume").status_code == 200
    # 存档已被消费，且内存里已在战斗中 → 第二次 resume 走「已存在」分支（resumed=False）
    again = client.post(f"/api/combat/test/{test_id}/resume")
    assert again.status_code == 200
    assert again.get_json()["resumed"] is False
    client.delete(f"/api/combat/test/{test_id}")


def test_discard_suspend_removes_entry(client):
    start = client.post("/api/combat/test/start", json={"node_id": NODE_ID})
    test_id = start.get_json()["test_id"]
    clear_resume(_test_resume_path(test_id))

    assert client.post(f"/api/combat/test/{test_id}/suspend").status_code == 200
    assert _test_resume_path(test_id).is_file()

    assert client.delete(f"/api/combat/test/{test_id}/suspend").status_code == 200
    assert not _test_resume_path(test_id).is_file()
    assert client.post(f"/api/combat/test/{test_id}/resume").status_code == 404


def test_resumes_list_reports_suspended_tests(client):
    start = client.post("/api/combat/test/start", json={"node_id": NODE_ID})
    test_id = start.get_json()["test_id"]
    clear_resume(_test_resume_path(test_id))
    client.post(f"/api/combat/test/{test_id}/suspend")

    data = client.get("/api/combat/resumes").get_json()
    assert isinstance(data.get("sessions"), list) and isinstance(data.get("tests"), list)
    entry = next((t for t in data["tests"] if t["test_id"] == test_id), None)
    assert entry is not None, "挂起的测试战必须出现在「继续战斗」列表里"
    assert entry["encounter_id"] == NODE_ID
    assert entry["battle_over"] is False
    assert entry["player_alive"] >= 1
    assert isinstance(entry["hand_size"], int)
    assert entry["suspended_at"] > 0

    clear_resume(_test_resume_path(test_id))


# ── 会话战 ──

@pytest.fixture
def session_id(client):
    """建一个战术会话并把角色载入场景，用于会话战链路；结束后删除会话。

    注意：`combat/start` 的参战角色取自**场景角色**（`build_character_metas`
    读 scene_manager），创建会话时传 `characters` 并不进场景，必须显式
    `characters/load`，否则 start 直接 400「没有可用角色」。
    """
    res = client.post("/api/sessions", json={"mode": "free", "combat_mode": "tactical"})
    assert res.status_code in (200, 201), res.get_json()
    sid = res.get_json()["id"]
    loaded = client.post(f"/api/sessions/{sid}/characters/load", json={"character": "临光"})
    assert loaded.status_code == 200, loaded.get_json()
    try:
        yield sid
    finally:
        client.delete(f"/api/sessions/{sid}")


def _managers(client):
    """取 app 上挂的 Manager 注册表（app factory 在 `app._managers` 暴露）。"""
    return client.application._managers


def _session_dir(client, session_id: str) -> Path:
    """会话数据目录：DTO 未直接暴露，经 backgrounds_dir 的父目录反推。"""
    sessions = client.get("/api/sessions").get_json()
    dto = next((s for s in sessions if s["id"] == session_id), None)
    assert dto is not None, f"会话 {session_id} 不在列表中"
    return Path(dto["backgrounds_dir"]).parent


def _session_resume_file(client, session_id: str) -> Path:
    """会话战存档路径（会话目录内的 combat_resume.json）。"""
    return _session_dir(client, session_id) / "combat_resume.json"


def test_session_combat_suspend_resume_round_trip(client, session_id):
    start = client.post(f"/api/sessions/{session_id}/combat/start",
                        json={"encounter_id": SESSION_NODE_ID})
    assert start.status_code == 200, start.get_json()
    assert start.get_json().get("state"), "该节点无 approaches，应直接进战斗"

    live = client.get(f"/api/sessions/{session_id}/combat/state").get_json()
    assert not live["battle_over"]

    path = _session_resume_file(client, session_id)
    clear_resume(path)

    sus = client.post(f"/api/sessions/{session_id}/combat/suspend")
    assert sus.status_code == 200, sus.get_json()
    assert sus.get_json()["resume"]["encounter_id"] == SESSION_NODE_ID
    assert path.is_file()

    # 挂起后：内存态释放 + DTO 标记可恢复（会话界面据此给「继续战斗」入口）
    dto = next(s for s in client.get("/api/sessions").get_json() if s["id"] == session_id)
    assert dto["in_combat"] is False
    assert dto["combat_resumable"] is True
    assert dto["combat_resume"]["round_num"] == live["round_num"]
    assert client.get(f"/api/sessions/{session_id}/combat/state").status_code == 404

    res = client.post(f"/api/sessions/{session_id}/combat/resume")
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["resumed"] is True
    assert not path.is_file(), "恢复成功后存档应被消费掉"
    assert _diff(_norm(live), _norm(res.get_json()["state"]), "state") == []

    dto = next(s for s in client.get("/api/sessions").get_json() if s["id"] == session_id)
    assert dto["in_combat"] is True
    assert dto["combat_resume"] is None, "战斗回到内存后不应再有挂起摘要"


def test_discard_suspend_removes_session_entry(client, session_id):
    """挂起后「丢弃」走 DELETE /combat/suspend：存档清掉、入口消失。"""
    client.post(f"/api/sessions/{session_id}/combat/start",
                json={"encounter_id": SESSION_NODE_ID})
    path = _session_resume_file(client, session_id)
    clear_resume(path)

    assert client.post(f"/api/sessions/{session_id}/combat/suspend").status_code == 200
    assert path.is_file()

    discarded = client.delete(f"/api/sessions/{session_id}/combat/suspend")
    assert discarded.status_code == 200
    assert discarded.get_json()["removed"] is True
    assert not path.is_file()
    dto = next(s for s in client.get("/api/sessions").get_json() if s["id"] == session_id)
    assert dto["combat_resumable"] is False
    assert client.post(f"/api/sessions/{session_id}/combat/resume").status_code == 404


def test_abandon_leaves_no_resumable_entry(client, session_id):
    """放弃战斗 → 不留可恢复入口（否则「继续战斗」指向一场已作废的战斗）。

    注意 abandon 需要内存中仍有战斗（挂起后内存已释放，此时应走
    DELETE /combat/suspend，见上一个用例）。
    """
    client.post(f"/api/sessions/{session_id}/combat/start",
                json={"encounter_id": SESSION_NODE_ID})
    path = _session_resume_file(client, session_id)
    clear_resume(path)

    assert client.post(f"/api/sessions/{session_id}/combat/abandon").status_code == 200
    assert not path.is_file()
    dto = next(s for s in client.get("/api/sessions").get_json() if s["id"] == session_id)
    assert dto["in_combat"] is False
    assert dto["combat_resumable"] is False
    assert client.post(f"/api/sessions/{session_id}/combat/resume").status_code == 404


def test_suspend_without_combat_is_404(client, session_id):
    assert client.post(f"/api/sessions/{session_id}/combat/suspend").status_code == 404


# ── 删除会话的级联清理 ──

def test_delete_session_cascades_suspended_combat(client):
    """删除会话必须级联清掉挂起存档，否则「继续战斗」入口指向已死会话。

    回归点：`delete_session` 曾是「摘内存 + 删覆盖目录」，挂起存档只因恰好
    落在会话目录内而被 `rmtree` 顺带带走；一旦目录删除失败（占用/权限），
    存档就残留成孤儿入口。
    """
    res = client.post("/api/sessions", json={"mode": "free", "combat_mode": "tactical"})
    sid = res.get_json()["id"]
    client.post(f"/api/sessions/{sid}/characters/load", json={"character": "临光"})
    try:
        client.post(f"/api/sessions/{sid}/combat/start",
                    json={"encounter_id": SESSION_NODE_ID})
        assert client.post(f"/api/sessions/{sid}/combat/suspend").status_code == 200

        # 路径必须在删除前取好：会话一旦删掉就查不到目录了
        session_dir = _session_dir(client, sid)
        path = session_dir / "combat_resume.json"
        assert path.is_file(), "挂起后存档应落盘"

        deleted = client.delete(f"/api/sessions/{sid}")
        assert deleted.status_code == 200, deleted.get_json()

        assert not path.is_file(), "会话删除必须级联删除挂起战斗存档"
        assert not session_dir.exists(), "会话目录应随之清除"

        # 内存与入口都不应再提到这场战斗
        assert sid not in [s["id"] for s in client.get("/api/sessions").get_json()]
        listed = client.get("/api/combat/resumes").get_json()["sessions"]
        assert all(s["session_id"] != sid for s in listed), \
            "已删除会话不得残留在「继续战斗」列表里"
    finally:
        client.delete(f"/api/sessions/{sid}")


def test_delete_session_removes_resume_even_if_dir_survives(client, monkeypatch):
    """目录还在时，挂起存档也必须已被删除（不靠 `rmtree` 顺带带走）。

    这是本条 bug 的核心：旧实现把挂起存档的清理**隐式**寄托在「整个会话目录
    会被递归删掉」上。目录一旦因占用/权限没能删掉，存档就成了孤儿——前端
    「继续战斗」入口指向一个已不存在的会话。因此存档必须独立、先行删除。
    """
    from session_overlay import SessionOverlay

    res = client.post("/api/sessions", json={"mode": "free", "combat_mode": "tactical"})
    sid = res.get_json()["id"]
    client.post(f"/api/sessions/{sid}/characters/load", json={"character": "临光"})
    try:
        client.post(f"/api/sessions/{sid}/combat/start",
                    json={"encounter_id": SESSION_NODE_ID})
        assert client.post(f"/api/sessions/{sid}/combat/suspend").status_code == 200
        session_dir = _session_dir(client, sid)
        path = session_dir / "combat_resume.json"
        assert path.is_file()

        # 让目录删除无声失败（模拟被占用）：旧实现下存档这时会残留
        monkeypatch.setattr(SessionOverlay, "delete_session_overlays",
                            staticmethod(lambda *a, **k: None))
        client.delete(f"/api/sessions/{sid}")

        assert not path.is_file(), \
            "挂起存档必须独立删除，不能指望会话目录的 rmtree 顺带清掉"
    finally:
        monkeypatch.undo()
        client.delete(f"/api/sessions/{sid}")
        import shutil
        shutil.rmtree(_path_probe(sid), ignore_errors=True)


def _path_probe(sid: str) -> Path:
    """删除前没抓到目录时，按 id 在 free/story 下兜底定位（仅测试清理用）。"""
    root = ROOT / "data" / "memory" / "sessions"
    for mode in ("free", "story"):
        d = root / mode / sid
        if d.is_dir():
            return d
    return root / "_nonexistent_" / sid


def test_delete_session_releases_in_memory_combat(client):
    """会话战仍在内存（未挂起）时删除：内存战斗态必须被摘下并作废。

    `suspended` 标记不只是记账——它让阻塞在 `event_queue.get(timeout=30)`
    的 SSE 线程立刻退出，否则线程会攥着已删会话的战斗对象多活 30 秒。
    """
    res = client.post("/api/sessions", json={"mode": "free", "combat_mode": "tactical"})
    sid = res.get_json()["id"]
    client.post(f"/api/sessions/{sid}/characters/load", json={"character": "临光"})
    try:
        client.post(f"/api/sessions/{sid}/combat/start",
                    json={"encounter_id": SESSION_NODE_ID})
        # 取到内存中的战斗对象（删除后应已作废）
        live = _managers(client)["session"].get_session(sid)
        assert live is not None and live.combat is not None
        combat = live.combat

        assert client.delete(f"/api/sessions/{sid}").status_code == 200
        assert live.combat is None, "会话实例上的战斗引用应被摘下"
        assert getattr(combat, "suspended", False) is True, \
            "应置 suspended 以唤醒阻塞中的 SSE 线程"
    finally:
        client.delete(f"/api/sessions/{sid}")


def test_delete_session_failure_keeps_session_and_reports_error(client, monkeypatch):
    """目录清理失败时必须如实报错且**不**返回成功，会话保持可重试。

    事务性要求：宁可直接失败，也不能静默留下残留数据（半删比不删更难排查）。
    """
    from session_overlay import SessionOverlay

    res = client.post("/api/sessions", json={"mode": "free", "combat_mode": "tactical"})
    sid = res.get_json()["id"]
    client.post(f"/api/sessions/{sid}/characters/load", json={"character": "临光"})
    try:
        client.post(f"/api/sessions/{sid}/combat/start",
                    json={"encounter_id": SESSION_NODE_ID})
        client.post(f"/api/sessions/{sid}/combat/suspend")
        path = _session_resume_file(client, sid)
        assert path.is_file()

        def _boom(session_id, mode="free"):
            raise OSError("模拟目录被占用")

        monkeypatch.setattr(SessionOverlay, "delete_session_overlays",
                            staticmethod(_boom))
        failed = client.delete(f"/api/sessions/{sid}")
        assert failed.status_code == 500, "清理失败不得谎报成功"
        assert sid in [s["id"] for s in client.get("/api/sessions").get_json()], \
            "失败后会话应保留，供用户重试"

        # 战斗存档是先一步清掉的：即便目录删不掉，也不该留一个指向死会话的入口
        assert not path.is_file(), "存档应在目录清理之前就删除"

        monkeypatch.undo()
        assert client.delete(f"/api/sessions/{sid}").status_code == 200, "重试应成功"
    finally:
        monkeypatch.undo()
        client.delete(f"/api/sessions/{sid}")


def test_delete_session_rejects_bogus_mode_without_touching_disk(client):
    """`session.mode` 被写坏时必须拒绝删除，既不越界删目录也不假装删成功。

    `mode` 会参与拼接磁盘路径，非法值可能让 `rmtree` 打到 `sessions/` 之外；
    同时也不能当作「没有目录要删」放行 —— 那会丢一个其实还在盘上的会话。
    """
    from session_manager import SessionCleanupError

    res = client.post("/api/sessions", json={"mode": "free", "combat_mode": "tactical"})
    sid = res.get_json()["id"]
    try:
        session_dir = _session_dir(client, sid)
        live = _managers(client)["session"].get_session(sid)
        live.mode = "../../etc"  # 制造越界 mode

        with pytest.raises(SessionCleanupError):
            _managers(client)["session"].delete_session(sid)

        assert session_dir.exists(), "非法 mode 下不得删除任何目录"
        assert _managers(client)["session"].get_session(sid) is not None, \
            "拒绝删除时会话必须保留"
    finally:
        live = _managers(client)["session"].get_session(sid)
        if live:
            live.mode = "free"
        client.delete(f"/api/sessions/{sid}")


def test_delete_session_twice_is_404(client):
    res = client.post("/api/sessions", json={"mode": "free", "combat_mode": "tactical"})
    sid = res.get_json()["id"]
    assert client.delete(f"/api/sessions/{sid}").status_code == 200
    assert client.delete(f"/api/sessions/{sid}").status_code == 404


# ── 存档摘要（前端入口展示用）──

def test_summarize_handles_missing_and_partial_payload():
    # 空载荷视为「无存档」：调用方（list_test_resumes / 会话 DTO）据此跳过入口
    assert summarize(None) is None
    assert summarize({}) is None

    # 部分载荷：缺的字段补零，不能让前端入口崩在 undefined 上
    assert summarize({"encounter_id": "enc_x"}) == {
        "encounter_id": "enc_x", "suspended_at": None, "round_num": 0, "phase": "",
        "battle_over": False, "player_alive": 0, "hand_size": 0, "pending_waves": 0,
    }

    info = summarize({
        "encounter_id": "enc_x",
        "engine": {
            "state": {"round_num": 4, "phase": "END"},
            "units": {"a": {"team": "player", "is_alive": True},
                      "b": {"team": "player", "is_alive": False},
                      "c": {"team": "enemy", "is_alive": True}},
            "shared_pool": {"hand": [1, 2, 3]},
            "pending_waves": [{"enemies": []}],
        },
    })
    assert info["round_num"] == 4
    assert info["battle_over"] is True
    assert info["player_alive"] == 1
    assert info["hand_size"] == 3
    assert info["pending_waves"] == 1


def test_read_resume_tolerates_corrupt_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert read_resume(bad) is None, "损坏存档不应让恢复流程抛错"


def test_session_resume_path_lives_in_session_dir(client, session_id):
    dto = next(s for s in client.get("/api/sessions").get_json() if s["id"] == session_id)
    path = _session_resume_file(client, session_id)
    assert path.name == "combat_resume.json"
    assert path.parent == Path(dto["backgrounds_dir"]).parent
