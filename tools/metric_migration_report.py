"""度量迁移报告：切比雪夫 → 统一曼哈顿的前后对比。

用法::

    python3 tools/metric_migration_report.py            # 5 次/组（与黄金基线同口径）
    python3 tools/metric_migration_report.py --runs 30  # 更稳的验收口径

数据来源：`perf_tests/metric_migration_baseline.json`（**冻结的改动前基线**，切比雪夫移动 +
切比雪夫射程，取自批次 0 的 `tests/golden/combat_sim_metrics.json`）对比当前模拟结果；
输出 `perf_tests/metric_migration_report.md`。同时给出射程覆盖格数的理论对照表
（切比雪夫 (2r+1)² vs 曼哈顿 2r²+2r+1）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "perf_tests"))

import simulate_combat  # noqa: E402
from combat_data_loader import CombatDataLoader  # noqa: E402

BASELINE_PATH = ROOT / "perf_tests" / "metric_migration_baseline.json"
REPORT_PATH = ROOT / "perf_tests" / "metric_migration_report.md"
TEAM = "standard"
SEED_BASE = 20260912


def _round(value):
    return round(value, 6) if isinstance(value, float) else value


def current_metrics(runs: int) -> dict:
    loader = CombatDataLoader()
    out = {}
    for summary in loader.list_nodes():
        node_id = summary["node_id"]
        node = loader.load_node(node_id)
        rows = [simulate_combat.simulate_battle(node, TEAM, SEED_BASE + i, loader)
                for i in range(runs)]
        metrics = simulate_combat.summarise(rows)
        metrics.pop("issues", None)
        out[node_id] = {k: _round(v) for k, v in metrics.items()}
    return out


def coverage_table() -> list[str]:
    lines = ["| 射程 r | 切比雪夫覆盖 | 曼哈顿覆盖 | 变化 |", "|---|---:|---:|---|"]
    for r in range(1, 6):
        cheb = (2 * r + 1) ** 2
        manh = 2 * r * r + 2 * r + 1
        lines.append(f"| {r} | {cheb} | {manh} | {(manh - cheb) / cheb:+.0%} |")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8")) \
        if BASELINE_PATH.is_file() else {}
    current = current_metrics(args.runs)

    lines = [
        "# 度量迁移报告：切比雪夫 → 统一曼哈顿（批次 1）",
        "",
        f"- 对比口径：标准队 × {args.runs} 次/组，种子基数 {SEED_BASE}",
        "- 基线：`perf_tests/metric_migration_baseline.json`（改动前冻结：切比雪夫移动 + 切比雪夫射程）",
        "- 现状：8 向曼哈顿代价（斜向 ×2）+ 曼哈顿射程 + 寻路/视线/地形 + 单体近战射程 1→2 补偿"
        "（含 CV 预算收紧后的伤害回调）",
        "- 复现：`python3 tools/metric_migration_report.py --runs 30`",
        "",
        "## 射程覆盖格数（含自身格）",
        "",
        *coverage_table(),
        "",
        "结论：r≥2 时覆盖约减半，r=1 由 8 邻格降为 4 正交格。近战卡因此打不到斜角邻格，",
        "故对玩家近战卡与敌方 `enemy_atk`/`enemy_heavy` 执行射程 1 → 2 的迁移",
        "（曼哈顿 r=2 的菱形正好把 4 个斜角邻格包回来）。",
        "",
        "## 逐节点指标（前 → 后）",
        "",
        "| 节点 | 胜率 | 中位回合 | P90 回合 | 血损率 | 每轮出牌AP | 每轮移动AP |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    deltas = []
    for node_id in sorted(set(baseline) | set(current)):
        before = baseline.get(node_id) or {}
        after = current.get(node_id) or {}
        if not before or not after:
            continue

        def cell(key: str, pct: bool = False) -> str:
            b, a = before.get(key), after.get(key)
            if b is None or a is None:
                return "—"
            fmt = (lambda v: f"{v:.0%}") if pct else (lambda v: f"{v:g}")
            return f"{fmt(b)} → {fmt(a)}"

        lines.append(
            f"| {node_id} | {cell('win_rate', True)} | {cell('median_rounds')} | "
            f"{cell('p90_rounds')} | {cell('hp_loss_rate', True)} | "
            f"{cell('player_card_ap_per_round')} | {cell('player_move_ap_per_round')} |"
        )
        if before.get("median_rounds") is not None and after.get("median_rounds") is not None:
            deltas.append(after["median_rounds"] - before["median_rounds"])

    lines += ["", "## 汇总", ""]
    if deltas:
        slow = [d for d in deltas if d > 0]
        lines.append(f"- 中位回合变化：{len(slow)}/{len(deltas)} 个节点变慢，"
                     f"平均 {sum(deltas) / len(deltas):+.1f} 回合")
    lines.append("- 移动预算仍为 `mobility // 2`；若整体节奏偏慢，调优旋钮为节点 "
                 "`rules.move_budget`（批次 3 与难度带一起定）")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.json:
        Path(args.json).write_text(json.dumps(current, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    print(f"报告已写入 {REPORT_PATH.relative_to(ROOT)}")
    if deltas:
        print(f"中位回合平均变化 {sum(deltas) / len(deltas):+.2f}")


if __name__ == "__main__":
    main()
