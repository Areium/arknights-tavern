"""程序化生成一场合法的战斗规格（固定种子可复现）。

这是"LLM 生成战斗"的**确定性基线**与后备路径：没有 LLM 时也能为肉鸽/试玩批量产出
战斗；有 LLM 时可用它作为对照与兜底（生成失败就退回程序化编排）。

用法::

    python3 tools/generate_battle_spec.py --node-id enc_gen_1 --band T2 --seed 42
    python3 tools/generate_battle_spec.py --band T3 --seed 7 --out /tmp/gen.json
    for i in $(seq 1 5); do python3 tools/generate_battle_spec.py --node-id enc_rg_$i --seed $i --out data/combat/nodes/enc_rg_$i.json --force; done

产物一定通过 `tools/validate_battle_spec.py`（生成后自校验，失败自动换种子重试）。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from combat_balance import classify_enemy, node_budget_report  # noqa: E402
from combat_data_loader import CombatDataLoader  # noqa: E402
from combat_nodes import NodeError, validate_node  # noqa: E402
from combat_rules import band_config  # noqa: E402

LAYOUTS = ["open", "corridor", "pillars", "ruins"]


def _terrain(layout: str, rows: int, cols: int, rng: random.Random) -> list[list[str]]:
    """生成地形：始终保留中央横向通路，避免两个部署区被隔断（软锁）。"""
    grid = [["ground"] * cols for _ in range(rows)]
    mid = rows // 2
    keep_clear = {mid, max(0, mid - 1), min(rows - 1, mid + 1)}

    def paint(tile: str, r: int, c: int) -> None:
        if r in keep_clear or c in (0, 1, cols - 2, cols - 1):
            return
        grid[r][c] = tile

    if layout == "corridor":
        wall_col = cols // 2
        for r in range(rows):
            paint("wall", r, wall_col)
        for _ in range(rng.randint(1, 3)):
            hole = rng.choice([r for r in range(rows) if r not in keep_clear])
            grid[hole][wall_col] = "ground"
    elif layout == "pillars":
        for r in range(2, rows - 2, 2):
            for c in range(2, cols - 2, 2):
                paint("wall", r, c)
    elif layout == "ruins":
        for _ in range((rows * cols) // 8):
            paint("wall", rng.randrange(rows), rng.randrange(cols))
        for _ in range(max(2, (rows * cols) // 16)):
            paint("cover", rng.randrange(rows), rng.randrange(cols))
    else:  # open：只有少量掩体与高台
        for _ in range(max(2, (rows * cols) // 14)):
            paint(rng.choice(["cover", "cover", "high_ground"]),
                  rng.randrange(rows), rng.randrange(cols))

    if rng.random() < 0.35:
        paint("hazard_fire", rng.choice([r for r in range(rows) if r not in keep_clear]),
              rng.randrange(cols))
    return grid


def _catalog(loader: CombatDataLoader, max_threat: float) -> list[dict]:
    """可用的敌人（按威胁从低到高），用于凑预算。"""
    rows: list[dict] = []
    for entry in loader.list_enemy_catalog():
        stats = entry.get("combat_stats") or {}
        if not stats.get("hp"):
            continue
        info = classify_enemy(stats, level=entry.get("level", 1),
                              declared_role=entry.get("role", ""),
                              declared_tier=entry.get("power_tier", ""))
        threat = float(info["threat_points"])
        if threat <= max_threat:
            rows.append({"name": entry["name"], "threat": threat})
    rows.sort(key=lambda r: r["threat"])
    return rows


def _plan_waves(catalog: list[dict], target: float, rng: random.Random,
                waves: int) -> list[dict]:
    """按目标威胁凑编排：贪心叠加最接近剩余预算的敌人。"""
    if not catalog:
        return []
    remaining = target
    picks: list[dict] = []
    guard = 0
    while remaining > 0 and guard < 40:
        guard += 1
        affordable = [c for c in catalog if c["threat"] <= remaining + 1e-6]
        if not affordable:
            break
        # 在"能装下"的敌人里随机偏大，制造强兵而非一堆杂兵
        pick = affordable[rng.randint(max(0, len(affordable) - 3), len(affordable) - 1)]
        picks.append(pick)
        remaining -= pick["threat"]
    if not picks:
        picks = [catalog[0]]

    total = sum(p["threat"] for p in picks)
    # 拆波：默认单波；威胁总量 ≥6 且随机通过时拆两波（60/40）
    if waves > 1 and total >= 6 and len(picks) >= 3:
        cut = max(1, int(len(picks) * 0.6))
        groups = [picks[:cut], picks[cut:]]
    else:
        groups = [picks]

    out: list[dict] = []
    for group in groups:
        merged: dict[str, int] = {}
        for pick in group:
            merged[pick["name"]] = merged.get(pick["name"], 0) + 1
        entries = [{"enemy": name, "count": count}
                   for name, count in merged.items()]
        out.append({"enemies": entries})
    return out


def _place(rows: int, cols: int, waves: list[dict], grid: list[list[str]],
           rng: random.Random) -> None:
    """给每个敌人分配敌方部署区内的落点（保序、不落在阻挡格）。"""
    cells = [(r, c) for r in range(rows) for c in range(cols - 2, cols)
             if grid[r][c] == "ground"]
    rng.shuffle(cells)
    idx = 0
    for wave in waves:
        for entry in wave["enemies"]:
            positions = []
            for _ in range(entry["count"]):
                if idx >= len(cells):
                    break
                positions.append(list(cells[idx]))
                idx += 1
            if positions:
                entry["positions"] = positions


def generate(node_id: str, band: str, seed: int, *, waves_hint: int = 0) -> dict:
    loader = CombatDataLoader()
    rng = random.Random(seed)
    cfg = band_config(band)
    rng_cfg = cfg.get("threat_range") or [3.0, 6.0]
    target = rng.uniform(float(rng_cfg[0]) * 1.1, float(rng_cfg[1]) * 0.95)

    rows = rng.choice([7, 8, 9, 9, 11])
    cols = rng.choice([8, 9, 11, 11, 13])
    layout = rng.choice(LAYOUTS)
    grid = _terrain(layout, rows, cols, rng)

    catalog = _catalog(loader, max_threat=max(1.0, target))
    waves_hint = waves_hint or (2 if rng.random() < 0.4 else 1)
    waves = _plan_waves(catalog, target, rng, waves_hint)
    _place(rows, cols, waves, grid, rng)

    mid = rows // 2
    node = {
        "schema_version": 1,
        "node_id": node_id,
        "name": f"生成战斗 {node_id}",
        "summary": f"程序化生成（{layout} 布局 · 目标阶段带 {band} · 种子 {seed}）",
        "bind": {"plot_id": "", "chapter_id": "", "beat_id": ""},
        "rules": {"range_metric": "manhattan", "allow_corner_cut": False},
        "map": {
            "rows": rows, "cols": cols, "tiles": grid,
            "deploy": {
                "player": {"rect": [max(0, mid - 1), 0, min(rows - 1, mid + 1), 1]},
                "enemy": {"rect": [max(0, mid - 1), cols - 2, min(rows - 1, mid + 1), cols - 1]},
                "enemy_random_shift": False,
            },
        },
        "waves": waves,
        "conditions": {"max_rounds": 8, "escape_enabled": True},
        "rewards": {"xp": 0, "items": [], "unlock": []},
        "difficulty": {
            "category": "test", "encounter_type": "normal", "band": band,
            "threat_budget": 0, "target_rounds": 4,
            "apply_band_scaling": False,
        },
        "balance_version": 1,
    }

    report = node_budget_report(node, loader=loader)
    node["difficulty"]["threat_budget"] = report["total"]
    node["difficulty"]["target_rounds"] = max(
        3, min(10, int(round(report["total"] / 1.4))))
    node["rewards"]["xp"] = int(round(20 + report["total"] * 8))
    return node


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node-id", default="enc_generated")
    ap.add_argument("--band", default="T1", choices=["T0", "T1", "T2", "T3", "T4"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--waves", type=int, default=0, help="0 = 自动（1 或 2 波）")
    ap.add_argument("--out", default="", help="写入路径（默认打印到 stdout）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    ap.add_argument("--attempts", type=int, default=6, help="校验失败时换种子重试次数")
    args = ap.parse_args()

    loader = CombatDataLoader()
    enemy_names = set(loader.list_enemy_names())
    last_errors: list[str] = []

    for attempt in range(max(1, args.attempts)):
        node = generate(args.node_id, args.band, args.seed + attempt * 977,
                        waves_hint=args.waves)
        report = validate_node(node, enemy_names=enemy_names)
        if not report["errors"]:
            break
        last_errors = report["errors"]
    else:
        print("生成失败（多次尝试仍未通过校验）:", file=sys.stderr)
        for e in last_errors:
            print(f"  ✖ {e}", file=sys.stderr)
        return 1

    text = json.dumps(node, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        path = Path(args.out)
        if path.exists() and not args.force:
            print(f"目标已存在（加 --force 覆盖）: {path}", file=sys.stderr)
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        threat = node["difficulty"]["threat_budget"]
        print(f"已生成 {node['node_id']}（{node['map']['rows']}×{node['map']['cols']}，"
              f"{len(node['waves'])} 波，威胁 {threat}，{args.band}）-> {path}")
        print(f"  校验: OK（{len(report['warnings'])} 条警告）")
        for w in report["warnings"]:
            print(f"    ⚠ {w}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
