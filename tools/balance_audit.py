"""数值审计：敌人分层 / 威胁点 / 节点威胁预算 与阶段带一致性。

取代两个已失效的迁移脚本（`scripts/migrate_balance_v1.py`、
`scripts/tune_encounters_v1.py` —— 它们的输入格式 `data/combat/encounters/*.md` 与
`data/combat/enemies/*.md` 已在批次 1 被 JSON 节点 + 统一敌人库替换）。

用法::

    python3 tools/balance_audit.py                      # 打印 + 写报告
    python3 tools/balance_audit.py --json out.json      # 同时导出机器可读结果
    python3 tools/balance_audit.py --strict             # 存在偏差时退出码 1（CI 用）

审计项：
1. 每个敌人的自动分类 vs frontmatter 声明（role / power_tier / threat_points）；
2. §12 硬性测试「敌人 XP 与威胁点单调相关」；
3. 每个节点的实际威胁 vs 声明 `threat_budget` 与阶段带推荐。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import frontmatter  # noqa: E402
from combat_balance import classify_enemy, node_budget_report  # noqa: E402
from combat_data_loader import CombatDataLoader  # noqa: E402

ENEMY_DIR = ROOT / "data" / "enemies"
REPORT_MD = ROOT / "perf_tests" / "balance_audit_report.md"


def audit_enemies(loader: CombatDataLoader) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(ENEMY_DIR.glob("*.md")):
        if path.stem == "TEMPLATE":
            continue
        meta = dict(frontmatter.load(path).metadata)
        stats = meta.get("combat_stats") or {}
        derived = not stats
        if derived:
            unit = loader.load_enemy(path.stem)
            if unit is None:
                continue
            stats = {"hp": unit.max_hp, "patk": unit.PATK, "defense": unit.DEF}

        info = classify_enemy(stats, level=int(meta.get("level", 1) or 1),
                              declared_role=str(meta.get("role") or ""),
                              declared_tier=str(meta.get("power_tier") or ""))
        auto = classify_enemy(stats, level=int(meta.get("level", 1) or 1))
        issues: list[str] = []
        if not derived and meta.get("role") and meta["role"] != auto["role"]:
            issues.append(f"声明 role={meta['role']} 与自动分类 {auto['role']} 不一致")
        if not derived and meta.get("threat_points") is not None:
            try:
                if abs(float(meta["threat_points"]) - info["threat_points"]) > 0.05:
                    issues.append(
                        f"声明 threat_points={meta['threat_points']} 与模型 {info['threat_points']} 不一致")
            except (TypeError, ValueError):
                issues.append("threat_points 非数值")
        if not derived and meta.get("action_slots") is not None:
            try:
                if int(meta["action_slots"]) != info["action_slots"]:
                    issues.append(
                        f"声明 action_slots={meta['action_slots']} 与模板 {info['action_slots']} 不一致")
            except (TypeError, ValueError):
                issues.append("action_slots 非整数")

        rows.append({
            "name": path.stem,
            "role": info["role"],
            "auto_role": auto["role"],
            "power_tier": info["power_tier"],
            "threat_points": info["threat_points"],
            "action_slots": info["action_slots"],
            "xp_reward": int(meta.get("xp_reward", 0) or 0),
            "derived_from_attributes": derived,
            "issues": issues,
        })
    return rows


def audit_xp_monotonic(rows: list[dict]) -> list[str]:
    """§12 硬性测试：威胁点越高，XP 不得越低。"""
    problems: list[str] = []
    ordered = sorted((r for r in rows if not r["derived_from_attributes"]),
                     key=lambda r: r["threat_points"])
    for a, b in zip(ordered, ordered[1:]):
        if b["threat_points"] > a["threat_points"] and b["xp_reward"] < a["xp_reward"]:
            problems.append(
                f"{b['name']}（威胁 {b['threat_points']}）XP {b['xp_reward']} 低于 "
                f"{a['name']}（威胁 {a['threat_points']}）XP {a['xp_reward']}")
    return problems


def audit_nodes(loader: CombatDataLoader) -> list[dict]:
    rows: list[dict] = []
    for summary in loader.list_nodes():
        node = loader.load_node(summary["node_id"]) or {}
        report = node_budget_report(node, loader=loader)
        rows.append({
            "node_id": summary["node_id"],
            "name": summary.get("name", ""),
            "units": report["units"],
            "threat": report["total"],
            "declared_budget": report.get("declared_budget"),
            "band": report.get("declared_band", ""),
            "band_hint": report["band_hint"],
            "budget_ratio": report.get("budget_ratio"),
            "warnings": report["warnings"],
        })
    return rows


def write_report(enemy_rows: list[dict], node_rows: list[dict],
                 xp_problems: list[str]) -> None:
    lines = [
        "# 战斗数值审计报告（威胁模型 v1）",
        "",
        f"- 敌人条目：{len(enemy_rows)}（其中按 attributes 派生数值："
        f"{sum(1 for r in enemy_rows if r['derived_from_attributes'])}）",
        f"- 战斗节点：{len(node_rows)}",
        f"- XP 单调性问题：{len(xp_problems)}",
        "",
        "## 敌人分层",
        "",
        "| 敌人 | role | 自动分类 | 阶段带 | 威胁点 | 行动槽 | XP | 偏差 |",
        "|---|---|---|---|---:|---:|---:|---|",
    ]
    for r in enemy_rows:
        lines.append(
            f"| {r['name']} | {r['role']} | {r['auto_role']} | {r['power_tier']} | "
            f"{r['threat_points']} | {r['action_slots']} | {r['xp_reward']} | "
            f"{'；'.join(r['issues']) or '-'} |")
    if xp_problems:
        lines += ["", "## XP 单调性问题", ""] + [f"- {p}" for p in xp_problems]
    lines += ["", "## 节点威胁预算", "",
              "| 节点 | 单位 | 威胁 | 声明预算 | 预算偏差 | 阶段带 | 推荐 | 备注 |",
              "|---|---:|---:|---:|---:|---|---|---|"]
    for r in node_rows:
        ratio = f"{r['budget_ratio']:.0%}" if r.get("budget_ratio") is not None else "-"
        lines.append(
            f"| {r['node_id']} | {r['units']} | {r['threat']} | "
            f"{r['declared_budget'] if r['declared_budget'] is not None else '-'} | {ratio} | "
            f"{r['band'] or '-'} | {r['band_hint']} | {'；'.join(r['warnings']) or '-'} |")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--strict", action="store_true",
                    help="存在敌人分层偏差/XP 单调性问题/节点预算超差时返回退出码 1")
    args = ap.parse_args()

    loader = CombatDataLoader()
    enemy_rows = audit_enemies(loader)
    node_rows = audit_nodes(loader)
    xp_problems = audit_xp_monotonic(enemy_rows)
    write_report(enemy_rows, node_rows, xp_problems)

    enemy_issues = [r for r in enemy_rows if r["issues"]]
    node_issues = [r for r in node_rows if r["warnings"]]
    print(f"敌人 {len(enemy_rows)}（分层偏差 {len(enemy_issues)}）"
          f" | 节点 {len(node_rows)}（预算/阶段带提示 {len(node_issues)}）"
          f" | XP 单调性 {len(xp_problems)}")
    for r in enemy_issues[:8]:
        print(f"  ! {r['name']}: {'；'.join(r['issues'])}")
    for r in node_issues[:8]:
        print(f"  ! {r['node_id']}: {'；'.join(r['warnings'])}")
    print(f"报告 -> {REPORT_MD.relative_to(ROOT)}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"enemies": enemy_rows, "nodes": node_rows, "xp_problems": xp_problems},
            ensure_ascii=False, indent=2), encoding="utf-8")

    if args.strict and (enemy_issues or xp_problems or node_issues):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
