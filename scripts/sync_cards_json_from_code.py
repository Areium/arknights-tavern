"""
一次性迁移脚本：将运行时硬编码卡表（combat_engine.card_data）同步到
data/classes/<职业>/cards.json，补齐 effects/ignore_def/cleanse 与成长方案 v1
新增字段（rank/upgrade_branch/exhaust/power_tier/cv_budget/cv_estimated/
balance_version），并重算 _hash。

同时把迁移前的 Python 旧表快照到 perf_tests/cards_python_snapshot.json，
供等价性测试验证「JSON 与旧表逐字段一致」。

必须在 card_data.py 切换到 JSON 加载器之前运行：
    python scripts/sync_cards_json_from_code.py
"""
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "src"))

import combat_engine.card_data as cd  # noqa: E402

CLASS_DIR = os.path.join(_ROOT, "data", "classes")
SNAPSHOT = os.path.join(_ROOT, "perf_tests", "cards_python_snapshot.json")

# 成长方案 v1 默认元数据（假设，见交付说明）
DEFAULT_META = {
    "rank": 0,
    "upgrade_branch": "",
    "exhaust": None,
    "balance_version": 1,
}


def compute_hash(data: dict) -> str:
    payload = {k: v for k, v in data.items() if k != "_hash"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def card_to_json(card) -> dict:
    d = card.to_dict()
    d["power_tier"] = "T2" if d.get("tier") == "elite" else "T1"  # 假设：精英卡归 T2
    d["cv_budget"] = 24 * int(d.get("cost", 1))                    # 24 CV/AP × 1.00 品质系数
    d["cv_estimated"] = 0.0                                        # 由 CV 审计脚本回填
    d.update(DEFAULT_META)
    return d


def main():
    report = {}
    snapshot = {}
    for char_class, cards in cd.CLASS_CARD_POOLS.items():
        path = os.path.join(CLASS_DIR, char_class, "cards.json")
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        old_ids = [c.get("card_id") for c in doc.get("cards", [])]
        new_ids = [c.card_id for c in cards]
        json_only = [i for i in old_ids if i not in new_ids]
        code_only = [i for i in new_ids if i not in old_ids]

        doc["cards"] = [card_to_json(c) for c in cards]
        doc["version"] = 1
        doc["_hash"] = compute_hash(doc)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        snapshot[char_class] = [c.to_dict() for c in cards]
        report[char_class] = {"json_only": json_only, "code_only": code_only,
                              "cards": len(cards)}
        print(f"{char_class}: wrote {len(cards)} cards; "
              f"json_only={json_only or '-'} code_only={code_only or '-'}")

    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"snapshot -> {SNAPSHOT}")


if __name__ == "__main__":
    main()
