"""从 results_combat_experiments.json 提取未触发（非 triggered）案例清单。"""
import json
import sys

d = json.load(open(sys.argv[1] if len(sys.argv) > 1
                    else "perf_tests/results_combat_experiments.json", encoding="utf-8"))
for e in d["experiments"]:
    print(f"=== {e['label']} ===")
    for c in e["cases"]:
        if c["class"] != "triggered":
            print(f"  [{c['class']}] {c['narrative']}  finish={c['finish_reason']}")