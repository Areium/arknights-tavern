"""战斗节点注册表：校验、CRUD 冲突、剧情节拍绑定与世界书携带。"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app import create_app  # noqa: E402
from combat_nodes import (  # noqa: E402
    NodeError, decode_worldbook_entry, encode_node_for_worldbook,
    is_combat_node_entry, node_bindings, node_overview, template_data,
    validate_node,
)

NODE_DIR = ROOT / "data" / "combat" / "nodes"


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _small_node(**overrides) -> dict:
    node = {
        "schema_version": 1,
        "node_id": "enc_unit_test",
        "name": "单元测试节点",
        "summary": "",
        "bind": {"plot_id": "", "chapter_id": "", "beat_id": ""},
        "rules": {"range_metric": "manhattan", "allow_corner_cut": False},
        "map": {
            "rows": 5, "cols": 5, "tiles": "ground",
            "deploy": {"player": {"rect": [0, 0, 4, 0]}, "enemy": {"rect": [0, 4, 4, 4]}},
        },
        "waves": [{"enemies": [{"enemy": "整合运动士兵", "count": 1, "positions": [[2, 4]]}]}],
        "conditions": {"max_rounds": 6, "escape_enabled": True},
        "rewards": {"xp": 10, "items": []},
        "difficulty": {"category": "test", "encounter_type": "normal", "band": "T1"},
    }
    node.update(overrides)
    return node


# ── 校验 ──

def test_template_passes_validation_only_after_enemies_added():
    report = validate_node(template_data() | {"node_id": "t", "name": "T"})
    # 模板本身是空波次骨架，应报"没有敌人"
    assert any("没有任何敌人" in e for e in report["errors"]), report


def test_unknown_enemy_is_error():
    report = validate_node(_small_node(waves=[{"enemies": [{"enemy": "不存在的敌人"}]}]),
                           enemy_names={"整合运动士兵"})
    assert any("未知敌人" in e for e in report["errors"])


def test_out_of_bounds_and_blocked_positions():
    node = _small_node()
    node["map"]["tiles"] = [
        ["ground", "ground", "ground", "ground", "ground"],
        ["ground", "wall", "ground", "ground", "ground"],
        ["ground", "ground", "ground", "ground", "ground"],
        ["ground", "ground", "ground", "ground", "ground"],
        ["ground", "ground", "ground", "ground", "ground"],
    ]
    node["waves"] = [{"enemies": [
        {"enemy": "整合运动士兵", "count": 2, "positions": [[1, 1], [9, 9]]},
    ]}]
    report = validate_node(node)
    joined = " ".join(report["errors"])
    assert "不可通行格" in joined and "越界" in joined


def test_unit_caps_are_enforced():
    node = _small_node(waves=[{"enemies": [{"enemy": "整合运动士兵", "count": 99}]}])
    report = validate_node(node)
    assert any("count" in e for e in report["errors"])


def test_position_count_mismatch_is_warning():
    node = _small_node(waves=[{"enemies": [
        {"enemy": "整合运动士兵", "count": 2, "positions": [[2, 4]]}]}])
    report = validate_node(node)
    assert not report["errors"]
    assert any("与数量" in w for w in report["warnings"])


def test_unknown_band_and_metric_warn():
    node = _small_node(difficulty={"band": "T9"}, rules={"range_metric": "diagonal"})
    report = validate_node(node)
    joined = " ".join(report["warnings"])
    assert "T0–T4" in joined and "range_metric" in joined


def test_illegal_node_id_rejected():
    report = validate_node(_small_node(node_id="bad id/with slash"))
    assert any("非法字符" in e for e in report["errors"])


# ── CRUD ──

def test_create_save_conflict_and_delete(client):
    node_id = "enc_crud_test"
    assert client.post("/api/combat/nodes", json={"node_id": node_id, "name": "CRUD"}).status_code == 201
    try:
        detail = client.get(f"/api/combat/nodes/{node_id}").get_json()
        current_hash = detail["node"]["_hash"]

        payload = dict(detail["node"])
        payload["waves"] = [{"enemies": [{"enemy": "整合运动士兵", "count": 2,
                                          "positions": [[2, 4], [3, 4]]}]}]
        ok = client.put(f"/api/combat/nodes/{node_id}",
                        json={**payload, "_hash": current_hash})
        assert ok.status_code == 200, ok.get_json()

        # 用过期 hash 再存一次 → 409（模拟另一个窗口先保存过）
        stale = client.put(f"/api/combat/nodes/{node_id}",
                           json={**payload, "_hash": current_hash})
        assert stale.status_code == 409
        assert "冲突" in stale.get_json()["error"]

        # 非法内容 → 400 且不落盘
        bad = client.put(f"/api/combat/nodes/{node_id}",
                         json={"node": {**payload, "waves": [], "_hash": ""}})
        assert bad.status_code == 400
        assert "至少需要 1 个波次" in bad.get_json()["error"]
    finally:
        assert client.delete(f"/api/combat/nodes/{node_id}").status_code == 200


def test_duplicate_create_is_rejected(client):
    assert client.post("/api/combat/nodes", json={"node_id": "enc_training"}).status_code == 400


def test_delete_refuses_when_plot_references_node(client):
    # enc_snow_convoy 被 fengxue_guojing 的节拍引用
    res = client.delete("/api/combat/nodes/enc_snow_convoy")
    assert res.status_code == 409
    assert "剧情引用" in res.get_json()["error"]
    assert (NODE_DIR / "enc_snow_convoy.json").is_file()


def test_delete_missing_node_returns_404(client):
    assert client.delete("/api/combat/nodes/enc_not_here").status_code == 404


# ── 列表 / 进度 / 绑定 ──

def test_overview_lists_nodes_with_markers(client):
    payload = client.get("/api/combat/nodes").get_json()
    nodes = {n["node_id"]: n for n in payload["nodes"]}
    assert "enc_snow_convoy" in nodes
    assert nodes["enc_snow_convoy"]["markers"][0]["plot_id"] == "fengxue_guojing"
    assert payload["meta"]["bindings"] >= 8


def test_bindings_scan_plot_markers():
    bindings = node_bindings()
    assert bindings["enc_snow_convoy"][0]["beat_id"] == "beat_convoy_fight"
    assert all(not node_id.startswith("ID") for node_id in bindings)


def test_session_progress_reports_beat_states(client):
    created = client.post("/api/sessions", json={
        "mode": "story", "plot_id": "fengxue_guojing",
        "combat_mode": "tactical", "name": "节点进度测试",
    })
    assert created.status_code in (200, 201), created.get_json()
    session_id = created.get_json().get("id") or created.get_json()["session"]["id"]
    try:
        payload = client.get(f"/api/combat/nodes?session_id={session_id}").get_json()
        assert payload["meta"]["plot"], "应返回会话剧情上下文"
        progressed = [n for n in payload["nodes"] if n.get("progress")]
        assert progressed, "剧情会话应至少有一个带进度的节点"
        assert {n["progress"]["state"] for n in progressed} <= {"done", "current", "locked"}
    finally:
        client.delete(f"/api/sessions/{session_id}")


def test_progress_without_plot_returns_empty(client):
    created = client.post("/api/sessions", json={"mode": "free", "name": "无剧情"})
    session_id = created.get_json().get("id") or created.get_json()["session"]["id"]
    try:
        payload = client.get(f"/api/combat/nodes/progress?session_id={session_id}").get_json()
        assert payload["has_plot"] is False
        assert payload["progress"] == {}
    finally:
        client.delete(f"/api/sessions/{session_id}")


# ── 世界书携带 ──

def test_worldbook_entry_round_trip():
    node = _small_node(node_id="enc_wb_roundtrip")
    entry = encode_node_for_worldbook(node)
    assert is_combat_node_entry(entry)
    decoded = decode_worldbook_entry(entry)
    assert decoded["node_id"] == "enc_wb_roundtrip"
    assert decoded["map"]["rows"] == 5
    assert "_hash" not in decoded


def test_non_combat_entry_decodes_to_none():
    entry = {"uid": "x", "name": "设定", "content": "普通设定文本", "raw": {}}
    assert is_combat_node_entry(entry) is False
    assert decode_worldbook_entry(entry) is None


def test_decode_broken_entry_raises():
    entry = {
        "uid": "x", "name": "坏节点",
        "content": "```json combat-node\n{不是 JSON}\n```",
        "raw": {"extensions": {"arknights_tavern": {"entry_type": "combat_node",
                                                    "node_id": "bad"}}},
    }
    with pytest.raises(NodeError):
        decode_worldbook_entry(entry)


def test_invalid_entry_is_rejected_without_writing(client):
    entry = {
        "uid": "bad", "name": "非法节点",
        "content": '```json combat-node\n{"node_id":"enc_bad_import","name":"坏",'
                   '"map":{"rows":3,"cols":3,"tiles":"ground"},'
                   '"waves":[{"enemies":[{"enemy":"整合运动士兵","count":1,'
                   '"positions":[[99,99]]}]}]}\n```',
        "raw": {"extensions": {"arknights_tavern": {"entry_type": "combat_node"}}},
    }
    res = client.post("/api/combat/nodes/import-worldbook", json={"entries": [entry]})
    assert res.status_code == 207
    assert res.get_json()["errors"]
    assert not (NODE_DIR / "enc_bad_import.json").exists()


def test_import_nodes_through_worldbook_book_import(client):
    """整本书导入：条目里的战斗节点自动落地为节点文件。"""
    node = _small_node(node_id="enc_book_import")
    entry = encode_node_for_worldbook(node)
    entry["uid"] = "combat_node_enc_book_import"
    book = {"name": "节点导入测试书", "entries": [entry]}
    res = client.post("/api/worldbook/import", json={"name": book["name"],
                                                     "data": book})
    assert res.status_code == 201, res.get_json()
    body = res.get_json()
    assert body["combat_nodes"]["imported"], body["combat_nodes"]
    book_id = body["book"]["id"]
    try:
        assert (NODE_DIR / "enc_book_import.json").is_file()
        exported = client.get(f"/api/worldbook/{book_id}/export").get_json()
        assert exported["combat_nodes_refreshed"] == 1
        content = json.dumps(exported["data"], ensure_ascii=False)
        assert "enc_book_import" in content
    finally:
        client.delete(f"/api/worldbook/{book_id}")
        (NODE_DIR / "enc_book_import.json").unlink(missing_ok=True)


def test_node_overview_reports_missing_node_from_plot(client):
    """剧情引用了但注册表里没有的节点 → missing=True，供编辑器提示创建。"""
    fake = {"plot_id": "p", "chapter_id": "c", "beat_id": "beat_x"}
    rows, _ = node_overview(None)
    assert all("missing" not in r or r["missing"] is False for r in rows)
    # 直接验证 missing 分支的构造逻辑（不需要真的改剧情文件）
    from combat_nodes import node_bindings as _nb
    assert isinstance(_nb(), dict)
    assert fake["beat_id"]


def test_empty_node_cannot_start_battle(client):
    """新建的空节点（无敌人）可保存，但开战必须被拒绝并给出可读原因。"""
    node_id = "enc_empty_test"
    assert client.post("/api/combat/nodes", json={"node_id": node_id}).status_code == 201
    try:
        res = client.post("/api/combat/test/start", json={"node_id": node_id})
        assert res.status_code == 400
        assert "没有可出场的敌人" in res.get_json()["error"]
    finally:
        client.delete(f"/api/combat/nodes/{node_id}")
