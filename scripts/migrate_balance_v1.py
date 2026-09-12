"""
敌人分层与遭遇威胁预算迁移（design §8 / §11 P1-2、P1-3）。

用法：
    python scripts/migrate_balance_v1.py            # 只出报告
    python scripts/migrate_balance_v1.py --apply    # 写回 data/combat/**

内容：
1. 敌人按 §8.1 五类模板分类（相对生命 / 相对单次输出最近邻），写入
   power_tier / role / action_slots / threat_points / expected_dpr /
   expected_effective_hp / balance_version；elite/boss 行动槽为 2；
2. 敌人 xp_reward 按威胁点重算（threat × 10，T3+ ×12），保证
   「敌人 XP 与威胁点单调相关」（§12 硬性测试第 5 条）；
3. 遭遇写入 encounter_type / recommended_power_tier / target_rounds /
   threat_budget / balance_version，并按 §1.1 收敛 max_rounds
   （教学 6 / 普通 8 / 精英 10 / Boss 12）；
4. 遭遇 rewards.xp 按 §9.2 阶段带重写：最终 XP = 遭遇基础 XP + 0.35 × 敌人 XP，
   落在该类型/阶段的奖励带内。

假设（已在报告中标注）：
- 敌人分类阈值取 §8.1 各模板「相对生命/相对输出」区间的中值最近邻；
- 山雪鬼队长在圣山决战中承担章节主敌职责，人工提升为 elite（2 行动槽），
  数值抬入 §8.1 精英带（HP 1.6–2.0 倍标准、输出 1.15–1.35 倍标准）；
- 遭遇阶段由 difficulty 映射：1→T0、2→T0/T1、3→T1、4→T2、5→T3；
- 遭遇类型由 id/组成推断，见 ENCOUNTER_TYPES。
"""
import argparse
import glob
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "src"))

ROOT_PATH = _ROOT
REPORT_MD = os.path.join(_ROOT, "perf_tests", "balance_migration_report.md")
REPORT_JSON = os.path.join(_ROOT, "perf_tests", "balance_migration.json")

BALANCE_VERSION = 1

# §8.1 五类模板：(相对生命中值, 相对输出中值, 威胁点, 行动槽)
TEMPLATES = {
    "minion": (0.675, 0.725, 1.0, 1),
    "standard": (1.000, 1.000, 1.6, 1),
    "strong": (1.375, 1.175, 2.2, 1),
    "elite": (1.800, 1.250, 3.2, 2),
    "boss": (4.250, 1.350, 7.0, 2),
}
STD_HP, STD_OUTPUT = 100.0, 20.0

# 人工覆盖（模板分类之外的设计决策）
ROLE_OVERRIDES = {
    "山雪鬼队长": {"role": "elite", "power_tier": "T3",
                   "combat_stats": {"hp": 170, "patk": 34}},
}

# 遭遇类型 → (目标回合, max_rounds)
ENCOUNTER_TYPE_RULES = {
    "enc_quick_test_1": "teaching",
    "enc_quick_test_2": "teaching",
    "enc_quick_test_3": "teaching",
    "enc_training": "teaching",
    "enc_snow_convoy": "teaching",
    "enc_first_reunion": "normal",
    "enc_elite_hunt": "elite",
    "enc_final_showdown": "boss",
}
TYPE_ROUNDS = {
    "teaching": (3, 6),
    "normal": (5, 8),
    "elite": (6, 10),
    "boss": (8, 12),
}

# difficulty → 建议阶段
DIFFICULTY_TIER = {1: "T0", 2: "T1", 3: "T1", 4: "T2", 5: "T3"}

# §9.2 阶段奖励带（普通 / 精英 / Boss）
XP_BANDS = {
    "T0": {"normal": (35, 50), "elite": (65, 80), "boss": (120, 160)},
    "T1": {"normal": (50, 70), "elite": (90, 120), "boss": (160, 220)},
    "T2": {"normal": (70, 95), "elite": (125, 165), "boss": (220, 300)},
    "T3": {"normal": (90, 125), "elite": (165, 220), "boss": (300, 400)},
    "T4": {"normal": (120, 160), "elite": (220, 300), "boss": (400, 520)},
}
ENEMY_XP_PER_THREAT = 10.0
ENEMY_XP_PER_THREAT_HIGH = 12.0   # T3/T4 敌人
ENEMY_XP_WEIGHT = 0.35            # 与 combat_settlement.ENEMY_XP_WEIGHT 一致
# 教学战没有独立奖励带（方案 §9.2 未列），按同阶段普通战带的 60% 取（假设）
TEACHING_BAND_MULT = 0.6


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _insert_after(text: str, anchor_re: str, lines: list[str]) -> str:
    """在首个匹配 anchor_re 的行后插入若干 YAML 行（幂等：已存在则跳过）。"""
    remaining = [ln for ln in lines if not re.search(rf"^{re.escape(ln.split(':')[0])}:", text, re.M)]
    if not remaining:
        return text
    m = re.search(anchor_re, text, re.M)
    if not m:
        raise SystemExit(f"anchor not found: {anchor_re}")
    insert_at = text.find("\n", m.end()) + 1
    return text[:insert_at] + "\n".join(remaining) + "\n" + text[insert_at:]


def _replace_key(text: str, key_re: str, new_line: str) -> str:
    if re.search(key_re, text, re.M):
        return re.sub(key_re, new_line, text, count=1, flags=re.M)
    return text


def classify_enemy(meta: dict) -> dict:
    """按 §8.1 相对生命/相对输出最近邻分类，返回 role/tier/threat 等。"""
    stats = meta.get("combat_stats", {}) or {}
    hp = float(stats.get("hp", 100) or 100)
    patk = float(stats.get("patk", 20) or 20)
    defense = float(stats.get("defense", 5) or 5)
    dpr = 0.5 * patk + 7.5                     # enemy_atk 期望伤害
    ehp = hp * (1 + defense / 20.0)            # 含防御的有效生命
    hp_rel = hp / STD_HP
    out_rel = dpr / STD_OUTPUT

    best_role, best_dist = "standard", 1e9
    for role, (hp_mid, out_mid, _, _) in TEMPLATES.items():
        dist = abs(hp_rel - hp_mid) / hp_mid + abs(out_rel - out_mid) / out_mid
        if dist < best_dist:
            best_role, best_dist = role, dist

    _, _, threat, slots = TEMPLATES[best_role]
    name = meta.get("name", "")
    override = ROLE_OVERRIDES.get(name)
    if override:
        best_role = override["role"]
        _, _, threat, slots = TEMPLATES[best_role]

    tier = DIFFICULTY_TIER.get(int(meta.get("level", 1) or 1), "T1")
    if override and override.get("power_tier"):
        tier = override["power_tier"]

    return {
        "role": best_role,
        "power_tier": tier,
        "action_slots": slots,
        "threat_points": threat,
        "relative_hp": round(hp_rel, 2),
        "relative_output": round(out_rel, 2),
        "expected_dpr": round(dpr, 1),
        "expected_effective_hp": round(ehp, 1),
        "distance": round(best_dist, 3),
        "override": override,
    }


def migrate_enemy(path: str, apply: bool) -> dict:
    import frontmatter
    meta = frontmatter.load(path).metadata
    info = classify_enemy(meta)
    per_threat = (ENEMY_XP_PER_THREAT_HIGH
                  if info["power_tier"] in ("T3", "T4") else ENEMY_XP_PER_THREAT)
    new_xp = int(round(info["threat_points"] * per_threat))

    text = _read(path)
    lines = [
        f'power_tier: "{info["power_tier"]}"',
        f'role: "{info["role"]}"',
        f'action_slots: {info["action_slots"]}',
        f'threat_points: {info["threat_points"]}',
        f'expected_dpr: {info["expected_dpr"]}',
        f'expected_effective_hp: {info["expected_effective_hp"]}',
        f"balance_version: {BALANCE_VERSION}",
    ]
    new_text = _insert_after(text, r"^level:.*$", lines)
    new_text = _replace_key(new_text, r"^xp_reward:.*$", f"xp_reward: {new_xp}")

    if info["override"] and info["override"].get("combat_stats"):
        for key, value in info["override"]["combat_stats"].items():
            new_text = _replace_key(new_text, rf"^(\s+){key}:.*$", rf"\g<1>{key}: {value}")

    if apply and new_text != text:
        _write(path, new_text)

    return {"file": os.path.basename(path), "name": meta.get("name", ""),
            "old_xp_reward": meta.get("xp_reward"), "new_xp_reward": new_xp,
            **{k: v for k, v in info.items() if k != "override"},
            "override_applied": bool(info["override"])}


def encounter_type(encounter_id: str, units: int, difficulty: int) -> str:
    if encounter_id in ENCOUNTER_TYPE_RULES:
        return ENCOUNTER_TYPE_RULES[encounter_id]
    if units >= 8:
        return "elite"
    return "normal"


def migrate_encounter(path: str, enemy_threats: dict, apply: bool) -> dict:
    import frontmatter
    meta = frontmatter.load(path).metadata
    encounter_id = meta.get("encounter_id", "")
    difficulty = int(meta.get("difficulty", 1) or 1)
    waves = meta.get("waves", []) or []

    units = 0
    threat_total = 0.0
    enemy_xp_total = 0
    for wave in waves:
        for entry in (wave.get("enemies") or []):
            count = int(entry.get("count", 1) or 1)
            name = entry.get("enemy") or entry.get("name") or ""
            units += count
            info = enemy_threats.get(name)
            if info:
                threat_total += info["threat_points"] * count
                enemy_xp_total += info["new_xp_reward"] * count

    etype = encounter_type(encounter_id, units, difficulty)
    tier = DIFFICULTY_TIER.get(difficulty, "T1")
    target_rounds, max_rounds = TYPE_ROUNDS[etype]

    band = XP_BANDS[tier].get(etype) or XP_BANDS[tier]["normal"]
    if etype == "teaching":
        band = (round(band[0] * TEACHING_BAND_MULT), round(band[1] * TEACHING_BAND_MULT))
    target_xp = (band[0] + band[1]) / 2.0
    base_xp = max(0, int(round(target_xp - ENEMY_XP_WEIGHT * enemy_xp_total)))
    final_xp = int(round((base_xp + ENEMY_XP_WEIGHT * enemy_xp_total) * 1.0))

    text = _read(path)
    lines = [
        f'encounter_type: "{etype}"',
        f'recommended_power_tier: "{tier}"',
        f"target_rounds: {target_rounds}",
        f"threat_budget: {round(threat_total, 1)}",
        f"balance_version: {BALANCE_VERSION}",
    ]
    new_text = _insert_after(text, r"^difficulty:.*$", lines)
    new_text = _replace_key(new_text, r"^(\s+)max_rounds:.*$", rf"\g<1>max_rounds: {max_rounds}")
    new_text = _replace_key(new_text, r"^(\s+)xp:.*$", rf"\g<1>xp: {base_xp}")

    if apply and new_text != text:
        _write(path, new_text)

    return {
        "file": os.path.basename(path),
        "encounter_id": encounter_id,
        "encounter_type": etype,
        "power_tier": tier,
        "difficulty": difficulty,
        "units": units,
        "threat_budget": round(threat_total, 1),
        "old_xp": (meta.get("rewards") or {}).get("xp"),
        "enemy_xp_weighted": round(ENEMY_XP_WEIGHT * enemy_xp_total, 1),
        "new_base_xp": base_xp,
        "final_xp": final_xp,
        "xp_band": band,
        "target_rounds": target_rounds,
        "max_rounds": max_rounds,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    enemy_files = sorted(glob.glob(os.path.join(ROOT_PATH, "data/combat/enemies/*.md")))
    enemies = []
    for path in enemy_files:
        enemies.append(migrate_enemy(path, args.apply))
    enemy_threats = {e["name"]: e for e in enemies}

    encounters = []
    for path in sorted(glob.glob(os.path.join(ROOT_PATH, "data/combat/encounters/*.md"))):
        encounters.append(migrate_encounter(path, enemy_threats, args.apply))

    lines = ["# 敌人分层与遭遇预算迁移报告（balance_version 1）", "",
             "## 敌人", "",
             "| 敌人 | 角色 | 阶段 | 行动槽 | 威胁点 | 相对生命 | 相对输出 | XP |",
             "|---|---|---|---:|---:|---:|---:|---:|"]
    for e in sorted(enemies, key=lambda x: -x["threat_points"]):
        lines.append(f"| {e['name']} | {e['role']} | {e['power_tier']} | "
                     f"{e['action_slots']} | {e['threat_points']} | {e['relative_hp']} | "
                     f"{e['relative_output']} | {e['new_xp_reward']} |")
    lines += ["", "## 遭遇", "",
              "| 遭遇 | 类型 | 阶段 | 单位 | 威胁预算 | 旧 XP | 新基础 XP | 最终 XP | 奖励带 | 回合目标 | max_rounds |",
              "|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|"]
    for c in encounters:
        lines.append(f"| {c['encounter_id']} | {c['encounter_type']} | {c['power_tier']} | "
                     f"{c['units']} | {c['threat_budget']} | {c['old_xp']} | "
                     f"{c['new_base_xp']} | {c['final_xp']} | "
                     f"{c['xp_band'][0]}–{c['xp_band'][1]} | {c['target_rounds']} | "
                     f"{c['max_rounds']} |")

    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump({"enemies": enemies, "encounters": encounters}, f,
                  ensure_ascii=False, indent=2)

    print(f"enemies={len(enemies)} encounters={len(encounters)}")
    for e in sorted(enemies, key=lambda x: -x["threat_points"]):
        print(f"  {e['name']:16} {e['role']:9} {e['power_tier']} slots={e['action_slots']} "
              f"threat={e['threat_points']} xp={e['old_xp_reward']}->{e['new_xp_reward']}"
              f"{' (override)' if e['override_applied'] else ''}")
    print("applied" if args.apply else "dry-run (add --apply)")


if __name__ == "__main__":
    main()
