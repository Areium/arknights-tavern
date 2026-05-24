"""
索引配置管理器 — 全局索引配置的 CRUD 和树结构构建。

将分散在文档 frontmatter 中的 index_refs 集中管理到
data/_index_config.yaml，并提供反向引用计算和树结构输出。
"""

import json
import os
import yaml
from typing import Dict, List, Optional, Tuple

class IndexConfig:
    """全局索引配置。

    data 格式:
        { "category/doc_id": { "ref_category": ["entity_id", ...] } }
    """

    def __init__(self, data: Optional[Dict[str, Dict[str, List[str]]]] = None):
        self.data: Dict[str, Dict[str, List[str]]] = data or {}

    def get_doc_refs(self, doc_path: str) -> Dict[str, List[str]]:
        return self.data.get(doc_path, {})

    def set_doc_refs(self, doc_path: str, refs: Dict[str, List[str]]):
        self.data[doc_path] = refs

    def remove_doc(self, doc_path: str):
        self.data.pop(doc_path, None)

    def to_dict(self) -> Dict:
        return {"docs": self.data}


def parse_doc_path(doc_path: str) -> Tuple[str, str]:
    """从 'characters/博士' 解析出 (category, doc_id)。"""
    parts = doc_path.split("/", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], parts[0])


class IndexManager:
    """全局索引配置管理器。"""

    def __init__(self, data_dir: str):
        self._config_path = os.path.join(data_dir, "_index_config.yaml")
        self.config: IndexConfig = IndexConfig()
        self._load()

    # ── 内部 I/O ──

    def _load(self):
        """从磁盘加载配置。"""
        if os.path.isfile(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                self.config = IndexConfig(raw.get("docs", {}))
            except Exception:
                self.config = IndexConfig({})
        else:
            self.config = IndexConfig({})

    def save(self):
        """写入磁盘。"""
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.config.to_dict(), f,
                      allow_unicode=True, sort_keys=False,
                      default_flow_style=False)

    # ── 查询 ──

    def get_all_refs(self) -> Dict[str, Dict[str, List[str]]]:
        return self.config.data

    def get_doc_refs(self, doc_path: str) -> Dict[str, List[str]]:
        return self.config.get_doc_refs(doc_path)

    # ── 修改 ──

    def set_doc_refs(self, doc_path: str, refs: Dict[str, List[str]]):
        self.config.set_doc_refs(doc_path, refs)

    def remove_doc(self, doc_path: str):
        self.config.remove_doc(doc_path)

    def add_ref(self, doc_path: str, ref_category: str, entity_id: str):
        refs = self.config.data.setdefault(doc_path, {})
        refs.setdefault(ref_category, [])
        if entity_id not in refs[ref_category]:
            refs[ref_category].append(entity_id)

    def remove_ref(self, doc_path: str, ref_category: str, entity_id: str):
        refs = self.config.data.get(doc_path, {})
        cat_refs = refs.get(ref_category, [])
        if entity_id in cat_refs:
            cat_refs.remove(entity_id)
            if not cat_refs:
                del refs[ref_category]
        if not refs:
            del self.config.data[doc_path]

    # ── 构建反向引用 & 树结构 ──

    def build_tree(self, all_entities: Dict[str, List[Dict]]) -> Dict:
        """构建带反向引用的索引树。

        all_entities 格式: { "characters": [{id, name, summary}, ...] }
        由 app._load_all_entities() 提供。

        返回:
            {
                "categories": [
                    {
                        "category": "characters",
                        "doc_count": 3,
                        "docs": [
                            {
                                "id": "博士",
                                "path": "characters/博士",
                                "ref_count": 5,
                                "refed_by_count": 1,
                                "refs": {"attributes": ["情绪稳定性", ...]},
                                "refed_by": {
                                    "plots": [{"id": "near-light", "name": "近夜"}]
                                }
                            }
                        ]
                    }
                ]
            }
        """
        # Step 1: 构建反向引用映射 entity -> [(doc_path, category)]
        # 对于每个文档的每个 ref，记录哪个文档引用了这个实体
        reverse_map: Dict[str, List[Tuple[str, str]]] = {}  # entity_id -> [(doc_path, cat)]

        for doc_path, refs in self.config.data.items():
            for ref_cat, entity_ids in refs.items():
                for eid in entity_ids:
                    reverse_map.setdefault(eid, []).append((doc_path, ref_cat))

        # Step 2: 对每个类别下的文档，计算正向/反向引用
        categories: Dict[str, Dict] = {}  # category -> category dict

        for doc_path, refs in self.config.data.items():
            cat_name, doc_id = parse_doc_path(doc_path)

            if cat_name not in categories:
                categories[cat_name] = {
                    "category": cat_name,
                    "doc_count": 0,
                    "docs": [],
                }

            # 反向引用：哪些文档引用了当前文档对应的实体
            refed_by_cats: Dict[str, List[Dict]] = {}
            referrers = reverse_map.get(doc_id, [])
            for ref_doc_path, _ in referrers:
                if ref_doc_path == doc_path:
                    continue  # skip self
                ref_doc_cat, ref_doc_id = parse_doc_path(ref_doc_path)
                refed_by_cats.setdefault(ref_doc_cat, [])
                if not any(r["id"] == ref_doc_id for r in refed_by_cats[ref_doc_cat]):
                    refed_by_cats[ref_doc_cat].append({
                        "id": ref_doc_id,
                        "path": ref_doc_path,
                    })

            total_ref_count = sum(len(v) for v in refs.values())
            total_refed_by_count = sum(len(v) for v in refed_by_cats.values())

            categories[cat_name]["docs"].append({
                "id": doc_id,
                "path": doc_path,
                "ref_count": total_ref_count,
                "refed_by_count": total_refed_by_count,
                "refs": refs,
                "refed_by": refed_by_cats,
            })

        # Step 3: 排序 & 计数
        result_cats = sorted(categories.values(), key=lambda c: c["category"])
        for cat in result_cats:
            cat["doc_count"] = len(cat["docs"])
            cat["docs"].sort(key=lambda d: d["id"])

        return {"categories": result_cats}

    # ── 导出 / 导入 ──

    def export_yaml(self) -> str:
        """将配置导出为 YAML 字符串。"""
        return yaml.dump(self.config.to_dict(), allow_unicode=True, sort_keys=False)

    def import_yaml(self, yaml_str: str) -> int:
        """从 YAML 字符串导入配置，保存并返回文档数。"""
        data = yaml.safe_load(yaml_str)
        if not isinstance(data, dict):
            raise ValueError("无效的 YAML 格式")
        docs = data.get("docs", {})
        if not isinstance(docs, dict):
            raise ValueError("缺少 docs 字段或格式不正确")
        self.config = IndexConfig(docs)
        self.save()
        return len(docs)

    # ── 会话级配置 ──

    def session_config_path(self, session_id: str, mode: str) -> str:
        """会话级索引配置文件的路径。"""
        config_dir = os.path.dirname(self._config_path)
        return os.path.join(
            config_dir, "memory", "sessions", mode, session_id, "index_config.json"
        )

    def load_session_config(self, session_id: str, mode: str) -> dict:
        """加载会话的索引配置，不存在则返回空 dict。"""
        path = self.session_config_path(session_id, mode)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_session_config(self, session_id: str, mode: str, config: dict):
        """保存会话的索引配置。"""
        path = self.session_config_path(session_id, mode)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"config": config}, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def build_tree_from_config(self, config: dict, all_entities: dict) -> dict:
        """从给定的配置构建树，不修改当前加载的配置。"""
        from copy import deepcopy
        saved = deepcopy(self.config.data)
        self.config.data = config
        try:
            return self.build_tree(all_entities)
        finally:
            self.config.data = saved

    # ── 全量树（含未配置文档） ──

    def build_full_tree(self, doc_manager, all_entities: dict) -> dict:
        """构建包含未配置文档的全量树。

        将文件系统中存在的所有文档与 _index_config.yaml 的配置合并，
        未配置的文档标记 in_config=False，方便前端展示和添加。
        """
        # 1. 构建已配置的树
        config_tree = self.build_tree(all_entities)

        # 2. 查找已配置的文档 ID
        configured: dict = {}
        for cat in config_tree["categories"]:
            configured[cat["category"]] = {d["id"] for d in cat["docs"]}

        # 3. 从文件系统获取所有文档，按类别归并
        all_cats = doc_manager.list_all_documents()

        # 4. 构建结果
        result = []
        config_docs_map: dict = {}
        for cat in config_tree["categories"]:
            config_docs_map[cat["category"]] = {d["id"]: d for d in cat["docs"]}

        seen_categories = set()
        for cat_data in all_cats:
            cat_name = cat_data["category"]
            seen_categories.add(cat_name)
            flat_ids = self._flatten_docs_tree(cat_data.get("children", []))

            existing = config_docs_map.get(cat_name, {})
            merged = {**existing}  # copy configured docs

            for doc_id in flat_ids:
                if doc_id not in merged:
                    merged[doc_id] = {
                        "id": doc_id,
                        "path": f"{cat_name}/{doc_id}",
                        "ref_count": 0,
                        "refed_by_count": 0,
                        "refs": {},
                        "refed_by": {},
                        "in_config": False,
                    }
                else:
                    merged[doc_id]["in_config"] = True

            docs_list = sorted(merged.values(), key=lambda d: d["id"])
            result.append({
                "category": cat_name,
                "doc_count": len(docs_list),
                "configured_count": sum(1 for d in docs_list if d.get("in_config")),
                "docs": docs_list,
            })

        # 5. 追加仅有配置但文件可能已被删除的类别
        for cat in config_tree["categories"]:
            if cat["category"] not in seen_categories:
                docs_list = [
                    {**d, "in_config": True}
                    for d in cat["docs"]
                ]
                result.append({
                    "category": cat["category"],
                    "doc_count": len(docs_list),
                    "configured_count": len(docs_list),
                    "docs": docs_list,
                })

        result.sort(key=lambda c: c["category"])
        return {"categories": result}

    @staticmethod
    def _flatten_docs_tree(children: list) -> list:
        """从 DocTreeNode 列表中提取所有文档 ID。"""
        ids = []
        for child in children:
            if child.get("type") == "document" and child.get("id"):
                ids.append(child["id"])

        return ids

    # ── 迁移 ──

    def migrate_from_frontmatter(self, doc_manager) -> int:
        """从文档 frontmatter 中的 index_refs 迁移到全局配置。

        doc_manager: DocumentManager 实例
        返回迁移的文档数。
        """
        # 查找所有文档及其 index_refs
        migrated = 0
        cat_dirs = self._list_categories()

        for cat_name in cat_dirs:
            doc_items = doc_manager.list_documents(cat_name)
            for item in doc_items:
                doc_id = item["id"]
                try:
                    doc = doc_manager.read_document(cat_name, doc_id)
                except Exception:
                    continue
                refs = doc.get("metadata", {}).get("index_refs", {})
                if refs:
                    doc_path = f"{cat_name}/{doc_id}"
                    self.config.set_doc_refs(doc_path, refs)
                    migrated += 1

        if migrated > 0:
            self.save()
        return migrated

    def _list_categories(self) -> List[str]:
        """从 _INDEX.md 列出所有类别。"""
        from frontmatter import load as fm_load
        master_path = os.path.join(
            os.path.dirname(self._config_path), "_INDEX.md"
        )
        if not os.path.isfile(master_path):
            return []
        with open(master_path, "r", encoding="utf-8") as f:
            master = fm_load(f)
        return list(master.metadata.get("index", {}).keys())
