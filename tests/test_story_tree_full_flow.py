# -*- coding: utf-8 -*-
"""完整剧情流程下的动态剧情树验证（脚本化 LLM，确定性）。

与 test_story_tree_nodes.py 的区别：那边以单步驱动 commit_tree_step 为主；
本文件把真实 Flask 应用 + narrate-continue 全链路串成一次「从开场到分叉、
回档、再重走」的完整剧情流程，逐步校验：

  1. 首轮：根节点被 LLM 输出填充（标题/概要/内容/分支）；
  2. 未来节点推进：同一节点内多轮继续，内容与轮次区间推进、不新建节点；
     同节点继续会以本轮分支**整体替换**上一轮分支（节点分支 = 最新选项集）；
  3. 分支节点：玩家选择分支后，父节点下生成由 LLM 内容填充的新子节点；
  4. 多层展开：子节点下再选分支 → 孙节点（depth 2）；
  5. 树分叉：回档到根节点后走另一分支 → 根节点下两个子节点共存；
  6. 复访复用：回档后重走同一分支 → 命中同一确定性子节点，树不膨胀；
  7. 提取降级轮：Call 2 空响应（degraded）时流程不断、节点仍推进；
  8. /story-state 契约：树视图 / 当前路径 / 回档点列表完整。

行为口径说明：树节点上的 branches 是「本轮 LLM 内联分支 + 作者预设分支」
的合并集（_build_branches 合并后随 commit_tree_step 入库），因此对节点分支
的断言用「包含本轮 LLM 分支」的语义，而非精确集合相等。

叙述文本使用节拍骨架中不可能出现的哨兵词（SENTINEL_*），
证明节点内容确实来自本轮 LLM 输出而非作者节拍。只写临时会话目录。
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import session_overlay as so  # noqa: E402
import session_manager as sm_mod  # noqa: E402

PLOT_ID = "fengxue_guojing"


@pytest.fixture()
def flow(tmp_path, monkeypatch):
    """真实 Flask 应用 + 脚本化 LLM 的完整剧情流程台座。"""
    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(so, "_SESSIONS_DIR", sessions_root)
    monkeypatch.setattr(sm_mod, "_SESSIONS_DIR", sessions_root)

    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    # LLM 后端配置（不联网）：关闭回忆生成，其余与真实配置口径一致
    app._managers["llm_backend"].get_config = lambda: {
        "auto_generate_choices": True, "choice_count": 2, "word_limit": 300,
        "dialogue_bubble_mode": False, "narration_reasoning_effort": "none",
        "max_output_tokens": 4096, "memory_interval": 999,
    }

    res = client.post("/api/sessions", json={
        "mode": "story", "plot_id": PLOT_ID, "name": "完整流程验证",
    })
    assert res.status_code == 201, res.get_json()
    sid = res.get_json()["id"]

    session = app._managers["session"].get_session(sid)
    session._llm = object()  # 令 _require_usable 通过（叙述由脚本接管）

    def script_round(narrative, *, title, summary, branches, env=None):
        """把下一轮的 LLM 行为脚本化（narrate 产出 + Call 2 提取结果）。"""
        sm = session.scene_manager
        sm.narrate = lambda *a, **k: (narrative, {}, None)
        sm.extract_markers = lambda *a, **k: {
            "beat_complete": False, "combat": None,
            "choices": [b["label"] for b in branches],
            "branches": [dict(b, target_beat_id=None) for b in branches],
            "node_title": title, "summary": summary, "environment": env,
            "usage": None, "error": None,
        }

    def play(action="", branch_id=None):
        payload = {"action": action}
        if branch_id:
            payload["branch_id"] = branch_id
        r = client.post(f"/api/sessions/{sid}/narrate-continue", json=payload)
        assert r.status_code == 200, r.get_json()
        return r.get_json()

    def emitted_labels():
        return [b["label"] for b in session.overlay.get_emitted_branches()]

    yield {
        "client": client, "sid": sid, "session": session,
        "script_round": script_round, "play": play,
        "emitted_labels": emitted_labels,
    }

    app._managers["session"].delete_session(sid)


def test_complete_story_flow_grows_future_and_branch_nodes(flow):
    """完整剧情流程：根 → 同节点推进 → 分支 → 多层 → 回档分叉 → 复访复用。"""
    client, sid, session = flow["client"], flow["sid"], flow["session"]
    script_round, play = flow["script_round"], flow["play"]
    emitted_labels = flow["emitted_labels"]
    tree = lambda: session.overlay.get_story_tree()

    # ── R1 首轮：根节点被 LLM 输出填充 ──
    script_round(
        "SENTINEL_R1 风雪初歇，山道尽头的会客厅里炭火正旺，银灰起身相迎。",
        title="会客厅初见", summary="博士抵达喀兰贸易会客厅",
        branches=[{"label": "追问铁路细节", "intent": "情报"},
                  {"label": "独自外出侦查", "intent": "侦查"}],
        env={"location": "喀兰贸易会客厅", "time": "上午"},
    )
    r1 = play()
    t = tree()
    assert list(t["nodes"]) == ["n_root"], "第 1 轮只填充根节点，不新建"
    root = t["nodes"]["n_root"]
    assert root["title"] == "会客厅初见"
    assert "SENTINEL_R1" in root["content"], "根节点内容应来自本轮 LLM 叙述"
    assert root["state"]["round_end"] == 1
    labels1 = {b["label"] for b in root["branches"]}
    assert {"追问铁路细节", "独自外出侦查"} <= labels1, \
        "节点分支应包含本轮 LLM 给出的分支（另有作者预设合并入内）"
    assert all(b["child_id"] for b in root["branches"]), "分支应预算出子节点 id"

    # ── R2 同节点内继续：未来内容推进，不新建节点；分支集被本轮替换 ──
    script_round(
        "SENTINEL_R2 银灰把一份铁路图纸推到博士面前，烛光在图纸上游移。",
        title="会客厅初见", summary="银灰抛出铁路计划",
        branches=[{"label": "质疑资金链", "intent": "冲突"},
                  {"label": "沉默观察", "intent": "中立"}],
    )
    r2 = play()
    t = tree()
    assert list(t["nodes"]) == ["n_root"], "同节点继续不应新建节点"
    root = t["nodes"]["n_root"]
    assert "SENTINEL_R2" in root["content"] and "SENTINEL_R1" not in root["content"]
    assert root["state"]["round_start"] == 1 and root["state"]["round_end"] == 2, \
        "同节点多轮推进应累积轮次区间"
    labels2 = {b["label"] for b in root["branches"]}
    assert {"质疑资金链", "沉默观察"} <= labels2, "节点分支应随本轮 LLM 输出更新"
    assert {"追问铁路细节", "独自外出侦查"}.isdisjoint(labels2), \
        "同节点继续会以本轮分支替换上一轮分支（最新选项集语义）"

    # ── R3 选择分支「质疑资金链」→ 生成分支节点（depth 1）──
    b_r3 = next(b for b in r2["branches"] if b["label"] == "质疑资金链")
    script_round(
        "SENTINEL_R3 银灰展开喀兰铁路的规划图，指尖停在圣山隧道的位置。",
        title="铁路蓝图", summary="银灰详解铁路计划",
        branches=[{"label": "要求见大长老", "intent": "推进"}],
    )
    r3 = play(branch_id=b_r3["id"])
    t = tree()
    assert len(t["nodes"]) == 2, "选分支后应生成一个新子节点"
    node3_id = t["current_id"]
    node3 = t["nodes"][node3_id]
    assert node3["parent_id"] == "n_root" and node3["depth"] == 1
    assert node3["branch_label"] == "质疑资金链"
    assert node3["title"] == "铁路蓝图"
    assert "SENTINEL_R3" in node3["content"], "分支节点内容应来自本轮 LLM 叙述"
    assert node3_id in t["nodes"]["n_root"]["children"]
    assert "要求见大长老" in {b["label"] for b in node3["branches"]}

    # ── R4 子节点下再选分支 → 孙节点（depth 2，多层展开）──
    b_r4 = next(b for b in r3["branches"] if b["label"] == "要求见大长老")
    script_round(
        "SENTINEL_R4 锏按住刀柄，会客厅的空气骤然绷紧。",
        title="针锋相对", summary="会谈走向僵持",
        branches=[{"label": "缓和气氛", "intent": "社交"}],
    )
    r4 = play(branch_id=b_r4["id"])
    t = tree()
    assert len(t["nodes"]) == 3
    node4_id = t["current_id"]
    node4 = t["nodes"][node4_id]
    assert node4["parent_id"] == node3_id and node4["depth"] == 2
    assert node4["branch_label"] == "要求见大长老"
    assert node4["state"]["round_end"] == 4

    # ── R5 回档到根 → 走另一分支「沉默观察」→ 树分叉 ──
    rb = client.post(f"/api/sessions/{sid}/rollback-node", json={"node_id": "n_root"})
    assert rb.status_code == 200, rb.get_json()
    assert tree()["current_id"] == "n_root"
    # 回档恢复了根节点时刻的分支选项（R2 的最新选项集），玩家才能「走别的路」
    assert "沉默观察" in emitted_labels()
    b_r5 = next(b for b in session.overlay.get_emitted_branches()
                if b["label"] == "沉默观察")

    script_round(
        "SENTINEL_R5 博士不动声色地观察银灰的每一个细微表情。",
        title="静观其变", summary="博士选择沉默观察",
        branches=[{"label": "告辞离开", "intent": "推进"}],
    )
    r5 = play(branch_id=b_r5["id"])
    t = tree()
    assert len(t["nodes"]) == 4, "分叉应新增节点，且回档路径上的节点保留"
    node5_id = t["current_id"]
    node5 = t["nodes"][node5_id]
    assert node5["parent_id"] == "n_root" and node5["depth"] == 1
    assert node5["branch_label"] == "沉默观察"
    assert "SENTINEL_R5" in node5["content"]
    assert set(t["nodes"]["n_root"]["children"]) == {node3_id, node5_id}, \
        "根节点下应有两个子节点共存（树分叉）"

    # ── R6 再次回档到根 → 重走同一分支「沉默观察」→ 复用节点 ──
    assert client.post(f"/api/sessions/{sid}/rollback-node",
                       json={"node_id": "n_root"}).status_code == 200
    b_r6 = next(b for b in session.overlay.get_emitted_branches()
                if b["label"] == "沉默观察")
    script_round(
        "SENTINEL_R6 博士再次选择沉默，茶汤的热气在两人之间升腾。",
        title="静观其变（复访）", summary="重走沉默观察",
        branches=[{"label": "告辞离开", "intent": "推进"}],
    )
    r6 = play(branch_id=b_r6["id"])
    t = tree()
    assert len(t["nodes"]) == 4, "重走同一分支应复用既有节点，树不膨胀"
    assert t["current_id"] == node5_id, "同父同分支应命中同一确定性子节点"
    assert "SENTINEL_R6" in t["nodes"][node5_id]["content"], "复访应刷新节点内容"

    # ── 终态：/story-state 契约 ──
    st = client.get(f"/api/sessions/{sid}/story-state").get_json()
    tv = st["tree"]
    assert tv["has_tree"] is True
    assert tv["root_id"] == "n_root" and tv["current_id"] == node5_id
    assert len(tv["nodes"]) == 4
    depths = {n["id"]: n["depth"] for n in tv["nodes"]}
    assert depths[node4_id] == 2 and depths[node3_id] == 1 and depths[node5_id] == 1
    # 当前路径 = 根 → node5
    assert tv["path"] == ["n_root", node5_id]
    # 节点历史导出为回档点
    assert {"n_root", node3_id, node4_id, node5_id} == \
        {n["node_id"] for n in st["node_history"]}
    # 当前节点带状态
    assert tv["current_node"]["has_state"] is True


def test_degraded_extraction_keeps_flow_alive(flow):
    """Call 2 空响应（degraded）轮：叙述链路不断，节点仍推进。"""
    session, script_round, play = flow["session"], flow["script_round"], flow["play"]

    script_round("SENTINEL_D1 开场。", title="开场", summary="开场",
                 branches=[{"label": "向前", "intent": "推进"}])
    play()

    # 下一轮提取降级：空文本 + degraded 标记（复现真实 LLM 空响应）
    sm = session.scene_manager
    sm.narrate = lambda *a, **k: ("SENTINEL_D2 风雪又起。", {}, None)
    sm.extract_markers = lambda *a, **k: {
        "beat_complete": False, "combat": None, "choices": None,
        "branches": None, "node_title": None, "summary": None,
        "environment": None, "usage": None, "error": None,
        "degraded": True, "retried": True, "finish_reason": "length",
    }
    r = play()
    t = session.overlay.get_story_tree()
    assert "SENTINEL_D2" in t["nodes"]["n_root"]["content"], \
        "降级轮叙述仍应落进当前节点"
    assert t["nodes"]["n_root"]["state"]["round_end"] == 2, \
        "降级轮仍推进节点轮次区间"
    assert "narrative" in r, "降级不应导致 500，叙述照常返回"
