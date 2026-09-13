# -*- coding: utf-8 -*-
"""动态剧情树（LLM 真正生成新节点）的后端验证。

覆盖本轮升级要求：
  - 节点是 LLM 现场生成的「新节点」（标题/概要/内容/分支都来自 LLM 输出），
    而不是从作者节拍骨架里挑一个落点；
  - 玩家选择分支会生成/复用子节点，于是结构可分叉、可多层展开（树状）；
  - 目标二（位置显示 / 逐节点状态记录 / 回档）在树上依然成立：
    树上回档返回此前经历过的关键节点并恢复其状态，且树保留（其它分支仍可走）。

只写临时会话目录（monkeypatch _SESSIONS_DIR），不触碰真实 data/memory/。
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import session_overlay as so  # noqa: E402
from session_overlay import SessionOverlay  # noqa: E402

PLOT_ID = "fengxue_guojing"


@pytest.fixture()
def overlay(tmp_path, monkeypatch):
    """全新剧情会话（走 init_session_docs，等价于创建时）。"""
    monkeypatch.setattr(so, "_SESSIONS_DIR", tmp_path / "sessions")
    ov = SessionOverlay("sess_test_tree", "story")
    ov.load_quests_from_plot(PLOT_ID)
    ov.init_session_docs(PLOT_ID)
    return ov


# ── 树的建立：根节点来自剧情入口，其余节点由 LLM 生成 ──

def test_tree_seeded_from_plot_opening(overlay):
    """会话创建即建好树：根节点（入口）来自剧情开场，尚无状态。"""
    tree = overlay.get_story_tree()
    assert tree["root_id"] == "n_root"
    assert tree["current_id"] == "n_root"
    root = tree["nodes"]["n_root"]
    assert root["parent_id"] is None
    assert root["depth"] == 0
    assert root["state"] is None, "尚未发生叙述，根节点不应有状态快照"
    assert root["content"], "根节点内容应来自剧情入口（开场）"


def test_first_turn_fills_root_with_llm_content(overlay):
    """首轮叙述填充根节点：标题/概要/内容/分支均取自 LLM 输出。"""
    node = overlay.commit_tree_step(
        narrative="雪原上，风把旗子吹得笔直，远处传来引擎声。",
        summary="抵达雪原",
        title="雪原初抵",
        branches=[{"label": "走向山道", "intent": "推进"}],
        branch=None, round_num=1,
    )
    assert node["id"] == "n_root"
    assert node["title"] == "雪原初抵"
    assert node["summary"] == "抵达雪原"
    assert node["content"] == "雪原上，风把旗子吹得笔直，远处传来引擎声。"
    assert node["state"]["round_end"] == 1
    # 分支已预算出各自的子节点 id（下一层的入口）
    assert node["branches"][0]["label"] == "走向山道"
    assert node["branches"][0]["child_id"].startswith("n_")


def test_branch_creates_new_llm_generated_node(overlay):
    """选择分支 → 生成一个由 LLM 现场内容填充的**新节点**（非既有节拍）。"""
    overlay.commit_tree_step(
        narrative="开场叙述", summary="开场", title="序章",
        branches=[{"label": "去酒馆"}], round_num=1,
    )
    # 叙述文本刻意用节拍骨架里不可能出现的标记，证明节点内容是 LLM 新生成的
    node = overlay.commit_tree_step(
        narrative="LLM 现场生成的酒馆场景叙述 XYZQ",
        summary="在酒馆密谈",
        title="酒馆密谈",
        branches=[{"label": "追问情报"}, {"label": "离开"}],
        branch={"label": "去酒馆", "intent": "社交"},
        round_num=2,
    )
    tree = overlay.get_story_tree()
    assert node["id"] != "n_root"
    assert tree["current_id"] == node["id"]
    assert node["parent_id"] == "n_root"
    assert node["depth"] == 1
    assert node["title"] == "酒馆密谈"
    assert node["intent"] == "社交"
    assert node["branch_label"] == "去酒馆"
    assert "XYZQ" in node["content"], "节点内容应来自本轮 LLM 叙述"

    # 结构确为树：父节点 children 含该子节点
    root = tree["nodes"]["n_root"]
    assert node["id"] in root["children"]
    # 该新节点自身又带下一层分支（可继续展开）
    assert {b["label"] for b in node["branches"]} == {"追问情报", "离开"}
    assert all(b["child_id"] for b in node["branches"])


def test_tree_forks_and_expands_multiple_layers(overlay):
    """树可分叉、可多层：root→A→A1 与 root→B 共存。"""
    overlay.commit_tree_step(
        narrative="n0", title="根", branches=[{"label": "A"}, {"label": "B"}], round_num=1,
    )
    a = overlay.commit_tree_step(
        narrative="na", title="A节点", branches=[{"label": "A1"}],
        branch={"label": "A"}, round_num=2,
    )
    a1 = overlay.commit_tree_step(
        narrative="na1", title="A1节点", branches=[],
        branch={"label": "A1"}, round_num=3,
    )
    # 回到根节点，再走另一条分支 B（树上回档后仍可走其它分支）
    overlay.rollback_to_tree_node("n_root")
    b = overlay.commit_tree_step(
        narrative="nb", title="B节点", branches=[],
        branch={"label": "B"}, round_num=4,
    )

    nodes = overlay.get_story_tree()["nodes"]
    root = nodes["n_root"]
    assert len(nodes) == 4, "应为 根/A/A1/B 四个节点"
    assert set(root["children"]) == {a["id"], b["id"]}, "根节点应有两个子节点（分叉）"
    assert a["parent_id"] == "n_root" and a["depth"] == 1
    assert b["parent_id"] == "n_root" and b["depth"] == 1
    assert a1["parent_id"] == a["id"] and a1["depth"] == 2, "A 下应再展开一层"


def test_repeat_same_branch_reuses_node(overlay):
    """同一父节点下重复走同一分支 → 复用同一子节点（树不无限膨胀）。"""
    overlay.commit_tree_step(
        narrative="n0", title="根", branches=[{"label": "A"}], round_num=1,
    )
    first = overlay.commit_tree_step(
        narrative="na", title="A节点", branch={"label": "A"}, round_num=2,
    )
    # 回档到根，再走同一分支
    overlay.rollback_to_tree_node("n_root")
    second = overlay.commit_tree_step(
        narrative="na2", title="A节点再访", branch={"label": "A"}, round_num=3,
    )
    assert first["id"] == second["id"], "同父同标签应命中同一确定性子节点 id"
    assert len(overlay.get_story_tree()["nodes"]) == 2


# ── 目标二在树上成立：状态显示 / 记录 / 回档 ──

def test_rollback_on_tree_restores_node_state(overlay):
    """树上回档：返回此前经历过的关键节点，并恢复该节点时的状态。"""
    # 节点 1（根）：银灰轻伤
    overlay.add_condition("银灰", {"name": "轻伤", "modifier": -1, "applies_to": "all"})
    overlay.commit_tree_step(
        narrative="n0", title="根", branches=[{"label": "A"}], round_num=1,
    )
    # 节点 2：银灰重伤 + 任务激活
    overlay.add_condition("银灰", {"name": "重伤", "modifier": -3, "applies_to": "all"})
    overlay.set_quest_state("q_probe", "active")
    a = overlay.commit_tree_step(
        narrative="na", title="A节点", branch={"label": "A"}, round_num=2,
    )
    assert len(overlay.get_character_state("银灰")["conditions"]) == 2

    # 回档到根节点
    res = overlay.rollback_to_tree_node("n_root")
    assert res["node_id"] == "n_root"
    assert res["depth"] == 0
    assert overlay.get_story_tree()["current_id"] == "n_root"
    conds = [c["name"] for c in overlay.get_character_state("银灰")["conditions"]]
    assert conds == ["轻伤"], conds
    assert overlay.get_quest_states().get("q_probe", {}).get("status") is None

    # 树保留：A 节点仍在，可再次进入
    tree = overlay.get_story_tree()
    assert a["id"] in tree["nodes"]


def test_story_state_includes_tree_and_history(overlay):
    """状态展示：build_story_state 输出树结构 + 回档点列表（节点历史）。"""
    overlay.commit_tree_step(
        narrative="n0", title="根", branches=[{"label": "A"}], round_num=1,
    )
    overlay.commit_tree_step(
        narrative="na", title="A节点", branch={"label": "A"}, round_num=2,
    )
    st = overlay.build_story_state()
    tree = st["tree"]
    assert tree["has_tree"] is True
    assert tree["current_id"] != tree["root_id"]
    assert len(tree["nodes"]) == 2
    depths = {n["title"]: n["depth"] for n in tree["nodes"]}
    assert depths["根"] == 0 and depths["A节点"] == 1
    # 每个节点带状态与父子信息
    cur = tree["current_node"]
    assert cur["id"] == tree["current_id"]
    assert cur["has_state"] is True
    # node_history 导出为可回档点
    assert {n["node_id"] for n in st["node_history"]} == {"n_root", tree["current_id"]}


def test_branch_context_grounded_in_current_node(overlay):
    """分支上下文以「当前树节点」为根（含标题/来路），并要求生成新节点。"""
    overlay.commit_tree_step(
        narrative="n0", title="根", branches=[{"label": "A"}], round_num=1,
    )
    overlay.commit_tree_step(
        narrative="na", title="酒馆密谈", branch={"label": "A"}, round_num=2,
    )
    ctx = overlay.build_branch_context()
    assert "<current_node>" in ctx
    assert "酒馆密谈" in ctx
    assert "已走路径" in ctx
    assert "新的剧情节点" in ctx, "上下文应要求 LLM 生成新节点而非挑选既有节拍"


def test_tree_node_id_is_deterministic():
    """子节点 id 由（父节点, 分支标签）确定性派生。"""
    ov = SessionOverlay.__new__(SessionOverlay)
    a = SessionOverlay._tree_node_id(ov, "n_root", "去酒馆")
    b = SessionOverlay._tree_node_id(ov, "n_root", "去酒馆")
    c = SessionOverlay._tree_node_id(ov, "n_root", "离开")
    assert a == b and a != c
    assert a.startswith("n_") and len(a) == 12


def test_rollback_unknown_tree_node_raises(overlay):
    with pytest.raises(ValueError):
        overlay.rollback_to_tree_node("n_ghost")


# ── HTTP 端到端：脚本化 LLM，验证叙述链路真的在长树 ──

def test_tree_grows_via_http_narrate(tmp_path, monkeypatch):
    """真实 Flask 应用 + 脚本化 LLM：narrate-continue 每轮把 LLM 生成内容落成树节点。"""
    import session_manager as sm_mod

    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(so, "_SESSIONS_DIR", sessions_root)
    monkeypatch.setattr(sm_mod, "_SESSIONS_DIR", sessions_root)

    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    # LLM 后端配置（不联网，只提供配置字典）
    app._managers["llm_backend"].get_config = lambda: {
        "auto_generate_choices": True, "choice_count": 2, "word_limit": 300,
        "dialogue_bubble_mode": False, "narration_reasoning_effort": "none",
        "max_output_tokens": 4096, "memory_interval": 5,
    }

    res = client.post("/api/sessions", json={
        "mode": "story", "plot_id": PLOT_ID, "name": "树验证",
    })
    assert res.status_code == 201, res.get_json()
    sid = res.get_json()["id"]

    session = app._managers["session"].get_session(sid)
    session._llm = object()  # 令 _require_usable 通过（不实际调用后端）
    sm = session.scene_manager

    # —— 第 1 轮：LLM 生成开场，给出分支「去酒馆」——
    sm.narrate = lambda *a, **k: (
        "LLM 开场叙述 ALPHA，风雪中一行人抵达关口。", {}, None,
    )
    sm.extract_markers = lambda *a, **k: {
        "beat_complete": False, "combat": None,
        "choices": ["去酒馆", "原地等待"],
        "branches": [
            {"label": "去酒馆", "intent": "社交", "target_beat_id": None},
            {"label": "原地等待", "intent": "中立", "target_beat_id": None},
        ],
        "node_title": "关口初抵", "summary": "抵达关口", "environment": None,
        "usage": None, "error": None,
    }
    r1 = client.post(f"/api/sessions/{sid}/narrate-continue", json={"action": ""})
    assert r1.status_code == 200, r1.get_json()
    tree1 = session.overlay.get_story_tree()
    assert len(tree1["nodes"]) == 1, "第 1 轮只填充根节点"
    root = tree1["nodes"]["n_root"]
    assert root["title"] == "关口初抵"
    assert "ALPHA" in root["content"]

    emitted = session.overlay.get_emitted_branches()
    branch = next(b for b in emitted if b["label"] == "去酒馆")

    # —— 第 2 轮：选择「去酒馆」→ 生成一个新的酒馆节点 ——
    sm.narrate = lambda *a, **k: (
        "LLM 酒馆场景 BRAVO，烛火摇曳，情报贩子低声开口。", {}, None,
    )
    sm.extract_markers = lambda *a, **k: {
        "beat_complete": False, "combat": None,
        "choices": ["追问情报"],
        "branches": [{"label": "追问情报", "intent": "情报", "target_beat_id": None}],
        "node_title": "酒馆密谈", "summary": "与情报贩子交谈", "environment": None,
        "usage": None, "error": None,
    }
    r2 = client.post(f"/api/sessions/{sid}/narrate-continue",
                     json={"action": "去酒馆", "branch_id": branch["id"]})
    assert r2.status_code == 200, r2.get_json()

    tree2 = session.overlay.get_story_tree()
    assert len(tree2["nodes"]) == 2, "第 2 轮应生成一个新子节点"
    cur_id = tree2["current_id"]
    assert cur_id != "n_root"
    child = tree2["nodes"][cur_id]
    assert child["parent_id"] == "n_root" and child["depth"] == 1
    assert child["title"] == "酒馆密谈"
    assert "BRAVO" in child["content"], "子节点内容应来自本轮 LLM 叙述"
    assert cur_id in tree2["nodes"]["n_root"]["children"]

    # —— 状态展示：树 + 回档点 ——
    st = client.get(f"/api/sessions/{sid}/story-state").get_json()
    assert st["tree"]["has_tree"] is True
    assert st["tree"]["current_id"] == cur_id
    assert len(st["tree"]["nodes"]) == 2

    # —— 树上回档：回到根节点，恢复其状态，树保留 ——
    r3 = client.post(f"/api/sessions/{sid}/rollback-node", json={"node_id": "n_root"})
    assert r3.status_code == 200, r3.get_json()
    body = r3.get_json()
    assert body["node_id"] == "n_root"
    assert body["story_state"]["tree"]["current_id"] == "n_root"
    assert cur_id in session.overlay.get_story_tree()["nodes"], "回档后子节点应保留"

    # 错误路径
    assert client.post(f"/api/sessions/{sid}/rollback-node",
                       json={"node_id": "n_ghost"}).status_code == 400

    app._managers["session"].delete_session(sid)
