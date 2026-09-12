"""校验战斗规格 JSON（LLM / 设计者产出的候选节点），不落盘、不依赖会话。

用法::

    python3 tools/validate_battle_spec.py spec.json          # 单个节点
    python3 tools/validate_battle_spec.py specs/*.json       # 批量
    python3 tools/validate_battle_spec.py spec.json --json    # 机器可读输出
    cat spec.json | python3 tools/validate_battle_spec.py -   # 从 stdin

退出码：0 = 无错误（警告不影响）；1 = 存在错误。适合放进生成循环做门禁：
`生成 → 校验 → 试跑 → 人工审阅 → 入库`。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from combat_data_loader import CombatDataLoader  # noqa: E402
from combat_nodes import NodeError, validate_node  # noqa: E402


def _load_specs(paths: list[str]) -> list[tuple[str, dict]]:
    specs: list[tuple[str, dict]] = []
    for raw in paths:
        if raw == "-":
            data = json.load(sys.stdin)
            if isinstance(data, list):
                specs += [(f"<stdin>[{i}]", item) for i, item in enumerate(data)]
            else:
                specs.append(("<stdin>", data))
            continue
        path = Path(raw)
        if not path.is_file():
            raise NodeError(f"文件不存在: {raw}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            specs += [(f"{path.name}[{i}]", item) for i, item in enumerate(data)]
        else:
            specs.append((path.name, data))
    return specs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="规格 JSON 路径（- 表示 stdin）")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = ap.parse_args()

    try:
        specs = _load_specs(args.paths)
    except (NodeError, ValueError) as exc:
        print(f"读取失败: {exc}", file=sys.stderr)
        return 1

    loader = CombatDataLoader()
    enemy_names = set(loader.list_enemy_names())
    results = []
    failed = 0

    for label, spec in specs:
        report = validate_node(spec, enemy_names=enemy_names)
        node_id = spec.get("node_id", label)
        threat = (report.get("metrics") or {}).get("threat") or {}
        results.append({
            "label": label,
            "node_id": node_id,
            "name": spec.get("name", ""),
            "errors": report["errors"],
            "warnings": report["warnings"],
            "threat": threat.get("total"),
            "threat_budget": threat.get("declared_budget"),
            "band": threat.get("declared_band") or "",
            "band_hint": threat.get("band_hint") or "",
            "units": threat.get("units"),
            "ok": not report["errors"],
        })
        if report["errors"]:
            failed += 1

    if args.json:
        print(json.dumps({"results": results, "failed": failed}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            status = "OK  " if r["ok"] else "FAIL"
            threat = (f"威胁 {r['threat']}" if r["threat"] is not None else "")
            band = (f"阶段带 {r['band'] or '-'}"
                    + (f"（推荐 {r['band_hint']}）" if r["band_hint"] else ""))
            print(f"[{status}] {r['node_id']} · {r['name']} · {threat} · {band}")
            for e in r["errors"]:
                print(f"        ✖ {e}")
            for w in r["warnings"]:
                print(f"        ⚠ {w}")

    if failed:
        print(f"\n{failed}/{len(results)} 个规格未通过校验", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
