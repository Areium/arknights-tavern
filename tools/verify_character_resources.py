#!/usr/bin/env python3
"""角色资源补全验证器 —— 逐条核对四个子项。

用法：
    python tools/verify_character_resources.py [--book arknights] [--json]

核对项：
  1. 世界书条目覆盖：每个角色实体在 data/packs/<book>.json 中都有对应条目
  2. 立绘：每个角色实体都有 avatar / skin / card_face 三类图像
  3. Spine：每个角色实体的 spine/ 目录含完整的 Front|Back × (skel|atlas|png)
  4. 世界书归属：每个角色实体 index.md frontmatter 的 worldbook_id == <book>
  5. 前端生效：有 spine 素材的角色必须在 PixiCombatScene.tsx 的 SPINE_VARIANT
     中注册，且注册的变体目录确实存在（文件就位 ≠ 生效，未注册则回退令牌）

退出码 0 表示「必需项」全部通过（已知例外单独列出，不计为失败）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import frontmatter

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_CHARS = REPO_ROOT / "data" / "characters"
PACKS_DIR = REPO_ROOT / "data" / "packs"
WORLDBOOKS_DIR = REPO_ROOT / "data" / "worldbooks"
PIXI_SCENE = REPO_ROOT / "frontend" / "src" / "components" / "combat" / "PixiCombatScene.tsx"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

# 已知例外（无对应游戏素材，属可接受缺口；不计入失败）
#   - 博士：玩家角色，官方无半身立绘/精二立绘
#   - 大长老 / 菈塔托丝·布朗陶 / 阿克托斯·佩尔罗契 / 托兰：剧情 NPC，官方无干员素材
NO_SKIN_EXCEPTIONS = {"博士"}
NO_SPINE_EXCEPTIONS = {"博士", "大长老", "菈塔托丝·布朗陶", "阿克托斯·佩尔罗契", "托兰"}
PLACEHOLDER_MARKERS = ("placeholder_",)


def _count_images(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def _has_complete_spine(spine_dir: Path) -> tuple[bool, int]:
    """返回 (是否有任一完整变体, 变体数)。"""
    if not spine_dir.is_dir():
        return False, 0
    variants = 0
    complete = False
    for variant in sorted(p for p in spine_dir.iterdir() if p.is_dir()):
        fn = variant.name
        # 嵌套路径：char_4064_mlynar/char_4064_mlynar_iteration_3 —— 取 basename
        files = [
            variant / d / (fn + ext)
            for d in ("Front", "Back")
            for ext in (".skel", ".atlas", ".png")
        ]
        if all(f.is_file() for f in files):
            complete = True
            variants += 1
        elif any(f.is_file() for f in files):
            variants += 1
    return complete, variants


def _parse_spine_variant_map(text: str) -> dict[str, str]:
    """从 PixiCombatScene.tsx 解析 SPINE_VARIANT（干员）映射。

    只取顶层 SPINE_VARIANT 对象字面量，忽略 ENEMY_SPINE_VARIANT 与注释。
    """
    m = re.search(r"const SPINE_VARIANT: Record<string, string> = \{(.*?)\n\};", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        mm = re.match(r'^"([^"]+)"\s*:\s*"([^"]+)"\s*,?$', line)
        if mm:
            out[mm.group(1)] = mm.group(2)
    return out


def _variant_files_exist(char_dir: Path, variant: str) -> bool:
    """注册的变体（可能嵌套路径）在角色 spine/ 下三件套是否齐全。"""
    fn = variant.split("/")[-1]
    vdir = char_dir / "spine" / variant
    return all(
        (vdir / d / (fn + ext)).is_file()
        for d in ("Front", "Back")
        for ext in (".skel", ".atlas", ".png")
    )


def _runtime_drift(book: str, pack_uids: set[str]) -> dict:
    """运行时世界书（data/worldbooks/，首次启动自动安装）是否落后于分发包。

    未安装 → 首次启动会自动安装，不算漂移。
    已安装但缺 uid → 该内容不会生效（需重装：POST /api/worldbook/<id>/reinstall）。
    """
    p = WORLDBOOKS_DIR / f"{book}.json"
    if not p.is_file():
        return {"installed": False, "total": 0, "missing_uids": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"installed": False, "total": 0, "missing_uids": []}
    rt = {e.get("uid", "") for e in data.get("entries", [])}
    return {
        "installed": True,
        "total": len(rt),
        "missing_uids": sorted(pack_uids - rt),
    }


def collect(book: str) -> dict:
    entities = sorted(
        d for d in DATA_CHARS.iterdir()
        if d.is_dir() and (d / "index.md").is_file()
    )

    # 世界书条目
    pack_path = PACKS_DIR / f"{book}.json"
    pack_entries = []
    if pack_path.is_file():
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        pack_entries = pack.get("entries", [])
    char_uids = {e.get("uid", "") for e in pack_entries if e.get("group") == "角色"}
    all_pack_uids = {e.get("uid", "") for e in pack_entries if e.get("uid")}

    # 前端注册表（有 spine 素材但未注册 = 不生效）
    spine_map = (
        _parse_spine_variant_map(PIXI_SCENE.read_text(encoding="utf-8"))
        if PIXI_SCENE.is_file() else {}
    )

    rows = []
    for d in entities:
        name = d.name
        meta = frontmatter.load(d / "index.md").metadata
        avatar = _count_images(d / "avatar")
        skin = _count_images(d / "skin")
        card = _count_images(d / "card_face")
        spine_ok, spine_variants = _has_complete_spine(d / "spine")
        variant = spine_map.get(name)
        uid = f"characters_{name}_index"

        # 图像指针：frontmatter 字段 → 实体子目录中的文件
        ptr = {}
        for field, sub in (("default_avatar", "avatar"),
                           ("default_skin", "skin"),
                           ("card_face", "card_face")):
            val = str(meta.get(field) or "").strip()
            ptr[field] = {"set": bool(val), "resolves": bool(val) and (d / sub / val).is_file()}

        rows.append({
            "name": name,
            "worldbook_id": str(meta.get("worldbook_id") or ""),
            "has_entry": uid in char_uids,
            "entry_uid": uid,
            "avatar": avatar,
            "skin": skin,
            "card_face": card,
            "placeholder": any(m in f for f in (avatar + skin + card)
                               for m in PLACEHOLDER_MARKERS),
            "spine_ok": spine_ok,
            "spine_variants": spine_variants,
            "spine_variant": variant or "",
            "spine_registered": variant is not None,
            "spine_registered_ok": bool(variant) and _variant_files_exist(d, variant),
            "pointers": ptr,
            # card_face/ 有图但字段未设 → 文件就位却不会被 find_card_face_path 读取
            "card_face_dead": bool(card) and not ptr["card_face"]["set"],
            "pointer_broken": [f for f, p in ptr.items() if p["set"] and not p["resolves"]],
        })
    return {
        "book": book,
        "pack": str(pack_path.relative_to(REPO_ROOT)),
        "entities": rows,
        "spine_map_size": len(spine_map),
        "all_pack_uids": all_pack_uids,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="arknights")
    ap.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = ap.parse_args()

    data = collect(args.book)
    rows = data["entities"]
    total = len(rows)

    # ── 1. 世界书条目覆盖 ──
    covered = [r for r in rows if r["has_entry"]]
    missing_entries = [r["name"] for r in rows if not r["has_entry"]]

    # ── 2. 立绘 ──
    art_missing = [r["name"] for r in rows
                   if not (r["avatar"] and r["skin"] and r["card_face"])]
    art_missing_hard = [n for n in art_missing if n not in NO_SKIN_EXCEPTIONS]
    placeholders = [r["name"] for r in rows if r["placeholder"]]

    # ── 3. Spine ──
    spine_ok = [r["name"] for r in rows if r["spine_ok"]]
    spine_missing = [r["name"] for r in rows if not r["spine_ok"]]
    spine_missing_hard = [n for n in spine_missing if n not in NO_SPINE_EXCEPTIONS]

    # ── 4. 世界书归属 ──
    attributed = [r["name"] for r in rows if r["worldbook_id"] == args.book]
    unattributed = [r["name"] for r in rows if r["worldbook_id"] != args.book]

    # ── 5. 前端生效（有 spine 素材 → 必须在 SPINE_VARIANT 注册且变体齐全）──
    spine_unregistered = [r["name"] for r in rows
                          if r["spine_ok"] and not r["spine_registered"]]
    spine_broken = [r["name"] for r in rows
                    if r["spine_registered"] and not r["spine_registered_ok"]]
    spine_live = [r["name"] for r in rows if r["spine_registered_ok"]]

    # ── 6. 运行时同步（分发包 → 已安装世界书）──
    drift = _runtime_drift(args.book, data["all_pack_uids"])
    runtime_synced = (not drift["installed"]) or (not drift["missing_uids"])

    # ── 7. 图像指针（frontmatter 字段必须指向真实文件）──
    dead_card_face = [r["name"] for r in rows if r["card_face_dead"]]
    broken_pointers = [(r["name"], f) for r in rows for f in r["pointer_broken"]]
    pointers_ok = not dead_card_face and not broken_pointers

    checks = {
        "worldbook_entries": not missing_entries,
        "portraits": not art_missing_hard,
        "spine": not spine_missing_hard,
        "attribution": not unattributed,
        "spine_registered": not spine_unregistered and not spine_broken,
        "runtime_synced": runtime_synced,
        "image_pointers": pointers_ok,
    }
    ok = all(checks.values())

    result = {
        "book": args.book,
        "total_characters": total,
        "checks": checks,
        "worldbook_entries": {
            "covered": len(covered), "total": total, "missing": missing_entries,
        },
        "portraits": {
            "complete": total - len(art_missing), "total": total,
            "missing": art_missing, "placeholders": placeholders,
        },
        "spine": {
            "complete": len(spine_ok), "total": total,
            "missing": spine_missing, "exceptions": sorted(NO_SPINE_EXCEPTIONS),
        },
        "attribution": {
            "attributed": len(attributed), "total": total, "missing": unattributed,
        },
        "spine_live": {
            "registered": len(spine_live), "total": total,
            "unregistered": spine_unregistered, "broken": spine_broken,
            "map_size": data["spine_map_size"],
        },
        "runtime_sync": {
            "installed": drift["installed"], "total": drift["total"],
            "pack_total": len(data["all_pack_uids"]),
            "missing_uids": drift["missing_uids"],
        },
        "image_pointers": {
            "card_face_set": sum(1 for r in rows if r["pointers"]["card_face"]["set"]),
            "dead_card_face": dead_card_face,
            "broken": broken_pointers,
        },
        "detail": rows,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    print(f"=== 角色资源验证 · 世界书「{args.book}」 ===")
    print(f"角色实体总数：{total}\n")

    print(f"[1] 世界书条目覆盖：{len(covered)}/{total} "
          f"{'PASS' if checks['worldbook_entries'] else 'FAIL'}")
    if missing_entries:
        print(f"    缺条目：{missing_entries}")

    print(f"[2] 立绘（avatar+skin+card_face）：{total - len(art_missing)}/{total} "
          f"{'PASS' if checks['portraits'] else 'FAIL'}")
    if art_missing:
        print(f"    缺立绘：{art_missing}")
    if placeholders:
        print(f"    占位图（待美术替换）：{placeholders}")

    print(f"[3] Spine（完整 Front/Back 三件套）：{len(spine_ok)}/{total} "
          f"{'PASS' if checks['spine'] else 'FAIL'}")
    if spine_missing:
        print(f"    缺 Spine：{spine_missing}")
        print(f"    已知例外（官方无素材）：{sorted(NO_SPINE_EXCEPTIONS)}")

    print(f"[4] 世界书归属 worldbook_id={args.book}：{len(attributed)}/{total} "
          f"{'PASS' if checks['attribution'] else 'FAIL'}")
    if unattributed:
        print(f"    未归属：{unattributed}")

    print(f"[5] 前端生效（SPINE_VARIANT 注册且变体齐全）：{len(spine_live)}/{total} "
          f"{'PASS' if checks['spine_registered'] else 'FAIL'}")
    if spine_unregistered:
        print(f"    有素材但未注册（会回退令牌）：{spine_unregistered}")
    if spine_broken:
        print(f"    已注册但变体文件不全：{spine_broken}")

    rt = drift
    if not rt["installed"]:
        print(f"[6] 运行时世界书同步：未安装（首次启动自动安装）SKIP")
    else:
        print(f"[6] 运行时世界书同步：{rt['total']}/{len(data['all_pack_uids'])} 条 "
              f"{'PASS' if runtime_synced else 'FAIL'}")
        if rt["missing_uids"]:
            print(f"    已安装副本缺 {len(rt['missing_uids'])} 条（不会生效）：{rt['missing_uids'][:8]}")
            print(f"    修复：POST /api/worldbook/{args.book}/reinstall")

    n_cf = sum(1 for r in rows if r["pointers"]["card_face"]["set"])
    print(f"[7] 图像指针（default_avatar/default_skin/card_face）：{n_cf}/{total} 已设 card_face "
          f"{'PASS' if pointers_ok else 'FAIL'}")
    if dead_card_face:
        print(f"    card_face/ 有图但字段未设（不会被读取）：{dead_card_face}")
    if broken_pointers:
        print(f"    字段指向不存在的文件：{broken_pointers}")

    print(f"\n{'全部必需项通过 ✔' if ok else '存在未通过项 ✘'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
