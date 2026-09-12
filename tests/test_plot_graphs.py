# -*- coding: utf-8 -*-
"""剧情节点图（plot_graphs）：序列化 roundtrip、结构校验、世界书存取。

只使用临时 WorldBookManager 目录写盘，不触碰真实 data/worldbooks/。
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from plot_graphs import (  # noqa: E402
    GraphError, decode_graph_entry, delete_graph, encode_graph_for_worldbook,
    entry_uid, is_graph_entry, list_graphs, load_graph, normalize_graph,
    save_graph, validate_graph,
)
from world_book import WorldBook, WorldBookManager  # noqa: E402

BOOK = "testbook"


def _doc() -> dict:
    return {
        "schema_version": 1,
        "plot_id": "fengxue_guojing",
        "title": "风雪过境",
        "nodes": [
            {"id": "n_a", "type": "plot", "title": "剧情入口", "x": 0, "y": 0, "ref": None},
            {"id": "n_b", "type": "beat", "title": "beat_open", "x": 260, "y": 0,
             "ref": {"chapter_idx": 1, "beat_id": "beat_open"}},
            {"id": "n_c", "type": "combat", "title": "雪道伏击", "x": 520, "y": 0,
             "ref": {"node_id": "enc_snow_ambush"}},
            {"id": "n_d", "type": "note", "title": "分支备忘", "content": "此处可选两条路线",
             "x": 260, "y": 180, "ref": None, "custom_field": "保留我"},
        ],
        "edges": [
            {"id": "e_1", "from": "n_a", "to": "n_b"},
            {"id": "e_2", "from": "n_b", "to": "n_c"},
            {"id": "e_3", "from": "n_b", "to": "n_d"},
        ],
    }


@pytest.fixture()
def mgr(tmp_path):
    manager = WorldBookManager(data_dir=tmp_path)
    manager.save(WorldBook(BOOK, name="测试书"))
    return manager, tmp_path


# ── 编解码 roundtrip ──

def test_encode_decode_roundtrip_lossless():
    doc = _doc()
    entry = encode_graph_for_worldbook(doc, display_name="风雪过境")
    assert entry["uid"] == "plot_graph_fengxue_guojing"
    assert entry["name"] == "节点图：风雪过境"
    assert is_graph_entry(entry)
    decoded = decode_graph_entry(entry)
    assert decoded == doc  # 围栏块 JSON 原样还原，未知字段保留
    assert decoded["nodes"][3]["custom_field"] == "保留我"


def test_encode_no_trigger_keys_so_never_injected():
    """布局数据绝不注入叙事：条目无关键词且非常驻。"""
    entry = encode_graph_for_worldbook(_doc())
    assert entry["trigger_keys"] == []
    assert not entry["raw"]["extensions"]["arknights_tavern"]["entry_type"] == "combat_node"


def test_decode_ignores_other_entries():
    assert not is_graph_entry({"uid": "x", "content": "普通条目"})
    assert decode_graph_entry({"uid": "x", "content": "普通条目"}) is None


def test_decode_broken_json_raises():
    entry = encode_graph_for_worldbook(_doc())
    entry["content"] = entry["content"].replace('{"schema_version"', "{broken")
    with pytest.raises(GraphError):
        decode_graph_entry(entry)


# ── 规范化与校验 ──

def test_normalize_coerces_unknown_type_and_fills_defaults():
    doc = normalize_graph({"nodes": [{"id": "n_x", "type": "alien", "title": "怪节点"}],
                           "edges": []}, plot_id="p1", worldbook_id=BOOK)
    node = doc["nodes"][0]
    assert node["type"] == "note"
    assert node["x"] == 0 and node["y"] == 0
    assert doc["plot_id"] == "p1" and doc["worldbook_id"] == BOOK


def test_validate_reports_dangling_edges_and_self_loops():
    doc = _doc()
    doc["edges"].append({"id": "e_bad", "from": "n_a", "to": "n_ghost"})
    doc["edges"].append({"id": "e_self", "from": "n_a", "to": "n_a"})
    doc["edges"].append({"id": "e_dup", "from": "n_a", "to": "n_b"})
    errors = validate_graph(doc)
    assert any("n_ghost" in e for e in errors)
    assert any("自环" in e for e in errors)
    assert any("重复" in e for e in errors)


def test_validate_duplicate_node_ids():
    doc = _doc()
    doc["nodes"][1]["id"] = "n_a"
    errors = validate_graph(doc)
    assert any("重复" in e for e in errors)


# ── 世界书存取 ──

def test_save_load_delete_roundtrip(mgr):
    mgr, _ = mgr
    doc = save_graph(mgr, BOOK, _doc(), display_name="风雪过境")
    assert doc["worldbook_id"] == BOOK
    assert doc["updated_at"] > 0

    loaded = load_graph(mgr, BOOK, "fengxue_guojing")
    assert loaded is not None
    assert [n["id"] for n in loaded["nodes"]] == ["n_a", "n_b", "n_c", "n_d"]
    assert len(loaded["edges"]) == 3
    assert list_graphs(mgr, BOOK) == ["fengxue_guojing"]

    # 同剧情再次保存 → 覆盖同一条目（单条目粒度），书内不出现重复条目
    doc["nodes"][0]["x"] = 999
    save_graph(mgr, BOOK, doc)
    book = mgr.load(BOOK)
    uids = [e.uid for e in book.entries if is_graph_entry(e.to_dict())]
    assert uids == ["plot_graph_fengxue_guojing"]
    assert load_graph(mgr, BOOK, "fengxue_guojing")["nodes"][0]["x"] == 999

    assert delete_graph(mgr, BOOK, "fengxue_guojing") is True
    assert load_graph(mgr, BOOK, "fengxue_guojing") is None
    assert list_graphs(mgr, BOOK) == []
    assert delete_graph(mgr, BOOK, "fengxue_guojing") is False


def test_save_rejects_dangling_edge(mgr):
    mgr, _ = mgr
    doc = _doc()
    doc["edges"].append({"id": "e_x", "from": "n_a", "to": "nope"})
    with pytest.raises(GraphError):
        save_graph(mgr, BOOK, doc)
    assert load_graph(mgr, BOOK, "fengxue_guojing") is None


def test_save_requires_book_and_plot(mgr):
    mgr, _ = mgr
    with pytest.raises(GraphError):
        save_graph(mgr, "", _doc())
    doc = _doc()
    doc["plot_id"] = ""
    with pytest.raises(GraphError):
        save_graph(mgr, BOOK, doc)


def test_load_survives_corrupted_entry(mgr):
    mgr, _ = mgr
    save_graph(mgr, BOOK, _doc())
    book = mgr.load(BOOK)
    for e in book.entries:
        if is_graph_entry(e.to_dict()):
            e.content = "```json plot-graph\n{broken\n```"
    mgr.save(book)
    assert load_graph(mgr, BOOK, "fengxue_guojing") is None


def test_entry_survives_book_export_roundtrip(mgr, tmp_path):
    """世界书导出（酒馆 v1）再导入后图文档仍在（raw 保留 → 无损搬家）。"""
    mgr, _ = mgr
    save_graph(mgr, BOOK, _doc())
    exported = mgr.load(BOOK).export_st()
    text = json.dumps(exported, ensure_ascii=False)
    assert "plot-graph" in text

    other = WorldBookManager(data_dir=tmp_path / "other")
    book2, report = other.import_book("迁移书", text)
    assert report.imported >= 1
    entries = [e.to_dict() for e in book2.entries if is_graph_entry(e.to_dict())]
    assert len(entries) == 1
    doc = decode_graph_entry(entries[0])
    assert doc["plot_id"] == "fengxue_guojing"
    assert [n["id"] for n in doc["nodes"]] == ["n_a", "n_b", "n_c", "n_d"]
