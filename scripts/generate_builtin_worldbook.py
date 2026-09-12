"""
生成方舟整合包：data/packs/arknights.json

从 data/characters/<名>/index.md（角色设定）与 data/plots/<剧情>/index.md（剧情概述）
生成酒馆兼容世界书条目：
- 角色条目：触发词 = 角色名 + 别名（tags 中的称号），内容 = 设定摘要 + 属性/关系
- 剧情条目：触发词 = 剧情 id / 名称，内容 = 剧情概述（开篇氛围 + 可用角色）

整合包随程序分发（git 跟踪），程序首次启动自动安装到 data/worldbooks/（source=preinstalled），
与用户导入内容统一管理（可停用/编辑/删除/一键重装）。
运行：python scripts/generate_builtin_worldbook.py
"""

import json
import sys
import time
from pathlib import Path

import frontmatter

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "data" / "packs" / "arknights.json"


def load_frontmatter(path: Path) -> dict:
    try:
        fm = frontmatter.load(path)
        return fm.metadata or {}
    except Exception:
        return {}


def char_entries():
    """角色条目：触发词 = 名称 + 称号标签。"""
    entries = []
    char_dir = REPO_ROOT / "data" / "characters"
    if not char_dir.is_dir():
        return entries
    for item in sorted(char_dir.iterdir()):
        if not item.is_dir():
            continue
        idx = item / "index.md"
        if not idx.is_file():
            continue
        md = frontmatter.load(idx)
        meta = md.metadata or {}
        name = str(meta.get("name") or item.name).strip()
        if not name:
            continue

        keys = [name]
        for tag in (meta.get("tags") or []):
            t = str(tag).strip()
            if t and t not in keys:
                keys.append(t)

        lines = [f"**{name}**（角色设定）"]
        if meta.get("class"):
            lines.append(f"职业：{meta['class']}")
        if meta.get("faction"):
            lines.append(f"势力：{meta['faction']}")
        if meta.get("race"):
            lines.append(f"种族：{meta['race']}")
        if meta.get("summary"):
            lines.append(f"简介：{meta['summary']}")
        body = (md.content or "").strip().replace("\r\n", "\n")
        if body:
            lines.append("")
            lines.append(body[:2000])
        content = "\n".join(lines)

        entries.append({
            "uid": f"char_{item.name}",
            "name": f"{name}（角色设定）",
            "content": content,
            "trigger_keys": keys,
            "secondary_keys": [],
            "always_active": False,
            "selective": True,
            "enabled": True,
            "position": 1,
            "depth": 4,
            "scan_depth": 4,
            "probability": 100,
            "group": "角色",
            "group_weight": 100,
            "case_sensitive": False,
            "match_whole_words": False,
            "raw": {},
        })
    return entries


def plot_entries():
    """剧情条目：触发词 = 剧情 id + 名称（若存在）。"""
    entries = []
    plot_dir = REPO_ROOT / "data" / "plots"
    if not plot_dir.is_dir():
        return entries
    for item in sorted(plot_dir.iterdir()):
        if not item.is_dir():
            continue
        idx = item / "index.md"
        if not idx.is_file():
            continue
        md = frontmatter.load(idx)
        meta = md.metadata or {}
        pid = str(meta.get("id") or item.name).strip()
        name = str(meta.get("name") or "").strip()
        keys = [pid]
        if name and name not in keys:
            keys.append(name)

        lines = [f"**{name or pid}**（剧情）"]
        if meta.get("initial_atmosphere"):
            lines.append(f"开篇氛围：{meta['initial_atmosphere']}")
        chars = meta.get("initial_characters") or []
        if chars:
            lines.append(f"登场角色：{'、'.join(str(c) for c in chars)}")
        body = (md.content or "").strip().replace("\r\n", "\n")
        if body:
            lines.append("")
            lines.append(body[:2000])
        content = "\n".join(lines)

        entries.append({
            "uid": f"plot_{pid}",
            "name": f"{name or pid}（剧情）",
            "content": content,
            "trigger_keys": keys,
            "secondary_keys": [],
            "always_active": False,
            "selective": True,
            "enabled": True,
            "position": 1,
            "depth": 4,
            "scan_depth": 4,
            "probability": 100,
            "group": "剧情",
            "group_weight": 90,
            "case_sensitive": False,
            "match_whole_words": False,
            "raw": {},
        })
    return entries


def main():
    entries = char_entries() + plot_entries()
    book = {
        "id": "arknights",
        "name": "明日方舟·内置设定集",
        "source": "preinstalled",
        "enabled": True,
        "source_format": "builtin",
        "budget_tokens": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, indent=2)
        f.write("\n")
    n_char = sum(1 for e in entries if e["uid"].startswith("char_"))
    n_plot = len(entries) - n_char
    print(f"已生成 {OUT}")
    print(f"条目：角色 {n_char} + 剧情 {n_plot} = {len(entries)}")


if __name__ == "__main__":
    sys.exit(main())
