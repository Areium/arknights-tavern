"""战斗数值黄金基线：固定种子模拟指标快照。

基线文件 `tests/golden/combat_sim_metrics.json` 由本用例录制：

    GOLDEN_RECORD=1 python3 -m pytest tests/test_combat_sim_golden.py

用途：
1. 度量/地形重构前后对跑，量化"曼哈顿切换"的影响（配合 perf_tests/metric_migration_report.md）；
2. 防止无意改动战斗数值（例如伤害公式、AP 经济）。

矩阵刻意取小（全部战斗 × 标准队 × 5 次）以便留在回归网里；完整验收口径仍跑
`python3 perf_tests/simulate_combat.py --runs 200`。
"""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "perf_tests"))

import simulate_combat  # noqa: E402
from combat_data_loader import CombatDataLoader  # noqa: E402

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "combat_sim_metrics.json"
TEAM = "standard"
RUNS = 5
SEED_BASE = 20260912


def _round_floats(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v) for v in value]
    return value


def _encounter_ids() -> list[str]:
    ids: list[str] = []
    loader = CombatDataLoader()
    enc_dir = ROOT / "data" / "combat" / "encounters"
    node_dir = ROOT / "data" / "combat" / "nodes"
    if enc_dir.is_dir():
        ids += [p.stem for p in sorted(enc_dir.glob("*.md"))]
    if node_dir.is_dir():
        for path in sorted(node_dir.glob("*.json")):
            try:
                node_id = json.loads(path.read_text(encoding="utf-8")).get("node_id") or path.stem
            except (OSError, ValueError):
                continue
            if node_id not in ids:
                ids.append(node_id)
    resolved = []
    for battle_id in ids:
        encounter = loader.load_encounter(battle_id)
        if encounter:
            resolved.append((battle_id, encounter))
    return resolved


def sim_metrics() -> dict:
    loader = CombatDataLoader()
    out = {}
    for battle_id, encounter in _encounter_ids():
        rows = [
            simulate_combat.simulate_battle(encounter, TEAM, SEED_BASE + i, loader)
            for i in range(RUNS)
        ]
        summary = simulate_combat.summarise(rows)
        summary.pop("issues", None)
        out[battle_id] = _round_floats(summary)
    return out


def _load() -> dict:
    if not GOLDEN_PATH.is_file():
        return {}
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


if os.environ.get("GOLDEN_RECORD") == "1":
    _recorded = sim_metrics()
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(
        json.dumps(_recorded, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"已录制 {len(_recorded)} 组模拟指标基线 -> {GOLDEN_PATH}")


BASELINE = _load()


def test_sim_baseline_exists():
    assert BASELINE, (
        f"缺少基线文件 {GOLDEN_PATH}；"
        "用 GOLDEN_RECORD=1 python3 -m pytest tests/test_combat_sim_golden.py 录制"
    )


_CURRENT: dict | None = None


def _current_metrics() -> dict:
    """整批只算一次（参数化用例共用）。"""
    global _CURRENT
    if _CURRENT is None:
        _CURRENT = sim_metrics()
    return _CURRENT


@pytest.mark.parametrize("battle_id", sorted(BASELINE) or ["<无基线>"])
def test_sim_metrics_match_golden(battle_id: str):
    """指标一致（种子固定 → 结果必须逐字段可复现）。"""
    metrics = _current_metrics()
    assert battle_id in metrics, f"{battle_id} 已不在可模拟战斗集合中"
    assert metrics[battle_id] == BASELINE[battle_id], f"{battle_id} 模拟指标偏离基线"
