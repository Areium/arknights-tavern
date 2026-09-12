# -*- coding: utf-8 -*-
"""剧情分支（LLM 生成 + 作者预设）与节点状态记录/回档的后端验证。

覆盖：
  目标一（LLM 生成未来分支 + 自由进入）
    - 作者手写「玩家选项方向」解析为结构化分支；
    - LLM 分支规范化：target_beat_id 必须真实存在，编造的丢弃；
    - 分支落点：advance_beat 命中 pending_branch 时跳转到目标节拍。

  目标二（状态显示 / 逐节点记录 / 回档）
    - build_story_state：当前位置（章节/节拍/路线图状态）；
    - record_node_snapshot：每个经历过的节点记录角色/任务/环境状态；
    - restore_from_snapshot：回档到关键节点并恢复该节点时的全部状态；
    - 恢复的会话（未走 init_session_docs）惰性加载剧情结构后依然可用。

只写临时会话目录（monkeypatch _SESSIONS_DIR），不触碰真实 data/memory/。
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import session_overlay as so  # noqa: E402
from session_overlay import SessionOverlay  # noqa: E402
from SceneManager import _normalize_branches_field  # noqa: E402

PLOT_ID = "fengxue_guojing"


@pytest.fixture()
def overlay(tmp_path, monkeypatch):
    """全新会话（走 init_session_docs，等价于创建时）。"""
    monkeypatch.setattr(so, "_SESSIONS_DIR", tmp_path / "sessions")
    ov = SessionOverlay("sess_test_branches", "story")
    ov.load_quests_from_plot(PLOT_ID)
    ov.init_session_docs(PLOT_ID)
    return ov


# ── 目标一：分支 ──

def test_author_branches_parsed(overlay):
    """剧情文件里手写的「玩家选项方向」被解析为结构化作者分支。"""
    chapters = overlay._ensure_narrative_beats()
    assert len(chapters) >= 6, "风雪过境应有 >= 6 章"

    authored = overlay.get_authored_branches()
    assert authored, "当前章节应有作者手写分支"
    assert all(b["source"] == "author" for b in authored)
    labels = [b["label"] for b in authored]
    assert any("银灰" in lb for lb in labels), f"应含试探银灰的选项，实际 {labels}"
    assert any(b.get("intent") for b in authored), "括号里的方向标签应被提取为 intent"

    # 发现路径也应被解析（供分支上下文参考）
    first_beat = chapters[0]["beats"][0]
    assert first_beat["discovery_paths"], "发现路径应被解析"


def test_llm_branches_target_validated():
    """LLM 给的 target_beat_id 必须真实存在，编造的目标被清空。"""
    valid = ["beat_arrival", "beat_intro_tension", "beat_convoy_fight"]
    raw = [
        {"label": "接受银灰的邀请", "intent": "中立", "target_beat_id": "beat_intro_tension"},
        {"label": "编造一个目标", "target_beat_id": "beat_not_exist"},
        "裸字符串选项",
        {"label": "   "},  # 空标签丢弃
    ]
    out = _normalize_branches_field(raw, valid)
    assert [b["label"] for b in out] == ["接受银灰的邀请", "编造一个目标", "裸字符串选项"]
    assert out[0]["target_beat_id"] == "beat_intro_tension"
    assert out[0]["source"] == "llm"
    assert out[1]["target_beat_id"] is None, "编造的节拍 id 必须被丢弃"


def test_pending_branch_jump(overlay):
    """玩家选择带 target_beat_id 的分支后，advance_beat 跳转到该节拍。"""
    assert overlay.get_current_beat()["id"] == "beat_arrival"

    overlay.set_pending_branch({
        "label": "走向山道", "intent": "推进", "target_beat_id": "beat_convoy_fight",
    })
    assert overlay.get_pending_branch() is not None

    overlay.advance_beat()  # 命中 pending_branch → 跳转，而非顺序推进到 intro_tension
    assert overlay.get_current_beat()["id"] == "beat_convoy_fight"
    assert overlay.get_pending_branch() is None, "落点生效后应清除"
    # 跳过的节拍不标记完成（时间旅行语义：只记真正经历过的）
    assert "beat_intro_tension" not in overlay.get_beat_state()["completed_beats"]


def test_pending_branch_invalid_target_falls_back(overlay):
    """pending_branch 指向不存在的节拍时，退化为顺序推进。"""
    overlay.set_pending_branch({"label": "x", "target_beat_id": "beat_ghost"})
    overlay.advance_beat()
    assert overlay.get_current_beat()["id"] == "beat_intro_tension"


# ── 目标二：状态展示 / 记录 / 回档 ──

def test_story_state_shows_position(overlay):
    """状态展示：当前位置在节点结构中的章节/节拍 + 路线图状态。"""
    st = overlay.build_story_state()
    assert st["has_plot"] is True
    assert st["chapter"]["idx"] == 0
    assert st["beat"]["id"] == "beat_arrival"
    assert st["beat"]["total"] == len(overlay._ensure_narrative_beats()[0]["beats"])

    roads = st["roads"]
    assert len(roads) == len(overlay._ensure_narrative_beats())
    assert roads[0]["state"] == "current"
    assert roads[1]["state"] == "locked"
    assert roads[0]["beats"][0]["state"] == "current"
    assert roads[0]["beats"][1]["state"] == "locked"


def test_node_snapshot_records_state(overlay):
    """逐节点记录：每个经历过的节点记录当时的角色/任务状态。"""
    overlay.advance_beat()  # 完成 beat_arrival
    overlay.add_condition("银灰", {"name": "轻伤", "modifier": -1, "applies_to": "all"})
    overlay.set_quest_state("q_probe", "active")
    snap = overlay.record_node_snapshot(round_num=2)

    assert snap is not None
    assert snap["node_id"] == "beat_arrival"
    assert snap["round_start"] == 1 and snap["round_end"] == 2
    assert snap["character_states"]["银灰"]["conditions"][0]["name"] == "轻伤"
    assert snap["quest_states"]["q_probe"]["status"] == "active"
    assert snap["chapter_title"]

    history = overlay.get_node_history()
    assert [n["node_id"] for n in history] == ["beat_arrival"]
    assert st_round_range(history[0]) == (1, 2)


def test_rollback_restores_node_state(overlay):
    """回档：返回此前经历过的关键节点，并恢复到该节点时的状态。"""
    # 节点 1：beat_arrival —— 银灰轻伤、任务 q_probe 激活
    overlay.advance_beat()
    overlay.add_condition("银灰", {"name": "轻伤", "modifier": -1, "applies_to": "all"})
    overlay.set_quest_state("q_probe", "active")
    overlay.record_node_snapshot(round_num=2)

    # 节点 2：beat_intro_tension —— 银灰重伤、任务 q_probe 完成
    overlay.advance_beat()
    overlay.add_condition("银灰", {"name": "重伤", "modifier": -3, "applies_to": "all"})
    overlay.set_quest_state("q_probe", "completed")
    overlay.record_node_snapshot(round_num=4)

    assert overlay.get_current_beat()["id"] == "beat_convoy_fight"
    assert len(overlay.get_character_state("银灰")["conditions"]) == 2

    # 回档到 beat_arrival
    result = overlay.restore_from_snapshot("beat_arrival")

    assert result["node_id"] == "beat_arrival"
    assert result["round_end"] == 2
    assert overlay.get_current_beat()["id"] == "beat_arrival"
    assert overlay.get_beat_state()["completed_beats"] == ["beat_arrival"]
    assert overlay._data["narration_round"] == 2
    # 状态回到该节点：只有轻伤，没有后来才有的重伤
    conds = [c["name"] for c in overlay.get_character_state("银灰")["conditions"]]
    assert conds == ["轻伤"], conds
    assert overlay.get_quest_states()["q_probe"]["status"] == "active"


def test_rollback_unknown_node_raises(overlay):
    overlay.advance_beat()
    overlay.record_node_snapshot(round_num=1)
    with pytest.raises(ValueError):
        overlay.restore_from_snapshot("beat_never_visited")


def test_restored_session_lazily_loads_beats(tmp_path, monkeypatch):
    """恢复的会话（未走 init_session_docs）惰性加载剧情结构，状态展示仍可用。"""
    monkeypatch.setattr(so, "_SESSIONS_DIR", tmp_path / "sessions")
    ov = SessionOverlay("sess_restored", "story")
    ov._data["plot_id"] = PLOT_ID
    ov._data["beat_state"] = {
        "chapter_idx": 0, "beat_idx": 1,
        "completed_beats": ["beat_arrival"], "narrations_on_beat": 0,
    }
    ov._save()

    # 新对象：磁盘上只有数据，内存里没有 _narrative_beats（模拟服务重启）
    restored = SessionOverlay("sess_restored", "story")
    assert not hasattr(restored, "_narrative_beats")

    st = restored.build_story_state()
    assert st["has_plot"] is True
    assert st["beat"]["id"] == "beat_intro_tension"
    assert st["roads"][0]["beats"][0]["state"] == "done"
    assert restored.get_authored_branches(), "恢复会话也应能读到作者分支"


def st_round_range(node):
    return (node["round_start"], node["round_end"])


# ── HTTP 层：真实 Flask 应用 + 隔离的临时会话目录 ──

def test_story_api_endpoints(tmp_path, monkeypatch):
    """GET /story-state 与 POST /rollback-node 的端到端契约（不触碰真实存档）。"""
    import session_manager as sm_mod

    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(so, "_SESSIONS_DIR", sessions_root)
    monkeypatch.setattr(sm_mod, "_SESSIONS_DIR", sessions_root)

    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    # 1) 通过真实 API 创建剧情会话
    res = client.post("/api/sessions", json={
        "mode": "story", "plot_id": PLOT_ID, "name": "回档验证",
    })
    assert res.status_code == 201, res.get_json()
    sid = res.get_json()["id"]

    # 2) 状态展示：当前位置在节点结构中
    st = client.get(f"/api/sessions/{sid}/story-state").get_json()
    assert st["has_plot"] is True
    assert st["chapter"]["idx"] == 0
    assert st["beat"]["id"] == "beat_arrival"
    assert len(st["roads"]) >= 6
    assert st["roads"][0]["state"] == "current"

    # 3) 直接驱动 overlay 产生两个节点快照（绕过 LLM，只验证记录/回档链路）
    session = app._managers["session"].get_session(sid)
    ov = session.overlay
    ov.advance_beat()
    ov.add_condition("银灰", {"name": "轻伤", "modifier": -1, "applies_to": "all"})
    ov.record_node_snapshot(round_num=2)
    ov.advance_beat()
    ov.add_condition("银灰", {"name": "重伤", "modifier": -3, "applies_to": "all"})
    ov.record_node_snapshot(round_num=4)

    st2 = client.get(f"/api/sessions/{sid}/story-state").get_json()
    assert st2["beat"]["id"] == "beat_convoy_fight"
    assert [n["node_id"] for n in st2["node_history"]] == ["beat_arrival", "beat_intro_tension"]
    assert st2["roads"][0]["beats"][0]["state"] == "done"

    # 4) 回档到关键节点并恢复状态
    res = client.post(f"/api/sessions/{sid}/rollback-node", json={"node_id": "beat_arrival"})
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["node_id"] == "beat_arrival"
    assert body["round_range"] == [1, 2]
    assert body["story_state"]["beat"]["id"] == "beat_arrival"
    conds = [c["name"] for c in ov.get_character_state("银灰")["conditions"]]
    assert conds == ["轻伤"], conds

    # 5) 错误路径
    assert client.post(f"/api/sessions/{sid}/rollback-node",
                       json={"node_id": "beat_ghost"}).status_code == 400
    assert client.post(f"/api/sessions/{sid}/rollback-node", json={}).status_code == 400
    assert client.get("/api/sessions/sess_not_exist/story-state").status_code == 404

    app._managers["session"].delete_session(sid)

