"""战斗开局黄金基线：重构前后，战斗开局结构必须保持稳定。

基线文件 `tests/golden/combat_openings.json` 由本用例录制：

    GOLDEN_RECORD=1 python3 -m pytest tests/test_combat_golden.py

基线的**不变项**：网格尺寸、部署坐标、单位血量/AP/属性、手牌、回合上限、波次。
**有意变更项**（度量切换带来的可达格/射程覆盖变化）在批次 1 重录基线时更新，
变更前后对照见 `perf_tests/metric_migration_report.md`。
"""

import json
import os
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from combat_session import CombatSession  # noqa: E402

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "combat_openings.json"
NODE_DIR = ROOT / "data" / "combat" / "nodes"

# 固定阵容与种子：模拟"标准小队"，保证开局状态可复现
ROSTER = ["阿米娅", "银灰", "灵知"]
SEED = 20260912


def battle_ids() -> list[str]:
    """全部可开局战斗的 id（战斗节点 JSON）。"""
    ids: list[str] = []
    if NODE_DIR.is_dir():
        for path in sorted(NODE_DIR.glob("*.json")):
            if path.stem.upper().startswith("TEMPLATE"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            node_id = data.get("node_id") or path.stem
            if node_id not in ids:
                ids.append(node_id)
    return ids


def opening_snapshot(encounter_id: str) -> dict:
    """开局状态的结构化快照（不含路径/随机落点以外的易变字段）。"""
    random.seed(SEED)
    combat = CombatSession("golden")
    state = combat.start(encounter_id, character_names=ROSTER)
    if state.get("phase") == "NONE":
        return {"error": state.get("error", "启动失败")}

    units = sorted(
        (
            {
                "unit_id": u["unit_id"],
                "name": u["name"],
                "team": u["team"],
                "char_class": u["char_class"],
                "hp": u["hp"],
                "max_hp": u["max_hp"],
                "personal_ap": u["personal_ap"],
                "max_personal_ap": u["max_personal_ap"],
                "patk": u["patk"],
                "matk": u["matk"],
                "def": u["def"],
                "res": u["res"],
                "spd": u["spd"],
                "hit": u["hit"],
                "eva": u["eva"],
                "pos": list(u["pos"]),
                "action_slots": u["action_slots"],
            }
            for u in state["units"]
        ),
        key=lambda item: (item["team"], item["unit_id"]),
    )
    return {
        "rows": state["rows"],
        "cols": state["cols"],
        "tiles": state["tiles"],
        "tile_ids": sorted(state["tile_defs"]),
        "deploy": state["deploy"],
        "range_metric": state["range_metric"],
        "max_rounds": state["max_rounds"],
        "escape_enabled": state["escape_enabled"],
        "round_num": state["round_num"],
        "phase": state["phase"],
        "shared_ap": state["shared_ap"],
        "shared_ap_max": state["shared_ap_max"],
        "wave_num": state["wave_num"],
        "pending_waves": state["pending_waves"],
        "hand": sorted(card["card_id"] for card in state["shared_hand"]),
        "deck_size": len(state["shared_pool"].get("deck", [])),
        # 移动可达集：批次 1 起由服务端权威计算（曼哈顿代价 + 地形 + 占位）
        "valid_moves_unit": state["valid_moves_unit"],
        "valid_moves": sorted(state["valid_moves"]),
        "units": units,
    }


def _load_baseline() -> dict:
    if not GOLDEN_PATH.is_file():
        return {}
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


if os.environ.get("GOLDEN_RECORD") == "1":
    _baseline = {bid: opening_snapshot(bid) for bid in battle_ids()}
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(
        json.dumps(_baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"已录制 {len(_baseline)} 个战斗基线 -> {GOLDEN_PATH}")


BASELINE = _load_baseline()


def test_baseline_exists():
    assert BASELINE, (
        f"缺少基线文件 {GOLDEN_PATH}；"
        "用 GOLDEN_RECORD=1 python3 -m pytest tests/test_combat_golden.py 录制"
    )


def test_no_battle_missing_from_baseline():
    """新增/删除战斗必须显式重录基线，避免静默漂移。"""
    current = set(BASELINE)
    found = set(battle_ids())
    assert found == current, (
        f"战斗集合与基线不一致：新增 {sorted(found - current)}，"
        f"消失 {sorted(current - found)}"
    )


@pytest.mark.parametrize("encounter_id", sorted(BASELINE) or ["<无基线>"])
def test_opening_matches_golden(encounter_id: str):
    expected = BASELINE[encounter_id]
    actual = opening_snapshot(encounter_id)
    assert actual == expected, f"{encounter_id} 开局状态偏离基线"
