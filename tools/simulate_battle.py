"""固定种子试跑战斗规格（注册表节点或候选 JSON），产出可判断的指标。

用法::

    python3 tools/simulate_battle.py --node enc_training
    python3 tools/simulate_battle.py --spec candidate.json --runs 60 --team standard
    python3 tools/simulate_battle.py --spec candidate.json --json out.json \\
        --min-win-rate 0.6 --max-median-rounds 8 --max-hp-loss 0.5

指标：胜率 / 中位回合 / P90 回合 / 首回合清场率 / 治疗溢出率 / 血损率 /
每轮出牌·移动 AP / 敌每轮动作数（引擎 telemetry）。退出码：
0 = 满足所有给定阈值（未给阈值时只要跑通）；1 = 有阈值未满足或规格不可跑。

这是"LLM 生成 → 校验 → 试跑 → 人工审阅 → 入库"闭环里的**试跑**环节：
候选规格不必先入库就能评估；相同种子结果可复现。
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
from combat_balance import node_budget_report  # noqa: E402
from combat_data_loader import CombatDataLoader  # noqa: E402
from combat_nodes import validate_node  # noqa: E402


def _load_spec(args) -> tuple[str, dict]:
    if args.spec:
        path = Path(args.spec)
        if not path.is_file():
            raise SystemExit(f"规格文件不存在: {args.spec}")
        if args.spec == "-":
            return "<stdin>", json.load(sys.stdin)
        return path.name, json.loads(path.read_text(encoding="utf-8"))
    loader = CombatDataLoader()
    node = loader.load_node(args.node)
    if not node:
        raise SystemExit(f"战斗节点不存在: {args.node}")
    return args.node, node


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--node", help="注册表节点 id")
    src.add_argument("--spec", help="候选规格 JSON 路径（- 表示 stdin）")
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--team", default="standard",
                    choices=sorted(simulate_combat.TEAM_CLASSES.keys()))
    ap.add_argument("--seed-base", type=int, default=20260912)
    ap.add_argument("--json", default="")
    ap.add_argument("--min-win-rate", type=float, default=None)
    ap.add_argument("--max-median-rounds", type=float, default=None)
    ap.add_argument("--min-median-rounds", type=float, default=None)
    ap.add_argument("--max-hp-loss", type=float, default=None,
                    help="血损率上限（0–1）")
    args = ap.parse_args()

    label, node = _load_spec(args)
    loader = CombatDataLoader()
    report = validate_node(node, enemy_names=set(loader.list_enemy_names()))
    if report["errors"]:
        print(f"规格校验失败（{label}）:", file=sys.stderr)
        for e in report["errors"]:
            print(f"  ✖ {e}", file=sys.stderr)
        return 1

    rows = [simulate_combat.simulate_battle(node, args.team, args.seed_base + i, loader)
            for i in range(args.runs)]
    summary = simulate_combat.summarise(rows)
    summary.pop("issues", None)
    budget = node_budget_report(node, loader=loader)

    verdict: list[str] = []
    if args.min_win_rate is not None and summary["win_rate"] < args.min_win_rate:
        verdict.append(f"胜率 {summary['win_rate']:.0%} < 要求 {args.min_win_rate:.0%}")
    if args.max_median_rounds is not None and summary["median_rounds"] > args.max_median_rounds:
        verdict.append(f"中位回合 {summary['median_rounds']} > 上限 {args.max_median_rounds}")
    if args.min_median_rounds is not None and summary["median_rounds"] < args.min_median_rounds:
        verdict.append(f"中位回合 {summary['median_rounds']} < 下限 {args.min_median_rounds}")
    if args.max_hp_loss is not None and summary["hp_loss_rate"] > args.max_hp_loss:
        verdict.append(f"血损率 {summary['hp_loss_rate']:.0%} > 上限 {args.max_hp_loss:.0%}")

    payload = {
        "label": label,
        "node_id": node.get("node_id", label),
        "team": args.team,
        "runs": args.runs,
        "seed_base": args.seed_base,
        "summary": summary,
        "threat": budget,
        "verdict": verdict,
        "pass": not verdict,
    }
    if args.json:
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    print(f"节点 {payload['node_id']} · 队伍 {args.team} · {args.runs} 次（种子基 {args.seed_base}）")
    print(f"  胜率 {summary['win_rate']:.0%} | 中位回合 {summary['median_rounds']} | "
          f"P90 {summary['p90_rounds']} | 首回合清场 {summary['first_round_kill_rate']:.0%} | "
          f"血损 {summary['hp_loss_rate']:.0%}")
    print(f"  每轮 出牌AP {summary['player_card_ap_per_round']} · 移动AP "
          f"{summary['player_move_ap_per_round']} · 敌动作 {summary['enemy_actions_per_round']}")
    print(f"  威胁 {budget['total']}（预算 {budget.get('declared_budget') or '-'}，"
          f"阶段带 {budget.get('declared_band') or '-'} / 推荐 {budget['band_hint']}）")
    for w in budget.get("warnings", []):
        print(f"  ⚠ {w}")
    if args.json:
        print(f"结果 -> {args.json}")
    if verdict:
        print("未达阈值:")
        for v in verdict:
            print(f"  ✖ {v}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
