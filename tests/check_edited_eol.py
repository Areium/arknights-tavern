# -*- coding: utf-8 -*-
"""检查改动文件的工作区换行符是否与仓库约定一致（core.autocrlf=true → 工作区 CRLF、blob LF）。"""

import subprocess
import sys

FILES = [
    "src/combat_engine/entity.py",
]
import pathlib  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def changed_files():
    out = subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(ROOT),
                          "diff", "--name-only", "-z"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    return [f for f in out.split("\0") if f.strip()]


def main():
    files = FILES + changed_files()
    if "--samples" in sys.argv:
        files = [
            "data/attributes/战场机动/index.md",
            "data/combat/encounters/初遇整合运动.md",
            "data/combat/TEMPLATE_enemy.md",
            "docs/combat-design.md",
            "src/combat_engine/engine.py",
            "src/combat_engine/grid.py",
            "data/characters/银灰/combat.json",
            "data/classes/近卫/cards.json",
        ]
    print(f"{'文件':<44} {'工作区CRLF':>10} {'工作区裸LF':>10} {'HEAD_CRLF':>10} {'HEAD_LF':>9}")
    bad = []
    for rel in files:
        p = ROOT / rel
        if not p.exists():
            continue
        disk = p.read_bytes()
        blob = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{rel}"],
                              capture_output=True).stdout
        d_crlf = disk.count(b"\r\n")
        d_lf = disk.count(b"\n") - d_crlf
        b_crlf = blob.count(b"\r\n")
        b_lf = blob.count(b"\n") - b_crlf
        flag = ""
        if d_crlf and d_lf:
            flag = "  <== 混合换行"
            bad.append(rel)
        print(f"{rel:<44} {d_crlf:>10} {d_lf:>10} {b_crlf:>10} {b_lf:>9}{flag}")
    print("-" * 90)
    print(f"混合换行文件数: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
