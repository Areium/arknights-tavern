#!/usr/bin/env python3
"""把「明日方舟」全部六星干员的资源落进 data/characters/。

素材来源（本地镜像，gitignored）：assets/ArknightsGameResource/
  - avatar/<cid>.png / <cid>_2.png     —— 精英0 / 精英2 头像（180×180）
  - skin/<cid>_2b.png                  —— 精英2 立绘（default_skin，卡面回退目标）
  - skin/<cid>_1b.png                  —— 精英1 立绘（--with-e1 才落）
  - gamedata/excel/character_table.json —— 星级 / 职业 / 标签 / 名称
  - gamedata/excel/handbook_info_table.json —— 官方干员档案（基础档案/客观履历/…）

六星口径：character_table.json 中 rarity == 5（0 起算）且 profession 不属于
TOKEN / TRAP（召唤物、装置、陷阱不是干员）。

实体口径（写入 data/characters/<中文名>/）：
  - index.md       —— frontmatter（name/class/race/summary/tags/theme_color/
                      default_avatar/default_skin/worldbook_id）+ 官方档案正文
  - avatar/        —— 头像（default_avatar 指向 <cid>.png）
  - skin/          —— 立绘（default_skin 指向 <cid>_2b.png）
  不建 card_face/：find_card_face_path 在 card_face 字段缺失时回退 default_skin，
  而 default_skin 就是同一张 <cid>_2b.png，再复制一份纯属重复占用体积。

已存在 index.md 的实体一律不覆盖（保留手写内容），只补缺失的图像文件。

用法：
    python tools/import_six_star_resources.py --dry-run          # 只报告，不落盘
    python tools/import_six_star_resources.py --scope standard   # 头像 + 精英2 立绘
    python tools/import_six_star_resources.py --scope full       # 全部皮肤/换装
    python tools/import_six_star_resources.py --json report.json # 覆盖度报告
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIRROR = REPO_ROOT / "assets" / "ArknightsGameResource"
CHAR_DIR = REPO_ROOT / "data" / "characters"
EXCEL = MIRROR / "gamedata" / "excel"

# profession（character_table）→ data/classes/ 目录名
CLASS_CN = {
    "PIONEER": "先锋",
    "WARRIOR": "近卫",
    "TANK": "重装",
    "SNIPER": "狙击",
    "CASTER": "术师",
    "MEDIC": "医疗",
    "SUPPORT": "辅助",
    "SPECIAL": "特种",
}

# 官方档案里【种族】字段的补白（表内偶见空值）
ARCHIVE_RACE_RE = re.compile(r"【种族】\s*([^\s\n【】]+)")


def _load_json(name: str) -> dict:
    return json.loads((EXCEL / name).read_text(encoding="utf-8"))


def _belongs(fn: str, cid: str) -> bool:
    """文件名是否属于角色 cid（避免 char_002_amiya 误吞 char_002_amiya2）。"""
    return fn == cid + ".png" or fn.startswith(cid + "_") or fn.startswith(cid + "#")


def _pool(sub: str) -> list[str]:
    d = MIRROR / sub
    return sorted(p.name for p in d.iterdir() if p.suffix.lower() == ".png") if d.is_dir() else []


def _default_skin(cid: str, pool: list[str]) -> str:
    """default_skin 取值：精英2 立绘 → 精英1 立绘（未实装干员只有精英1）→ 任意立绘。"""
    mine = [f for f in pool if _belongs(f, cid)]
    for cand in (cid + "_2b.png", cid + "_1b.png"):
        if cand in mine:
            return cand
    b = [f for f in mine if f.endswith("b.png")]
    return b[0] if b else ""


def _picked(pool: list[str], cid: str, scope: str) -> list[str]:
    """按 scope 选出该角色要落地的文件。"""
    mine = [f for f in pool if _belongs(f, cid)]
    if scope == "full":
        return mine
    out = [f for f in mine if f in (cid + ".png", cid + "_2.png")]
    if scope in ("standard", "e1"):
        dflt = _default_skin(cid, pool)
        if dflt:
            out.append(dflt)
        if scope == "e1" and (cid + "_1b.png") in mine and (cid + "_1b.png") != dflt:
            out.append(cid + "_1b.png")
    return out


def _archive_sections(handbook: dict, cid: str) -> list[tuple[str, str]]:
    """官方档案 → [(标题, 正文)]，正文去空白行。"""
    entry = handbook.get("handbookDict", {}).get(cid)
    if not entry:
        return []
    out: list[tuple[str, str]] = []
    for item in entry.get("storyTextAudio", []):
        title = str(item.get("storyTitle", "")).strip()
        texts = [
            str(s.get("storyText", "")).strip()
            for s in item.get("stories", [])
            if str(s.get("storyText", "")).strip()
        ]
        if title and texts:
            out.append((title, "\n\n".join(texts)))
    return out


def _race_of(sections: list[tuple[str, str]]) -> str:
    for title, body in sections:
        if title == "基础档案":
            m = ARCHIVE_RACE_RE.search(body)
            if m:
                return m.group(1)
    return ""


def _summary_of(char: dict, sections: list[tuple[str, str]]) -> str:
    """摘要优先级：官方「客观履历」首句 → 招聘文本 itemUsage → 中性兜底。

    注意：character_table.description 是**特性**文案（如「能够阻挡一个敌人」），
    不是人物简介，绝不能拿来当 summary。
    """
    for title, body in sections:
        if title == "客观履历":
            first = re.split(r"[。\n]", body.strip())[0].strip()
            if first:
                return first + "。"
    for key in ("itemUsage", "itemDesc"):
        text = str(char.get(key) or "").strip()
        if text:
            return text if text.endswith(("。", "！", "？")) else text + "。"
    return f"{char.get('name', '')}——罗德岛干员。"


def _theme_color(image: Path) -> str:
    """复用角色头像取色逻辑（src/avatar_color.py）。"""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from src.avatar_color import extract_theme_color  # type: ignore
    except Exception:
        return "#8b5ca8"
    try:
        return extract_theme_color(image)
    except Exception:
        return "#8b5ca8"


# YAML 纯量里必须避免的指示符（出现在任意位置就加引号）
_YAML_UNSAFE = set(":#[]{}&*!|>'\"%@`,\n\t")


def _yaml_scalar(value: str) -> str:
    """frontmatter 标量：含 YAML 指示符或首尾空白时用双引号包裹。"""
    if value and value == value.strip() and not (set(value) & _YAML_UNSAFE):
        return value
    return json.dumps(value, ensure_ascii=False)


def _render_index(char: dict, cid: str, sections: list[tuple[str, str]],
                  cls_cn: str, race: str, theme: str, default_skin: str) -> str:
    name = str(char["name"])
    summary = _summary_of(char, sections)
    tags = [t for t in (char.get("tagList") or []) if str(t).strip()]
    if cls_cn and cls_cn not in tags:
        tags.append(cls_cn)

    lines = ["---"]
    lines.append(f"class: {_yaml_scalar(cls_cn)}")
    lines.append(f"default_avatar: {cid}.png")
    lines.append(f"default_skin: {default_skin}")
    lines.append("imports:")
    lines.append(f"- classes/{cls_cn}")
    if race and (REPO_ROOT / "data" / "races" / race).is_dir():
        lines.append(f"- races/{race}")
    lines.append(f"name: {_yaml_scalar(name)}")
    if race:
        lines.append(f"race: {_yaml_scalar(race)}")
    lines.append(f"summary: {_yaml_scalar(summary)}")
    lines.append("tags:")
    for t in tags:
        lines.append(f"- {_yaml_scalar(str(t))}")
    lines.append(f"theme_color: '{theme}'")
    lines.append("worldbook_id: arknights")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")
    lines.append("> 本条目由 `tools/import_six_star_resources.py` 依据官方干员档案生成；"
                 "文本取自 `handbook_info_table.json` / `character_table.json`，未做改写。")
    for title, body in sections:
        lines.append("")
        lines.append(f"## {title}")
        lines.append("")
        lines.append(body)
    if not sections:
        intro = "\n\n".join(
            t for t in (str(char.get("itemUsage") or "").strip(),
                        str(char.get("itemDesc") or "").strip()) if t)
        lines.append("")
        lines.append("## 官方简介")
        lines.append("")
        lines.append(intro or "（官方未提供干员档案文本。）")
    lines.append("")
    return "\n".join(lines)


def _write_text_lf(path: Path, text: str) -> None:
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["core", "standard", "e1", "full"], default="standard",
                    help="core=仅头像；standard=头像+精英2立绘（默认）；e1=再加精英1立绘；full=全部皮肤")
    ap.add_argument("--dry-run", action="store_true", help="只统计与报告，不落盘")
    ap.add_argument("--json", metavar="PATH", help="把覆盖度报告写入 JSON")
    args = ap.parse_args()

    if not (EXCEL / "character_table.json").is_file():
        print(f"素材镜像缺失：{EXCEL}/character_table.json", file=sys.stderr)
        print("请先准备 assets/ArknightsGameResource（见仓库 README）。", file=sys.stderr)
        return 2

    ct = _load_json("character_table.json")
    handbook = _load_json("handbook_info_table.json")
    av_pool, sk_pool = _pool("avatar"), _pool("skin")

    six = [(k, v) for k, v in ct.items() if v.get("rarity") == 5]
    operators = [(k, v) for k, v in six if v.get("profession") not in ("TOKEN", "TRAP")]
    tokens = len(six) - len(operators)

    rows: list[dict] = []
    for cid, char in sorted(operators, key=lambda kv: kv[1].get("name", "")):
        name = str(char["name"])
        target = CHAR_DIR / name
        has_index = (target / "index.md").is_file()
        av_sel = _picked(av_pool, cid, args.scope)
        sk_sel = _picked(sk_pool, cid, args.scope)
        default_skin = _default_skin(cid, sk_pool)
        sections = _archive_sections(handbook, cid)
        cls_cn = CLASS_CN.get(str(char.get("profession", "")), "")
        race = _race_of(sections)

        row = {
            "cid": cid,
            "name": name,
            "class": cls_cn,
            "race": race,
            "rarity": "6",
            "isNotObtainable": bool(char.get("isNotObtainable")),
            "entity_existed": has_index,
            "default_skin": default_skin,
            "avatar_files": av_sel,
            "skin_files": sk_sel,
            "archive_sections": [t for t, _ in sections],
            "bytes": 0,
            "written": [],
        }
        for sub, files in (("avatar", av_sel), ("skin", sk_sel)):
            for f in files:
                src = MIRROR / sub / f
                if not src.is_file():
                    continue
                row["bytes"] += src.stat().st_size
                dst = target / sub / f
                if dst.is_file() and dst.stat().st_size == src.stat().st_size:
                    continue
                row["written"].append(f"{sub}/{f}")
                if not args.dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)

        if not has_index:
            avatar0 = target / "avatar" / f"{cid}.png"
            theme = _theme_color(avatar0) if (not args.dry_run and avatar0.is_file()) else "#8b5ca8"
            text = _render_index(char, cid, sections, cls_cn, race, theme, default_skin)
            if not args.dry_run:
                import frontmatter as _fm
                parsed = _fm.loads(text)  # frontmatter 不合法则立刻抛错
                if parsed.metadata.get("name") != name:
                    raise SystemExit(f"frontmatter 解析异常：{name}")
                target.mkdir(parents=True, exist_ok=True)
                _write_text_lf(target / "index.md", text)
            row["index_created"] = True
        else:
            row["index_created"] = False
        rows.append(row)

    # 未被任何六星命中的镜像文件（换装/异格），用于说明 scope=full 的增量
    used = {f for r in rows for f in r["avatar_files"] + r["skin_files"]}
    extra = len([f for f in av_pool if any(_belongs(f, r["cid"]) for r in rows) and f not in used]) + \
            len([f for f in sk_pool if any(_belongs(f, r["cid"]) for r in rows) and f not in used])

    new_entities = [r["name"] for r in rows if r["index_created"] or (not r["entity_existed"] and args.dry_run)]
    existed = [r["name"] for r in rows if r["entity_existed"]]
    total_bytes = sum(r["bytes"] for r in rows)
    missing_avatar = [r["name"] for r in rows if not r["avatar_files"]]
    missing_skin = [r["name"] for r in rows if not r["default_skin"]]
    no_archive = [r["name"] for r in rows if not r["archive_sections"]]

    report = {
        "scope": args.scope,
        "dry_run": args.dry_run,
        "six_star_total": len(operators),
        "excluded_tokens_traps": tokens,
        "not_obtainable": [r["name"] for r in rows if r["isNotObtainable"]],
        "entity_existed": existed,
        "entity_new": new_entities,
        "missing_avatar": missing_avatar,
        "missing_skin": missing_skin,
        "no_official_archive": no_archive,
        "selected_bytes": total_bytes,
        "selected_mb": round(total_bytes / 1048576, 1),
        "files_not_selected": extra,
        "detail": rows,
    }

    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")

    print(f"=== 六星资源落地 · scope={args.scope}{'（dry-run）' if args.dry_run else ''} ===")
    print(f"六星干员总数：{len(operators)}（另有 {tokens} 条召唤物/装置已排除）")
    print(f"已有实体（保留手写内容）：{len(existed)} → {existed}")
    print(f"本次新建实体：{len(new_entities)}")
    print(f"头像素材缺失：{missing_avatar or '无'}")
    print(f"立绘素材缺失：{missing_skin or '无'}")
    print(f"无官方档案：{no_archive or '无'}")
    print(f"选中文件体积：{report['selected_mb']} MB（未选中 {extra} 个换装/异格文件）")
    print(f"未实装（isNotObtainable）：{report['not_obtainable']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
