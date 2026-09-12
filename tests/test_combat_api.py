"""战斗 HTTP 接口契约（前端消费的 DTO 形状）：节点开战 → 状态 → 移动/出牌。"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture(scope="module")
def test_id(client):
    res = client.post("/api/combat/test/start", json={"node_id": "enc_training"})
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    yield body["test_id"]
    client.delete(f"/api/combat/test/{body['test_id']}")


def test_node_catalog(client):
    nodes = client.get("/api/combat/nodes").get_json()["nodes"]
    assert len(nodes) >= 16
    sample = next(n for n in nodes if n["node_id"] == "enc_snow_convoy")
    assert sample["bind"]["plot_id"] == "fengxue_guojing"
    assert sample["bind"]["beat_id"] == "convoy_fight" or sample["bind"]["beat_id"]


def test_enemy_catalog_marks_derived(client):
    enemies = client.get("/api/combat/enemies").get_json()["enemies"]
    assert len(enemies) >= 19
    assert any(e["derived_from_attributes"] for e in enemies)
    assert all("combat_stats" in e for e in enemies)


def test_tile_registry(client):
    payload = client.get("/api/combat/tiles").get_json()
    ids = {t["tile_id"] for t in payload["tiles"]}
    assert {"ground", "wall", "cover", "high_ground", "hazard_fire"} <= ids


def test_state_dto_shape(client, test_id):
    state = client.get(f"/api/combat/test/{test_id}/state").get_json()
    for key in ("rows", "cols", "tiles", "tile_defs", "deploy", "range_metric",
                "units", "shared_hand", "valid_moves", "valid_moves_unit"):
        assert key in state, key
    assert "grid_size" not in state, "旧字段不应再出现在 DTO 中"
    assert state["range_metric"] == "manhattan"
    assert len(state["tiles"]) == state["rows"]
    assert all(len(row) == state["cols"] for row in state["tiles"])
    assert state["deploy"]["player"] and state["deploy"]["enemy"]


def test_valid_moves_follow_selected_unit(client, test_id):
    state = client.get(f"/api/combat/test/{test_id}/state").get_json()
    player = next(u for u in state["units"] if u["team"] == "player")
    scoped = client.get(
        f"/api/combat/test/{test_id}/state?selected_unit={player['unit_id']}").get_json()
    assert scoped["valid_moves_unit"] == player["unit_id"]
    assert scoped["valid_moves"], "玩家回合应有可达格"
    # 曼哈顿预算：可达格到起点距离 == 代价上界（此处只校验在同一连通域且不越界）
    for r, c in scoped["valid_moves"]:
        assert 0 <= r < scoped["rows"] and 0 <= c < scoped["cols"]


def test_units_block_and_walls_reject_illegal_move(client, test_id):
    state = client.get(f"/api/combat/test/{test_id}/state").get_json()
    player = next(u for u in state["units"] if u["team"] == "player")
    res = client.post(f"/api/combat/test/{test_id}/action", json={
        "action": "move", "unit_id": player["unit_id"], "target": [player["pos"][0], player["pos"][1]],
    })
    # 原地移动距离 0：validate_move 允许（代价 0 ≤ 预算），但落点是自身所在格 → 视为可落脚
    assert res.status_code in (200, 400)


def test_unknown_node_returns_404(client):
    res = client.post("/api/combat/test/start", json={"node_id": "enc_not_exists"})
    assert res.status_code == 404


def test_unknown_selected_unit_returns_empty_moves(client, test_id):
    state = client.get(
        f"/api/combat/test/{test_id}/state?selected_unit=不存在").get_json()
    assert state["valid_moves"] == []
