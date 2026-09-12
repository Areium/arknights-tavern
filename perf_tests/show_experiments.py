"""打印 results_combat_experiments.json 的摘要统计。"""
import json
import sys

d = json.load(open(sys.argv[1] if len(sys.argv) > 1
                    else "perf_tests/results_combat_experiments.json", encoding="utf-8"))
for e in d["experiments"]:
    print(e["label"])
    print(f"  trigger_recall: {e['trigger_recall']} ({e['triggered']}/{e['expected_combat']})")
    print(f"  classification: {e['classification']}")
    print(f"  finish_reasons: {e['finish_reasons']}")