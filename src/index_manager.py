"""
索引管理 — 全局依赖聚合 + 缓存管理。

职责：
- 提供 build_overview 聚合器（基于每文档 imports frontmatter）
- 提供 invalidate_cache 显式失效
- 提供 import 辅助函数（从旧 app.py 移入）
"""

import os
import time
import logging
import yaml
import frontmatter

logger = logging.getLogger(__name__)

# ── 缓存 ──

_cache: dict = {"overview": None, "timestamp": 0.0}
_CACHE_TTL = 30  # seconds


def invalidate_cache():
    """写操作后主动清空缓存。"""
    global _cache
    _cache = {"overview": None, "timestamp": 0.0}


def _cache_valid() -> bool:
    return bool(_cache["overview"] and time.time() - _cache["timestamp"] < _CACHE_TTL)


# ── Import 辅助函数（从 app.py 移入） ──


def read_imports_from_file(filepath: str) -> list:
    """从单个文档 frontmatter 提取 imports 依赖路径列表。

    支持格式：
    - imports: [characters/博士, factions/罗德岛]
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
    except Exception:
        return []

    fm = post.metadata
    dep_paths = []

    imports_raw = fm.get("imports", [])
    if isinstance(imports_raw, list):
        for item in imports_raw:
            if isinstance(item, str) and item.strip():
                path, _ = parse_import_entry(item.strip())
                dep_paths.append(path)

    return dep_paths


def parse_import_entry(entry: str) -> tuple[str, str]:
    """解析 'path | name' 格式，返回 (path, name)。兼容纯路径格式。"""
    entry = entry.strip()
    if " | " in entry:
        parts = entry.split(" | ", 1)
        return parts[0].strip(), parts[1].strip()
    return entry, ""


def resolve_doc_display_name(doc_path: str, doc_manager=None) -> str:
    """从文档路径 'category/id' 获取显示名称（frontmatter 中的 name 字段）。"""
    if "/" not in doc_path:
        return doc_path
    category, doc_id = doc_path.split("/", 1)
    if doc_manager:
        try:
            doc = doc_manager.read_document(category, doc_id)
            meta = doc.get("metadata", {})
            return meta.get("name", doc_id)
        except Exception:
            return doc_id
    return doc_id


def write_imports_to_file(filepath: str, imports: list, doc_manager=None):
    """将 imports 路径列表以 'path | name' 格式写入文档 frontmatter。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
    except Exception:
        return

    cleaned = list(dict.fromkeys(p for p in imports if p and "/" in p))
    formatted = []
    for imp in cleaned:
        # 先剥离已存在的 "| name" 后缀，避免重复堆积
        path, _ = parse_import_entry(imp)
        name = resolve_doc_display_name(path, doc_manager)
        formatted.append(f"{path} | {name}" if name else path)
    post.metadata["imports"] = formatted
    post.metadata.pop("index_refs", None)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))


# ── 目录扫描辅助 ──


def _categories_and_hierarchy(data_root: str) -> tuple[dict, list]:
    """读取 categories.yaml，返回 (categories_dict, hierarchy_list)。"""
    yaml_path = os.path.join(data_root, "categories.yaml")
    if not os.path.isfile(yaml_path):
        return {}, []
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        categories = data.get("categories", {})
        hierarchy = data.get("hierarchy", {}).get("levels", [])
        hierarchy.sort(key=lambda x: x["level"])
        return categories, hierarchy
    except Exception as e:
        logger.error("读取 categories.yaml 失败: %s", e)
        return {}, []


def _scan_docs_in_category(category_dir: str) -> list[dict]:
    """扫描实体文件夹，返回 [{path, id, name}]。"""
    if not os.path.isdir(category_dir):
        return []
    docs = []
    for item in sorted(os.listdir(category_dir)):
        item_path = os.path.join(category_dir, item)
        index_md = os.path.join(item_path, "index.md")
        if os.path.isdir(item_path) and os.path.isfile(index_md):
            try:
                with open(index_md, "r", encoding="utf-8") as f:
                    fm_data = frontmatter.load(f)
                docs.append({
                    "id": item,
                    "name": fm_data.metadata.get("name", item),
                    "path": index_md,
                })
            except Exception:
                continue
    return docs


# ── 聚合器 ──


def build_overview(data_root: str, doc_manager=None) -> dict:
    """构建所有文档的分组概览，包含前向引用（imports）和反向引用（imported_by）。

    Returns:
        {categories: [{category, label, level, docs: [{path, id, name, imports, imported_by}]}],
         hierarchy: [...]}
    """
    global _cache
    if _cache_valid():
        return _cache["overview"]

    categories, hierarchy = _categories_and_hierarchy(data_root)
    if not categories:
        return {"categories": [], "hierarchy": []}

    # Phase 1: 扫描所有文档
    cat_docs = {}  # {category: [{id, name, path, import_paths}]}
    doc_index = {}  # {path_key: {category, id, name}}  (path_key = "category/id")

    for cat_name, dir_rel in categories.items():
        dir_path = dir_rel if isinstance(dir_rel, str) else dir_rel.get("dir", "")
        if dir_path.startswith("data/"):
            dir_path = dir_path[5:]
        full_dir = os.path.join(data_root, dir_path) if not os.path.isabs(dir_path) else dir_path
        docs = _scan_docs_in_category(full_dir)
        cat_docs[cat_name] = []
        for d in docs:
            import_paths = read_imports_from_file(d["path"])
            cat_docs[cat_name].append({
                "id": d["id"],
                "name": d["name"],
                "import_paths": import_paths,
            })
            path_key = f"{cat_name}/{d['id']}"
            doc_index[path_key] = {"category": cat_name, "name": d["name"]}

    # Phase 2: 构建反向引用
    reverse_index = {}  # path_key -> [{category, name}]
    for cat_name, docs in cat_docs.items():
        for d in docs:
            for imp in d["import_paths"]:
                if imp not in reverse_index:
                    reverse_index[imp] = []
                reverse_index[imp].append({
                    "category": cat_name,
                    "name": d["name"],
                    "path": f"{cat_name}/{d['id']}",
                })

    # Phase 3: 构建最终输出
    cat_level_map = {}
    for h in hierarchy:
        for c in h.get("categories", []):
            cat_level_map[c] = (h["level"], h["label"])

    result_categories = []
    for cat_name, docs in cat_docs.items():
        level, label = cat_level_map.get(cat_name, (99, ""))
        doc_list = []
        for d in docs:
            path_key = f"{cat_name}/{d['id']}"
            # imports 带名称
            imports_info = []
            for imp in d["import_paths"]:
                info = doc_index.get(imp, {"name": imp.split("/")[-1] if "/" in imp else imp})
                imports_info.append({
                    "path": imp,
                    "name": info["name"],
                })
            # imported_by 带名称
            imported_by = []
            for ref in reverse_index.get(path_key, []):
                imported_by.append({
                    "path": ref["path"],
                    "name": ref["name"],
                    "category": ref["category"],
                })
            doc_list.append({
                "path": path_key,
                "id": d["id"],
                "name": d["name"],
                "imports": imports_info,
                "imported_by": imported_by,
            })

        result_categories.append({
            "category": cat_name,
            "label": label,
            "level": level,
            "docs": doc_list,
        })

    result_categories.sort(key=lambda c: (c["level"], c["category"]))
    result = {"categories": result_categories, "hierarchy": hierarchy}

    _cache = {"overview": result, "timestamp": time.time()}
    return result
