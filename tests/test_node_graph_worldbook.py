"""节点图与世界书归属：plot_flows 解析、node_graph 过滤、导入自动标注。

使用仓库内真实数据（data/plots、data/combat/nodes 均已标注归属 arknights），
除 import 打标测试外不写盘。
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import combat_nodes  # noqa: E402
from combat_nodes import (  # noqa: E402
    decode_worldbook_entry, encode_node_for_worldbook,
    import_worldbook_nodes, node_graph, node_overview, plot_flows,
)

BOOK = "arknights"


# ── plot_flows：剧情流程解析 ──

def test_plot_flows_use_directory_plot_id():
    flows = {f["plot_id"]: f for f in plot_flows()}
    # plot_id 与 node_bindings / 会话一致：用目录名而非 frontmatter id
    assert "fengxue_guojing" in flows
    assert "near-light" in flows


def test_plot_flows_collect_chapters_beats_and_combat_refs():
    flows = {f["plot_id"]: f for f in plot_flows()}
    feng = flows["fengxue_guojing"]
    assert len(feng["chapters"]) == 6
    beats = [b for c in feng["chapters"] for b in c["beats"]]
    assert len(beats) == 21
    # [COMBAT:] 引用挂在节拍上
    beat_refs = {nid for b in beats for nid in b["combat_nodes"]}
    assert "enc_snow_convoy" in beat_refs
    # 节拍摘要是首行非标记文本
    assert any(b["summary"] for b in beats)


def test_plot_flows_stop_at_narrative_section_end():
    """near-light 场景流程图配置区里的重复章节不应被收集。"""
    flows = {f["plot_id"]: f for f in plot_flows()}
    nl = flows["near-light"]
    assert [c["idx"] for c in nl["chapters"]] == [1, 2, 3, 4]


def test_plot_flows_orphan_combat_refs_at_plot_level():
    """无标准节拍结构的剧情（combat-test）→ 引用挂 plot 级。"""
    flows = {f["plot_id"]: f for f in plot_flows()}
    ct = flows["combat-test"]
    assert ct["chapters"] == []
    assert "enc_quick_test_1" in ct["combat_nodes"]


def test_plot_flows_worldbook_stamp():
    for f in plot_flows():
        assert f["worldbook_id"] == BOOK


# ── node_overview / node_graph：按世界书过滤 ──

def test_node_overview_book_owns_all_current_nodes():
    """真实数据：16 个存量节点已全部标注归属 arknights。"""
    rows, _meta = node_overview(book_id=BOOK)
    assert len(rows) == 16
    assert all(r["worldbook_id"] == BOOK for r in rows)


def test_node_overview_filters_foreign_book():
    rows, _meta = node_overview(book_id="不存在的书")
    assert rows == []


def test_node_overview_unfiltered_returns_all():
    unfiltered, _ = node_overview()
    assert len(unfiltered) == 16


def test_node_graph_includes_referenced_plots():
    g = node_graph(BOOK)
    plot_ids = {p["plot_id"] for p in g["plots"]}
    # 三个剧情均已标注归属 arknights
    assert {"combat-test", "fengxue_guojing", "near-light"} <= plot_ids
    # 图中节点与剧情引用自洽：战斗节点可按引用定位
    node_ids = {n["node_id"] for n in g["nodes"]}
    assert {"enc_snow_convoy", "enc_quick_test_1"} <= node_ids


# ── 世界书导入：节点自动标注归属 ──

@pytest.fixture()
def no_write(monkeypatch):
    """拦截 save_node 落盘，捕获导入时写入的节点数据。"""
    captured: dict = {}

    def fake_save_node(data, expected_hash="", *, enemy_names=None):
        captured[data["node_id"]] = data
        return data

    monkeypatch.setattr(combat_nodes, "save_node", fake_save_node)
    return captured


def test_import_worldbook_nodes_stamps_worldbook_id(no_write):
    node = {
        "node_id": "enc_wb_import", "name": "导入测试",
        "map": {"rows": 5, "cols": 5, "tiles": "ground",
                "deploy": {"player": {"rect": [0, 0, 4, 0]}, "enemy": {"rect": [0, 4, 4, 4]}}},
        "waves": [{"enemies": [{"enemy": "整合运动士兵", "count": 1, "positions": [[2, 4]]}]}],
    }
    entry = encode_node_for_worldbook(node)
    assert decode_worldbook_entry(entry)["node_id"] == "enc_wb_import"

    result = import_worldbook_nodes([entry], book_id=BOOK)
    assert result["errors"] == []
    assert result["imported"] == [{"node_id": "enc_wb_import", "book_id": BOOK}]
    stamped = no_write["enc_wb_import"]
    assert stamped["worldbook_id"] == BOOK
    assert stamped["source"] == {"type": "worldbook", "book_id": BOOK, "entry_uid": entry["uid"]}
