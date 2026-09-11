"""
遭遇威胁重排（design §8.2 / §11 P1-3）。

模拟数据显示：威胁预算超带的遭遇（enc_defense 10.6、enc_elite_hunt 14.8、
enc_festival_eve 11.2 等）在 max_rounds 内清不掉场，胜率跌到 0–43%。
本脚本按 §8.2 五人队威胁带裁剪单位数量，并同步：

- encounter_type 重新判定（出现 elite/boss 模板敌人才算精英/Boss 遭遇，
  不再用「单位数 ≥8」这种与威胁无关的规则）；
- target_rounds / max_rounds 按 §1.1 收敛；
- threats / rewards.xp 按裁剪后的敌人组成重算（保持 §9.2 奖励带）。

用法：
    python scripts/tune_encounters_v1.py            # 报告
    python scripts/tune_encounters_v1.py --apply    # 写回
"""
import argparse
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "src"))

import frontmatter                                                    # noqa: E402
from migrate_balance_v1 import (TYPE_ROUNDS, XP_BANDS,               # noqa: E402
                                ENEMY_XP_WEIGHT, TEACHING_BAND_MULT,
                                DIFFICULTY_TIER, classify_enemy)
import migrate_balance_v1 as mb                                       # noqa: E402

# §8.2 四人队威胁带（按遭遇类型 × 阶段）
THREAT_BANDS = {
    "teaching": {"T0": (2.0, 3.5), "T1": (2.0, 3.5), "T2": (3.0, 4.0),
                 "T3": (3.0, 4.0), "T4": (3.0, 4.0)},
    "normal": {"T0": (5.0, 6.5), "T1": (5.0, 6.5), "T2": (5.5, 7.0),
               "T3": (6.0, 7.5), "T4": (6.0, 7.5)},
    "elite": {"T0": (7.5, 9.5), "T1": (7.5, 9.5), "T2": (8.0, 10.0),
              "T3": (9.0, 11.0), "T4": (9.0, 11.0)},
    "boss": {"T0": (10.0, 12.0), "T1": (10.0, 12.0), "T2": (11.0, 13.0),
             "T3": (12.0, 15.0), "T4": (12.0, 15.0)},
}
TEACHING_EXPLICIT = ("enc_quick_test_1", "enc_quick_test_2", "enc_quick_test_3",
                     "enc_training", "enc_snow_convoy")
BOSS_EXPLICIT = ("enc_final_showdown",)
MAX_UNITS_PER_WAVE = 6          # §8.2：同一波单位数 3–6
# §1.1：多波战 = 每波目标回合 + 波次切换成本；max_rounds 相应放宽
PER_WAVE_ROUNDS = {"teaching": 2, "normal": 3, "elite": 3, "boss": 4}
BASE_MAX_ROUNDS = {"teaching": 6, "normal": 8, "elite": 10, "boss": 12}
WAVE_SWITCH_COST = 1            # 每多一波的切换成本（回合）
MAX_ROUNDS_CAP = 16             # 兜底上限（方案建议上限 12，多波战允许放宽到 16）
REPORT_MD = os.path.join(_ROOT, "perf_tests", "encounter_tuning_report.md")


def round_budget(etype: str, waves: int) -> tuple:
    """多波战目标回合与兜底上限（§1.1）。"""
    waves = max(1, waves)
    target = PER_WAVE_ROUNDS[etype] * waves + WAVE_SWITCH_COST * (waves - 1)
    max_rounds = min(MAX_ROUNDS_CAP, BASE_MAX_ROUNDS[etype] + 2 * (waves - 1))
    return target, max_rounds


def enemy_index() -> dict:
    """敌人名 → 分类信息（含威胁点与新 XP）。"""
    import glob
    index = {}
    for path in glob.glob(os.path.join(_ROOT, "data/combat/enemies/*.md")):
        meta = frontmatter.load(path).metadata
        info = classify_enemy(meta)
        per = (mb.ENEMY_XP_PER_THREAT_HIGH
               if info["power_tier"] in ("T3", "T4") else mb.ENEMY_XP_PER_THREAT)
        index[meta.get("name", "")] = {
            "threat": info["threat_points"],
            "role": info["role"],
            "xp": int(round(info["threat_points"] * per)),
        }
    return index


def total_threat(entries: list, index: dict) -> float:
    return sum(index.get(e["enemy"], {}).get("threat", 1.6) * int(e["count"]) for e in entries)


def total_enemy_xp(entries: list, index: dict) -> int:
    return sum(index.get(e["enemy"], {}).get("xp", 16) * int(e["count"]) for e in entries)


def detect_type(encounter_id: str, entries: list, index: dict) -> str:
    if encounter_id in TEACHING_EXPLICIT:
        return "teaching"
    if encounter_id in BOSS_EXPLICIT:
        return "boss"
    if any(index.get(e["enemy"], {}).get("role") in ("elite", "boss") for e in entries):
        return "elite"
    return "normal"


def trim_entries(entries: list, index: dict, band: tuple) -> tuple:
    """裁剪到威胁带内：先削重复单位，再整体移除低威胁条目（保留 ≥3 个条目）。"""
    lo, hi = band
    work = [dict(e) for e in entries]
    guard = 0
    while total_threat(work, index) > hi and guard < 80:
        guard += 1
        dups = [e for e in work if int(e["count"]) > 1]
        if dups:
            dups.sort(key=lambda e: index.get(e["enemy"], {}).get("threat", 1.6))
            dups[0]["count"] = int(dups[0]["count"]) - 1
            work = [e for e in work if int(e["count"]) > 0]
            continue
        # 全是单条目：整体移除威胁最低的条目（至少保留 3 个、≥2 种敌人）
        if len(work) <= 3 or len({e["enemy"] for e in work}) <= 2:
            break
        lowest = min(range(len(work)),
                     key=lambda i: index.get(work[i]["enemy"], {}).get("threat", 1.6))
        work.pop(lowest)
    return work, total_threat(work, index)


def _rewrite_entries(text: str, new_counts: dict) -> str:
    """按条目重写 count 与 positions（保留 YAML 其余格式）。"""
    lines = text.split("\n")
    current = None
    out = []
    seen = {}
    for line in lines:
        m = re.match(r'^(\s*)- enemy:\s*"(.*)"\s*$', line)
        if m:
            current = m.group(2)
            seen[current] = seen.get(current, 0) + 1
            out.append(line)
            continue
        if current and re.match(r"^\s*count:\s*\d+\s*$", line):
            key = (current, seen[current])
            if key in new_counts:
                indent = re.match(r"^(\s*)", line).group(1)
                out.append(f"{indent}count: {new_counts[key]}")
                continue
        if current and re.match(r"^\s*positions:\s*\[.*\]\s*$", line):
            key = (current, seen[current])
            if key in new_counts:
                indent = re.match(r"^(\s*)", line).group(1)
                positions = re.findall(r"\[(\d+),\s*(\d+)\]", line)
                keep = positions[:new_counts[key]]
                inner = ", ".join(f"[{r}, {c}]" for r, c in keep)
                out.append(f"{indent}positions: [{inner}]")
                continue
        out.append(line)
    return "\n".join(out)


def process(path: str, index: dict, apply: bool) -> dict:
    meta = frontmatter.load(path).metadata
    encounter_id = meta.get("encounter_id", "")
    difficulty = int(meta.get("difficulty", 1) or 1)
    tier = DIFFICULTY_TIER.get(difficulty, "T1")
    waves = meta.get("waves", []) or []

    entries = []
    for wave in waves:
        for entry in (wave.get("enemies") or []):
            entries.append({"enemy": entry.get("enemy") or entry.get("name"),
                            "count": int(entry.get("count", 1) or 1)})

    etype = detect_type(encounter_id, entries, index)
    before = total_threat(entries, index)

    # 逐条目按比例裁剪（同类合并计数后按条目顺序回填）
    band = THREAT_BANDS[etype][tier]
    trimmed, after = trim_entries(entries, index, band)

    new_counts = {}
    seen = {}
    for e in trimmed:
        seen[e["enemy"]] = seen.get(e["enemy"], 0) + 1
        new_counts[(e["enemy"], seen[e["enemy"]])] = int(e["count"])

    enemy_xp = total_enemy_xp(trimmed, index)
    band_xp = XP_BANDS[tier].get(etype) or XP_BANDS[tier]["normal"]
    if etype == "teaching":
        band_xp = (round(band_xp[0] * TEACHING_BAND_MULT), round(band_xp[1] * TEACHING_BAND_MULT))
    target_xp = (band_xp[0] + band_xp[1]) / 2.0
    base_xp = max(0, int(round(target_xp - ENEMY_XP_WEIGHT * enemy_xp)))
    active_waves = sum(1 for w in waves if (w.get("enemies") or []))
    target_rounds, max_rounds = round_budget(etype, active_waves)

    text = frontmatter.load(path).content
    raw = open(path, "r", encoding="utf-8").read()
    new_raw = _rewrite_entries(raw, new_counts)
    new_raw = re.sub(r'^encounter_type:.*$', f'encounter_type: "{etype}"', new_raw, count=1, flags=re.M)
    new_raw = re.sub(r'^recommended_power_tier:.*$', f'recommended_power_tier: "{tier}"',
                     new_raw, count=1, flags=re.M)
    new_raw = re.sub(r'^target_rounds:.*$', f'target_rounds: {target_rounds}',
                     new_raw, count=1, flags=re.M)
    new_raw = re.sub(r'^threat_budget:.*$', f'threat_budget: {round(after, 1)}',
                     new_raw, count=1, flags=re.M)
    new_raw = re.sub(r'^(\s+)max_rounds:.*$', rf'\g<1>max_rounds: {max_rounds}',
                     new_raw, count=1, flags=re.M)
    new_raw = re.sub(r'^(\s+)xp:.*$', rf'\g<1>xp: {base_xp}', new_raw, count=1, flags=re.M)

    if apply and new_raw != raw:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_raw)

    return {
        "file": os.path.basename(path),
        "encounter_id": encounter_id,
        "type_before": meta.get("encounter_type", "normal"),
        "type": etype,
        "tier": tier,
        "threat_before": round(before, 1),
        "threat_after": round(after, 1),
        "band": band,
        "in_band": band[0] <= after <= band[1],
        "units_before": sum(e["count"] for e in entries),
        "units_after": sum(e["count"] for e in trimmed),
        "base_xp": base_xp,
        "target_rounds": target_rounds,
        "max_rounds": max_rounds,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    index = enemy_index()
    import glob
    records = []
    for path in sorted(glob.glob(os.path.join(_ROOT, "data/combat/encounters/*.md"))):
        records.append(process(path, index, args.apply))

    lines = ["# 遭遇威胁重排报告（balance_version 1）", "",
             "| 遭遇 | 类型 | 阶段 | 威胁（前→后） | 目标带 | 单位数 | 基础 XP | 回合 | max |",
             "|---|---|---|---|---|---:|---:|---:|---:|"]
    for r in records:
        lines.append(f"| {r['encounter_id']} | {r['type']} | {r['tier']} | "
                     f"{r['threat_before']} → {r['threat_after']} | "
                     f"{r['band'][0]}–{r['band'][1]} | {r['units_before']}→{r['units_after']} | "
                     f"{r['base_xp']} | {r['target_rounds']} | {r['max_rounds']} |")
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    for r in records:
        flag = "" if r["in_band"] else "  [over]"
        print(f"{r['encounter_id']:24} {r['type']:8} {r['tier']} "
              f"threat {r['threat_before']:>5} -> {r['threat_after']:>4} "
              f"units {r['units_before']}->{r['units_after']}{flag}")
    print("applied" if args.apply else "dry-run (add --apply)")


if __name__ == "__main__":
    main()
