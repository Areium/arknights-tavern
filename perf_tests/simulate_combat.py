"""
固定种子批量模拟器（design §11 P0-5 落库 / §11 P1-5 分层模拟 / §12 验收标准）。

用法：
    python perf_tests/simulate_combat.py                       # 全部遭遇 × 三队，30 次/组合
    python perf_tests/simulate_combat.py --runs 200             # 验收口径
    python perf_tests/simulate_combat.py --encounters enc_final_showdown,enc_defense
    python perf_tests/simulate_combat.py --json out.json        # 自定义输出

输出：perf_tests/results_combat_progression.json + perf_tests/progression_report.md

设计要点：
- 相同种子 → 完全相同的结果（可复现，§11 P0 验收条件）；
- 玩家侧使用确定性启发式策略（模拟"同阶段合理队伍"的操作水平）；
- 敌人侧完全走引擎自身的意图规划与执行（预告与执行一致性的端到端验证）；
- 指标：中位/P90 回合、胜率、首回合清场率、单卡使用率、治疗溢出率、
  每轮实际消耗 AP / 出牌数 / 移动次数（引擎 telemetry）。
"""
import argparse
import json
import os
import random
import statistics
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
if os.path.join(_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))

from combat_data_loader import CombatDataLoader            # noqa: E402
from combat_engine.card_data import get_starting_deck      # noqa: E402
from combat_engine.engine import CombatEngine              # noqa: E402
from combat_engine.entity import CombatUnit                # noqa: E402
from combat_engine.grid import metric_distance            # noqa: E402

RESULTS_JSON = os.path.join(_HERE, "results_combat_progression.json")
REPORT_MD = os.path.join(_HERE, "progression_report.md")

# ── 队伍原型（假设，见交付说明）────────────────────────────────────────────
# 7 维属性 → 派生战斗数值：HP=耐受×12+强度×3、PATK=(强度+技巧)×2、
# DEF=耐受×1.5+强度×0.5、HEAL=(源石+规划)×2。
TEAM_ATTRS = {
    "standard": {   # T1 前期：HP≈114 / PATK 24 / 共享 AP 4
        "物理强度": 6, "战场机动": 6, "生理耐受": 8, "战术规划": 6,
        "战斗技巧": 6, "源石技艺适应性": 6, "情绪稳定性": 6,
    },
    "command": {    # T2 中期指挥队：战术规划 8 → 共享 AP 5
        "物理强度": 6, "战场机动": 6, "生理耐受": 8, "战术规划": 8,
        "战斗技巧": 6, "源石技艺适应性": 7, "情绪稳定性": 6,
    },
    "low": {        # T0 低配队：数值全面落后，用于测功率方差
        "物理强度": 4, "战场机动": 5, "生理耐受": 5, "战术规划": 4,
        "战斗技巧": 4, "源石技艺适应性": 4, "情绪稳定性": 5,
    },
}
TEAM_CLASSES = {
    "standard": ["近卫", "狙击", "医疗", "重装"],
    "command": ["战术指挥", "狙击", "医疗", "近卫"],
    "low": ["近卫", "狙击", "医疗", "先锋"],
}
TEAM_NAMES = {
    "standard": ["标准队", "指挥队", "低配队"],
}


def deploy_positions(cells: list, count: int = 4) -> list:
    """把部署区格列表展开为 count 个落点（不足时循环取用）。

    部署区已由 `combat_map.resolve_map` 归一为坐标列表（rect/cells 两种写法都处理过）。
    """
    positions = [tuple(p) for p in (cells or [])]
    if not positions:
        positions = [(0, 0)]
    return [positions[i % len(positions)] for i in range(count)]


def build_team(kind: str, cells: list) -> list[CombatUnit]:
    """按原型构建四人队并放置在玩家部署区内。"""
    attrs = TEAM_ATTRS[kind]
    classes = TEAM_CLASSES[kind]
    slots = deploy_positions(cells, len(classes))
    units: list[CombatUnit] = []
    for i, char_class in enumerate(classes):
        unit = CombatUnit.from_character_metadata(
            {"name": f"{kind}-{char_class}", "class": char_class,
             "attributes": dict(attrs)},
            team="player")
        unit.unit_id = f"{kind}-{char_class}"
        unit.pos = slots[i]
        units.append(unit)
    return units


def enemy_scale_of(encounter: dict, approach_id: str = "assault") -> float:
    for approach in encounter.get("approaches", []) or []:
        if approach.get("id") == approach_id:
            return float(((approach.get("combat") or {}).get("enemy_scale", 1.0)) or 1.0)
    return 1.0


def build_engine(node: dict, team_kind: str, loader: CombatDataLoader) -> CombatEngine:
    """从战斗节点组装一场战斗（敌人走数据加载器，与线上一致）。"""
    battle_map = loader.load_map(node)
    engine = CombatEngine(battle_map=battle_map, rules=loader.rules_of(node))
    # 部署区小于队伍时溢出到全图空格（与线上 CombatSession._player_slots 同策略）
    player_cells = list(battle_map.deploy_zone("player"))
    if len(player_cells) < len(TEAM_CLASSES[team_kind]):
        zone = set(player_cells)
        player_cells += [(r, c) for r in range(battle_map.rows)
                         for c in range(battle_map.cols)
                         if not battle_map.is_blocked((r, c)) and (r, c) not in zone]
    players = build_team(team_kind, player_cells)
    for unit in players:
        engine.add_player_unit(unit, cards=get_starting_deck(unit.char_class, count=7),
                               pos=unit.pos)

    fallback_cells = list(battle_map.deploy_zone("enemy"))
    scale = enemy_scale_of(node)
    waves = []
    for wave in node.get("waves", []) or []:
        built = []
        for entry in wave.get("enemies", []) or []:
            name = entry.get("enemy") or entry.get("name")
            count = int(entry.get("count", 1) or 1)
            positions = entry.get("positions") or []
            for i in range(count):
                unit = loader.load_enemy(name, stat_overrides=entry.get("stats"))
                if unit is None:
                    continue
                unit.unit_id = f"{name}#{len(built)}"
                if scale != 1.0:
                    unit.max_hp = max(1, int(unit.max_hp * scale))
                    unit.hp = unit.max_hp
                    unit.PATK *= scale
                    unit.MATK *= scale
                if i < len(positions):
                    pos = tuple(positions[i])
                elif fallback_cells:
                    pos = fallback_cells[len(built) % len(fallback_cells)]
                else:
                    pos = (0, 0)
                if not engine.grid.can_place(pos) and fallback_cells:
                    pos = next((c for c in fallback_cells if engine.grid.can_place(c)), pos)
                built.append((unit, pos))
        if built:
            waves.append(built)

    conditions = node.get("conditions", {}) or {}
    engine.max_rounds = int(conditions.get("max_rounds", 0) or 0)
    engine.escape_enabled = bool(conditions.get("escape_enabled", False))
    engine.load_waves(waves)
    engine.start_battle()
    return engine


# ── 玩家启发式策略（确定性） ──────────────────────────────────────────────

def _living(engine: CombatEngine, team: str) -> list[CombatUnit]:
    return [u for u in engine.units.values() if u.team == team and u.is_alive]


def _playable(engine: CombatEngine, unit: CombatUnit, card) -> tuple:
    """返回 (是否可打, 目标)。目标选择：治疗→最低血盟友；伤害→最低血敌人。

    治疗只在目标生命低于 75% 时才出手（模拟同阶段合理队伍，避免无意义溢出）。
    """
    if card.damage_type == "healing":
        allies = [u for u in _living(engine, unit.team)]
        if not allies:
            return False, None
        target = min(allies, key=lambda u: u.hp / max(1, u.max_hp))
        if target.hp / max(1, target.max_hp) > 0.75 and not card.effects:
            return False, None
        return engine.validate_card_play(unit.unit_id, card, target.pos) is None, target
    enemies = _living(engine, "enemy")
    if not enemies:
        return False, None
    for target in sorted(enemies, key=lambda u: u.hp):
        if engine.validate_card_play(unit.unit_id, card, target.pos) is None:
            return True, target
    return False, None


def play_player_round(engine: CombatEngine) -> None:
    """一轮玩家操作：按 SPD 降序，尽量把共享 AP 用在最高价值卡上。"""
    players = sorted(_living(engine, "player"), key=lambda u: -u.SPD)
    for unit in players:
        if engine.is_battle_over():
            return
        for _ in range(6):  # 单角色单轮最多 6 次尝试，防死循环
            if engine.is_battle_over() or engine.shared_ap <= 0:
                break
            hand = [c for c in engine.shared_pool.hand if c.owner == unit.name]
            if not hand:
                break
            best = None
            for card in hand:
                if card.cost > engine.shared_ap:
                    continue
                ok, target = _playable(engine, unit, card)
                if not ok:
                    continue
                # 价值序：能救命的治疗 > 高 CV 伤害
                score = card.cv_estimated or (12 * card.cost)
                if card.damage_type == "healing":
                    ally = target
                    score += 40 * (1 - ally.hp / max(1, ally.max_hp))
                if best is None or score > best[0]:
                    best = (score, card, target)
            if best is None:
                break
            _, card, target = best
            engine.play_card(unit.unit_id, card, target.pos)

    # 剩余个人 AP 用于靠拢：无牌可打时向最近敌人移动
    for unit in players:
        if engine.is_battle_over():
            return
        enemies = _living(engine, "enemy")
        if not enemies:
            return
        nearest = min(enemies, key=lambda e: engine.distance(unit.pos, e.pos))
        guard = 0
        while unit.AP > 0 and guard < 3:
            guard += 1
            step = engine.step_toward(unit.pos, nearest.pos, mover_id=unit.unit_id)
            if step == unit.pos or not engine.move_unit(unit.unit_id, step):
                break


def simulate_battle(encounter: dict, team_kind: str, seed: int,
                    loader: CombatDataLoader) -> dict:
    random.seed(seed)
    engine = build_engine(encounter, team_kind, loader)

    first_round_kill = False
    rounds = 0
    guard = 0
    while not engine.is_battle_over() and guard < 60:
        guard += 1
        play_player_round(engine)
        if engine.is_battle_over():
            break
        if engine.state.round_num == 1 and not _living(engine, "enemy"):
            first_round_kill = True
        engine.end_player_round()
    rounds = engine.state.round_num

    totals = engine.telemetry["totals"]
    hp_lost = {
        uid: max(0, engine.initial_hp.get(uid, u.max_hp) - u.hp)
        for uid, u in engine.units.items() if u.team == "player"
    }
    # 纯治疗卡（无附带效果）的溢出率才算治疗效率指标
    pure_heal_total = totals["healing_effective"] + totals["healing_overflow_pure"]
    return {
        "encounter_id": encounter.get("node_id", ""),
        "team": team_kind,
        "seed": seed,
        "winner": engine.state.winner,
        "win": engine.state.winner == "player",
        "rounds": rounds,
        "round_limit_hit": rounds > (engine.max_rounds or 10 ** 6),
        "first_round_kill": first_round_kill,
        "telemetry": totals,
        "healing_overflow_ratio": (
            totals["healing_overflow_pure"] / pure_heal_total) if pure_heal_total else 0.0,
        "player_hp_lost": sum(hp_lost.values()),
        "player_hp_total": sum(u.max_hp for u in engine.units.values() if u.team == "player"),
    }


def summarise(rows: list) -> dict:
    if not rows:
        return {}
    rounds = [r["rounds"] for r in rows]
    rounds_sorted = sorted(rounds)
    p90_idx = max(0, int(round(0.9 * (len(rounds_sorted) - 1))))
    card_usage: dict[str, int] = {}
    played_total = 0
    for r in rows:
        for card_id, count in (r["telemetry"].get("cards_used") or {}).items():
            card_usage[card_id] = card_usage.get(card_id, 0) + count
            played_total += count
    usage_ratio = {k: round(v / played_total, 4) for k, v in card_usage.items()} if played_total else {}
    dead_cards = [k for k, v in usage_ratio.items() if v < 0.05]
    return {
        "runs": len(rows),
        "win_rate": round(sum(1 for r in rows if r["win"]) / len(rows), 3),
        "median_rounds": statistics.median(rounds),
        "p90_rounds": rounds_sorted[p90_idx],
        "mean_rounds": round(statistics.fmean(rounds), 2),
        "first_round_kill_rate": round(sum(1 for r in rows if r["first_round_kill"]) / len(rows), 3),
        "healing_overflow_rate": round(statistics.fmean([r["healing_overflow_ratio"] for r in rows]), 3),
        "hp_loss_rate": round(statistics.fmean(
            [r["player_hp_lost"] / max(1, r["player_hp_total"]) for r in rows]), 3),
        "cards_played_total": played_total,
        "distinct_cards_used": len(card_usage),
        "dead_card_ratio": round(len(dead_cards) / len(usage_ratio), 3) if usage_ratio else 0.0,
        "player_card_ap_per_round": round(statistics.fmean(
            [r["telemetry"]["player_card_ap"] / max(1, r["rounds"]) for r in rows]), 2),
        "player_move_ap_per_round": round(statistics.fmean(
            [r["telemetry"]["player_move_ap"] / max(1, r["rounds"]) for r in rows]), 2),
        "enemy_actions_per_round": round(statistics.fmean(
            [r["telemetry"]["enemy_actions"] / max(1, r["rounds"]) for r in rows]), 2),
    }


def target_check(etype: str, summary: dict, encounter: dict | None = None) -> list:
    """按 §12 验收标准给出偏差清单。

    多波战（§1.1）按遭遇声明的 target_rounds 判定，而不是单波类型带
    —— 每波 2–3 回合 + 波次切换成本。
    """
    issues = []
    bands = {
        "teaching": (2, 4, 0.95, 1.0),
        "normal": (4, 6, 0.75, 0.90),
        "elite": (5, 7, 0.60, 0.80),
        "boss": (6, 9, 0.50, 0.70),
    }
    lo, hi, wlo, whi = bands.get(etype, bands["normal"])
    waves = len([w for w in ((encounter or {}).get("waves") or [])
                 if (w.get("enemies") or [])])
    if waves > 1 and encounter and encounter.get("target_rounds"):
        target = int(encounter["target_rounds"])
        lo, hi = max(1, target - 1), target + 1
    median = summary.get("median_rounds", 0)
    win = summary.get("win_rate", 0)
    if median < lo:
        issues.append(f"中位回合 {median} 快于目标 {lo}–{hi}")
    elif median > hi:
        issues.append(f"中位回合 {median} 慢于目标 {lo}–{hi}")
    if win > whi:
        issues.append(f"胜率 {win:.0%} 高于目标 {wlo:.0%}–{whi:.0%}")
    elif win < wlo:
        issues.append(f"胜率 {win:.0%} 低于目标 {wlo:.0%}–{whi:.0%}")
    if summary.get("first_round_kill_rate", 0) > (0.05 if etype == "normal" else 0.02):
        issues.append(f"首回合清场率 {summary['first_round_kill_rate']:.1%} 偏高")
    if summary.get("healing_overflow_rate", 0) > 0.30:
        issues.append(f"治疗溢出率 {summary['healing_overflow_rate']:.0%} 偏高")
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--encounters", default="")
    ap.add_argument("--teams", default="standard,command,low")
    ap.add_argument("--json", default=RESULTS_JSON)
    ap.add_argument("--seed-base", type=int, default=20260912)
    ap.add_argument("--store-runs", action="store_true",
                    help="同时保存逐场明细（默认只存汇总，避免大文件入库）")
    ap.add_argument("--force", action="store_true",
                    help="允许局部跑（--encounters/--teams 受限）覆盖标准报告文件")
    args = ap.parse_args()

    # 防呆：局部跑默认不得覆盖标准报告，避免冒烟测试盖掉完整验收数据
    partial = bool(args.encounters) or args.teams != "standard,command,low" or args.runs < 30
    if partial and not args.force and os.path.abspath(args.json) == os.path.abspath(RESULTS_JSON):
        print("检测到局部跑，拒绝覆盖标准报告；如需覆盖请加 --force 或指定 --json <其它路径>")
        return

    loader = CombatDataLoader()
    wanted = [e for e in args.encounters.split(",") if e]
    teams = [t for t in args.teams.split(",") if t]

    node_ids = [n["node_id"] for n in loader.list_nodes()]
    if wanted:
        node_ids = [n for n in node_ids if n in wanted]

    results = {}
    for node_id in node_ids:
        encounter = loader.load_node(node_id)
        difficulty = (encounter or {}).get("difficulty") or {}
        etype = difficulty.get("encounter_type", "normal")
        for team in teams:
            rows = []
            for i in range(args.runs):
                rows.append(simulate_battle(encounter, team, args.seed_base + i, loader))
            summary = summarise(rows)
            summary["issues"] = target_check(etype, summary, encounter)
            results[f"{node_id}|{team}"] = {
                "encounter_id": node_id,
                "encounter_type": etype,
                "power_tier": difficulty.get("band", ""),
                "target_rounds": difficulty.get("target_rounds"),
                "threat_budget": difficulty.get("threat_budget"),
                "team": team,
                "summary": summary,
            }
            if args.store_runs:
                results[f"{encounter_id}|{team}"]["runs"] = rows

    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    lines = ["# 战斗数值迁移模拟报告（balance_version 1）", "",
             f"- 固定种子基数：{args.seed_base}，每组 {args.runs} 次",
             f"- 队伍原型：{', '.join(teams)}",
             f"- 玩家策略：确定性启发式（治疗优先救命 → 最高 CV 出牌 → 余 AP 靠拢）",
             "",
             "| 遭遇 | 类型 | 队伍 | 胜率 | 中位回合 | P90 | 均值 | 首回合清场 | 治疗溢出 | 血损率 | 每轮出牌AP | 每轮移动AP | 敌每轮动作 | 偏差 |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for key, data in results.items():
        s = data["summary"]
        issues = "；".join(s["issues"]) or "达标"
        lines.append(f"| {data['encounter_id']} | {data['encounter_type']} | {data['team']} | "
                     f"{s['win_rate']:.0%} | {s['median_rounds']} | {s['p90_rounds']} | "
                     f"{s['mean_rounds']} | {s['first_round_kill_rate']:.0%} | "
                     f"{s['healing_overflow_rate']:.0%} | {s['hp_loss_rate']:.0%} | "
                     f"{s['player_card_ap_per_round']} | {s['player_move_ap_per_round']} | "
                     f"{s['enemy_actions_per_round']} | {issues} |")
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"simulated {len(results)} combinations -> {args.json}")
    for key, data in results.items():
        s = data["summary"]
        flag = "" if not s["issues"] else "  [!] " + "；".join(s["issues"])
        print(f"  {data['encounter_id']:24} {data['team']:9} win={s['win_rate']:.0%} "
              f"med={s['median_rounds']:>4} p90={s['p90_rounds']:>3} "
              f"hp_loss={s['hp_loss_rate']:.0%}{flag}")

    # 跨队功率方差（design §11 P1-5：同阶段中位回合差 ≤2、胜率差 ≤20 个百分点）
    print("team spread:")
    for encounter_id in node_ids:
        rows = [results.get(f"{encounter_id}|{t}") for t in teams]
        rows = [r for r in rows if r]
        if len(rows) < 2:
            continue
        medians = [r["summary"]["median_rounds"] for r in rows]
        wins = [r["summary"]["win_rate"] for r in rows]
        print(f"  {encounter_id:24} median {min(medians)}–{max(medians)} "
              f"(Δ{max(medians) - min(medians):g}), win Δ{max(wins) - min(wins):.0%}")


if __name__ == "__main__":
    main()
