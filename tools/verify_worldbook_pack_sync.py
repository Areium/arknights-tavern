#!/usr/bin/env python3
"""验证预装世界书「按版本自动刷新」的行为（WorldBookManager._ensure_packs_installed）。

覆盖 6 个场景，全部在临时目录里跑，不碰 data/worldbooks/ 真身：

  1. 全新安装        → 安装并写入内容指纹 pack_rev
  2. 幂等            → 重复启动不重写（mtime 不变）
  3. 老副本缺指纹但内容一致 → 只补指纹，不改数据、不留备份
  4. 老副本内容落后  → 刷新为新版本，旧副本留存为 <id>.json.pre-refresh.bak
  5. 同名用户书（source=imported）→ 一律不动
  6. 用户编辑预装书后 → 下次启动不覆盖（编辑保留，指纹随书持久化）

用法：python tools/verify_worldbook_pack_sync.py
退出码 0 = 全部通过。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from world_book import (  # noqa: E402
    SOURCE_PREINSTALLED,
    WorldBookManager,
    _PACKS_DIR,
    _pack_rev,
)

PACK = _PACKS_DIR / "arknights.json"
BOOK_ID = "arknights"

results: list[tuple[bool, str]] = []


def check(name: str, cond: bool, extra: str = ""):
    results.append((cond, name))
    print(f"  {'✓' if cond else '✗'} {name}{('  → ' + extra) if extra else ''}")


def load_pack() -> dict:
    return json.loads(PACK.read_text(encoding="utf-8"))


def write_target(d: Path, data: dict):
    (d / f"{BOOK_ID}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def backup_of(d: Path) -> Path:
    return d / f"{BOOK_ID}.json.pre-refresh.bak"


def fresh_manager() -> tuple[WorldBookManager, Path]:
    d = Path(tempfile.mkdtemp(prefix="wb-sync-"))
    return WorldBookManager(data_dir=d), d


def main() -> int:
    pack = load_pack()
    rev = _pack_rev(pack)
    n = len(pack["entries"])
    print(f"分发源 {PACK.relative_to(REPO_ROOT)}：{n} 条，pack_rev={rev}\n")

    # ── 1. 全新安装 ──
    print("[1] 全新安装")
    mgr, d = fresh_manager()
    mgr._ensure_packs_installed()
    installed = json.loads((d / f"{BOOK_ID}.json").read_text(encoding="utf-8"))
    check("安装后条目数 == 分发源", len(installed["entries"]) == n,
          f"{len(installed['entries'])} vs {n}")
    check("source == preinstalled", installed.get("source") == SOURCE_PREINSTALLED)
    check("写入 pack_rev 且与分发源一致", installed.get("pack_rev") == rev)
    check("未产生备份文件", not backup_of(d).exists())

    # ── 2. 幂等 ──
    print("[2] 重复启动（幂等）")
    mtime_before = (d / f"{BOOK_ID}.json").stat().st_mtime_ns
    mgr2 = WorldBookManager(data_dir=d)
    mgr2._ensure_packs_installed()
    mtime_after = (d / f"{BOOK_ID}.json").stat().st_mtime_ns
    check("安装副本未被重写（mtime 不变）", mtime_before == mtime_after)

    # ── 3. 老副本缺指纹、内容一致 ──
    print("[3] 老安装副本（无 pack_rev 字段，内容其实一致）")
    mgr, d = fresh_manager()
    legacy = {k: v for k, v in pack.items() if k != "pack_rev"}
    legacy["source"] = SOURCE_PREINSTALLED
    write_target(d, legacy)
    before_entries = json.dumps(legacy["entries"], ensure_ascii=False, sort_keys=True)
    WorldBookManager(data_dir=d)._ensure_packs_installed()
    after = json.loads((d / f"{BOOK_ID}.json").read_text(encoding="utf-8"))
    check("补上了 pack_rev", after.get("pack_rev") == rev)
    check("条目内容未变",
          json.dumps(after["entries"], ensure_ascii=False, sort_keys=True) == before_entries)
    check("未产生备份文件", not backup_of(d).exists())

    # ── 4. 老副本内容落后 ──
    print("[4] 老安装副本（条目落后，模拟新增角色条目之前）")
    mgr, d = fresh_manager()
    old = {k: v for k, v in pack.items() if k != "pack_rev"}
    old["entries"] = pack["entries"][: n - 10]
    old["source"] = SOURCE_PREINSTALLED
    write_target(d, old)
    WorldBookManager(data_dir=d)._ensure_packs_installed()
    after = json.loads((d / f"{BOOK_ID}.json").read_text(encoding="utf-8"))
    check("刷新为分发源条目数", len(after["entries"]) == n,
          f"{len(after['entries'])} vs {n}")
    check("写入新 pack_rev", after.get("pack_rev") == rev)
    check("旧副本已留存", backup_of(d).is_file())
    if backup_of(d).is_file():
        bak = json.loads(backup_of(d).read_text(encoding="utf-8"))
        check("备份内容 = 刷新前的旧副本", len(bak["entries"]) == n - 10,
              f"{len(bak['entries'])} 条")

    # ── 5. 同名用户书 ──
    print("[5] 同名用户书（source=imported）")
    mgr, d = fresh_manager()
    user = {"id": BOOK_ID, "name": "我自己写的书", "source": "imported",
            "enabled": True, "entries": [{"uid": "u1", "content": "keep me"}]}
    write_target(d, user)
    WorldBookManager(data_dir=d)._ensure_packs_installed()
    after = json.loads((d / f"{BOOK_ID}.json").read_text(encoding="utf-8"))
    check("用户书未被覆盖", after.get("name") == "我自己写的书"
          and len(after["entries"]) == 1)
    check("未产生备份文件", not backup_of(d).exists())

    # ── 6. 用户编辑预装书后不被覆盖 ──
    print("[6] 用户编辑预装书 → 下次启动不覆盖")
    mgr, d = fresh_manager()
    mgr._ensure_packs_installed()
    book = mgr.load(BOOK_ID)
    book.entries[0].content = "用户改过的内容"
    edited_uid = book.entries[0].uid
    mgr.save(book)
    on_disk = json.loads((d / f"{BOOK_ID}.json").read_text(encoding="utf-8"))
    check("save() 后 pack_rev 仍持久化", on_disk.get("pack_rev") == rev)
    WorldBookManager(data_dir=d)._ensure_packs_installed()
    after = json.loads((d / f"{BOOK_ID}.json").read_text(encoding="utf-8"))
    kept = [e for e in after["entries"] if e.get("uid") == edited_uid]
    check("用户编辑未被覆盖", kept and kept[0].get("content") == "用户改过的内容")
    check("未产生备份文件", not backup_of(d).exists())

    failed = [name for ok, name in results if not ok]
    print(f"\n共 {len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    if failed:
        for f in failed:
            print(f"  - {f}")
        return 1
    print("预装世界书按版本自动刷新：全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
