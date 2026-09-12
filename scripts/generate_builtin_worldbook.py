"""
生成「世界书整合包」：data/packs/arknights.json

把 data/ 下的世界观文档语料（角色/剧情/势力/物品/地点/种族/职业/属性/规则/
敌人/世界观）整理为**单一统一格式**的酒馆兼容世界书打包文件——每个文档
对应一条条目，条目 content 承载完整 Markdown 正文（不只是摘要）。

整合包随程序分发（git 跟踪），程序首次启动自动安装到 data/worldbooks/
（source=preinstalled），也可通过世界书导入功能手动导入同一份文件。
「角色·剧情」文档管理界面移除后，本整合包即文档内容的迁移出口：
浏览与编辑经由世界书模块进行。

条目触发词 = 文档名/frontmatter name（+剧情 id、角色称号等别名）。
运行：python scripts/generate_builtin_worldbook.py
"""

import json
import sys
import time
from pathlib import Path

import frontmatter

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "data" / "packs" / "arknights.json"

# 类别 →（数据目录，条目 group，条目权重）
CATEGORIES = [
    ("world", "世界观", 95),
    ("rules", "规则", 95),
    ("attributes", "属性", 60),
    ("races", "种族", 70),
    ("classes", "职业", 70),
    ("weather", "天气", 40),
    ("environment/Location", "地点", 75),
    ("items", "物品", 70),
    ("enemies", "敌人", 60),
    ("characters", "角色", 100),
    ("plots", "剧情", 90),
]


def _entry(uid: str, name: str, content: str, keys: list[str], group: str,
           weight: int) -> dict:
    return {
        "uid": uid,
        "name": name,
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
        "group": group,
        "group_weight": weight,
        "case_sensitive": False,
        "match_whole_words": False,
        "raw": {},
    }


def _doc_id(path: Path) -> str:
    """文档 id（相对类别目录、去扩展名、目录分隔符归一）。"""
    return path.with_suffix("").as_posix()


def category_entries(cat_dir: str, group: str, weight: int) -> list[dict]:
    """一个类别目录下的全部文档 → 条目（递归扫描）。

    - 实体目录（含 index.md）→ 一条条目（content = index.md 正文）
    - 平铺 .md → 各一条条目
    同名时实体目录条目优先（跳过实体目录内的其它散文件）。
    """
    entries: list[dict] = []
    base = REPO_ROOT / "data" / cat_dir
    if not base.is_dir():
        return entries

    entity_index_dirs = {p.parent for p in base.rglob("index.md")}
    files: list[Path] = []
    for d in sorted(entity_index_dirs):
        files.append(d / "index.md")
    for p in sorted(base.rglob("*.md")):
        if p.parent in entity_index_dirs and p.stem != "index":
            continue  # 实体目录只收 index.md
        if p.stem.upper().startswith("TEMPLATE"):
            continue
        if p not in files:
            files.append(p)

    for path in files:
        try:
            md = frontmatter.load(path)
        except Exception as exc:
            print(f"  跳过解析失败的文档 {path}: {exc}")
            continue
        meta = md.metadata or {}
        name = str(meta.get("name") or (path.stem if path.stem != "index" else path.parent.name)).strip()
        if not name:
            continue
        body = (md.content or "").strip().replace("\r\n", "\n")
        lines = [f"**{name}**（{group}设定）"]
        for key in ("summary", "faction", "race", "class"):
            if meta.get(key):
                lines.append(f"{'简介' if key == 'summary' else key}：{meta[key]}")
        if body:
            lines.append("")
            lines.append(body)
        doc_id = _doc_id(path.relative_to(base))
        keys = [name]
        if doc_id != name and path.stem != "index":
            keys.append(doc_id)
        for tag in (meta.get("tags") or [])[:6]:
            t = str(tag).strip()
            if t and t not in keys:
                keys.append(t)
        entries.append(_entry(
            f"{Path(cat_dir).name}_{doc_id.replace('/', '_')}",
            f"{name}（{group}设定）", "\n".join(lines), keys, group, weight))
    return entries


def main():
    entries: list[dict] = []
    for cat_dir, group, weight in CATEGORIES:
        part = category_entries(cat_dir, group, weight)
        print(f"  {cat_dir}: {len(part)} 条")
        entries.extend(part)

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
    print(f"已生成 {OUT}（共 {len(entries)} 条）")


if __name__ == "__main__":
    sys.exit(main())
