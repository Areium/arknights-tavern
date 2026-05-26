"""
文档管理器：对所有 Markdown 数据文件的 CRUD 操作 + 哈希冲突检测。

设计：
- 从 data/categories.yaml 自动发现文档类别和路径
- 读文件时返回 SHA256 哈希，写文件时校验哈希以检测冲突
- 支持类别子目录（如 Location/Rhode_Island/）
- 可选集成 Git 自动提交
"""

import os
import re
import json
import hashlib
import logging
import shutil
from typing import Optional

import frontmatter
import yaml

logger = logging.getLogger(__name__)

# ── 异常类 ──


class DocumentNotFoundError(Exception):
    pass


class ConflictError(Exception):
    """保存冲突：文件已被其他进程修改。"""

    def __init__(self, path: str, current_hash: str, expected_hash: str,
                 current_content: str):
        self.path = path
        self.current_hash = current_hash
        self.expected_hash = expected_hash
        self.current_content = current_content
        super().__init__(f"文件已被修改: {path}")


# ── 类别描述 ──


class DocumentCategory:
    """一个文档类别（对应 categories.yaml 中的一个条目）。"""

    def __init__(self, category_id: str, directory: str):
        self.id = category_id
        self.directory = directory

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "directory": self.directory,
        }


class DocumentInfo:
    """单个文档的信息。"""

    def __init__(self, category_id: str, doc_id: str, title: str, path: str,
                 hash_str: str, mtime: float, summary: str = ""):
        self.category_id = category_id
        self.id = doc_id
        self.title = title
        self.path = path
        self.hash = hash_str
        self.mtime = mtime
        self.summary = summary

    def to_dict(self) -> dict:
        return {
            "category_id": self.category_id,
            "id": self.id,
            "title": self.title,
            "hash": self.hash,
            "mtime": self.mtime,
            "summary": self.summary,
        }


# ── 文档内容 ──


# ── 主类 ──


class DocumentManager:
    """文档管理器：读取/写入/列举所有数据文件。

    支持两种文档组织方式（双模式）：
    - 实体文件夹：目录包含 index.md（如 characters/银灰/index.md）
    - 传统文件：独立 .md 文件（如 characters/银灰.md），向后兼容
    """

    # 文件名白名单（不视为数据文档）
    _EXCLUDED_FILES = {"TEMPLATE", "_index", "_INDEX", "README"}

    def __init__(self, root_dir: str = None):
        if root_dir is None:
            # 从 __file__ 定位项目根目录
            self._root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        else:
            self._root = root_dir

        self._categories: dict[str, DocumentCategory] = {}
        self._hierarchy: list[dict] = []
        self._load_index()

    # ── 索引加载 ──

    def _load_index(self):
        """加载 data/categories.yaml 注册表。"""
        yaml_path = os.path.join(self._root, "data", "categories.yaml")
        if not os.path.isfile(yaml_path):
            logger.warning("categories.yaml 不存在: %s", yaml_path)
            return

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            cat_data = data.get("categories", {})
            for cat_id, cat_info in cat_data.items():
                dir_path = cat_info if isinstance(cat_info, str) else cat_info.get("dir", "")
                self._categories[cat_id] = DocumentCategory(
                    category_id=cat_id,
                    directory=os.path.join(self._root, dir_path),
                )
            h_data = data.get("hierarchy", {})
            self._hierarchy = h_data.get("levels", [])
            logger.info("加载了 %d 个文档类别", len(self._categories))
        except Exception as e:
            logger.error("加载 categories.yaml 失败: %s", e)

    # ── 类别查询 ──

    def list_categories(self) -> list[dict]:
        """返回所有文档类别。"""
        return [cat.to_dict() for cat in self._categories.values()]

    def get_category(self, category_id: str) -> Optional[DocumentCategory]:
        return self._categories.get(category_id)

    def get_hierarchy(self) -> list[dict]:
        return self._hierarchy

    # ── 文档列举 ──

    def list_documents(self, category_id: str,
                       include_content: bool = False) -> list[dict]:
        """列出指定类别下的所有文档。

        支持两种文档模式：
        - 实体文件夹：目录含 index.md → doc_id 为文件夹名
        - 传统文件：独立 .md 文件（向后兼容）

        Args:
            category_id: 类别 ID（如 "characters"）
            include_content: 是否同时返回内容摘要

        Returns:
            文档信息列表
        """
        cat = self._categories.get(category_id)
        if not cat:
            raise ValueError(f"未知文档类别: {category_id}")

        docs = []
        base = cat.directory
        if not os.path.isdir(base):
            return docs

        entity_dirs: set[str] = set()  # 已识别为实体的目录绝对路径

        for root, dirs, _files in os.walk(base):
            dirs.sort()

            # 1. 识别实体文件夹（含 index.md 的目录）
            for d in dirs:
                d_full = os.path.join(root, d)
                index_md = os.path.join(d_full, "index.md")
                if os.path.isfile(index_md):
                    entity_dirs.add(d_full)
                    doc_rel = os.path.relpath(d_full, base).replace("\\", "/")
                    stat = os.stat(index_md)
                    file_hash = self._hash_file(index_md)

                    title = d
                    summary = ""
                    if include_content:
                        try:
                            with open(index_md, "r", encoding="utf-8") as fh:
                                data = frontmatter.load(fh)
                            title = data.metadata.get("name", d)
                            summary = data.metadata.get("summary", "")
                            if not summary:
                                first_line = data.content.strip().split("\n")[0]
                                summary = first_line[:80] if first_line else ""
                        except Exception:
                            pass

                    docs.append(DocumentInfo(
                        category_id=category_id,
                        doc_id=doc_rel,
                        title=title,
                        path=doc_rel,  # 实体文件夹：路径不含 index.md
                        hash_str=file_hash,
                        mtime=stat.st_mtime,
                        summary=summary,
                    ).to_dict())

        for root, _dirs, files in os.walk(base):
            for f in sorted(files):
                if not f.endswith(".md"):
                    continue
                stem = os.path.splitext(f)[0]
                if stem in self._EXCLUDED_FILES or stem == "index":
                    continue

                filepath = os.path.join(root, f)

                # 跳过已在实体文件夹内的 .md 文件（由第三遍扫描作为子文档处理）
                file_dir = os.path.dirname(filepath)
                is_in_entity = any(
                    file_dir == ed or file_dir.startswith(ed + os.sep)
                    for ed in entity_dirs
                )
                if is_in_entity:
                    continue

                cat_rel = os.path.relpath(filepath, base).replace("\\", "/")
                doc_id = os.path.splitext(cat_rel)[0]

                stat = os.stat(filepath)
                file_hash = self._hash_file(filepath)

                title = stem
                summary = ""
                if include_content:
                    try:
                        with open(filepath, "r", encoding="utf-8") as fh:
                            data = frontmatter.load(fh)
                        title = data.metadata.get("name", stem)
                        summary = data.metadata.get("summary", "")
                        if not summary:
                            first_line = data.content.strip().split("\n")[0]
                            summary = first_line[:80] if first_line else ""
                    except Exception:
                        pass

                docs.append(DocumentInfo(
                    category_id=category_id,
                    doc_id=doc_id,
                    title=title,
                    path=cat_rel,
                    hash_str=file_hash,
                    mtime=stat.st_mtime,
                    summary=summary,
                ).to_dict())

        # 第三遍：收集实体目录内的子文档（非 index.md）
        for entity_dir in entity_dirs:
            entity_name = os.path.basename(entity_dir)
            for sub_root, _sub_dirs, sub_files in os.walk(entity_dir):
                for f in sorted(sub_files):
                    if not f.endswith(".md"):
                        continue
                    stem = os.path.splitext(f)[0]
                    if stem == "index" or stem in self._EXCLUDED_FILES:
                        continue

                    filepath = os.path.join(sub_root, f)
                    sub_rel = os.path.relpath(filepath, entity_dir).replace("\\", "/")
                    # 复合 doc_id: "entity_name/sub_name"
                    doc_id = f"{entity_name}/{os.path.splitext(sub_rel)[0]}"

                    stat = os.stat(filepath)
                    file_hash = self._hash_file(filepath)
                    cat_rel = os.path.relpath(filepath, base).replace("\\", "/")

                    title = stem
                    summary = ""
                    if include_content:
                        try:
                            with open(filepath, "r", encoding="utf-8") as fh:
                                data = frontmatter.load(fh)
                            title = data.metadata.get("name", stem)
                            summary = data.metadata.get("summary", "")
                            if not summary:
                                first_line = data.content.strip().split("\n")[0]
                                summary = first_line[:80] if first_line else ""
                        except Exception:
                            pass

                    docs.append(DocumentInfo(
                        category_id=category_id,
                        doc_id=doc_id,
                        title=title,
                        path=cat_rel,
                        hash_str=file_hash,
                        mtime=stat.st_mtime,
                        summary=summary,
                    ).to_dict())

        return docs

    def list_all_documents(self) -> list[dict]:
        """递归列举所有类别的所有文档（供前端文档树使用）。"""
        result = []
        for cat_id in self._categories:
            try:
                docs = self.list_documents(cat_id, include_content=True)
                result.append({
                    "category": cat_id,
                    "category_info": self._categories[cat_id].to_dict(),
                    "documents": docs,
                })
            except Exception as e:
                logger.error("列举类别 %s 失败: %s", cat_id, e)
        return self._build_tree(result)

    def _build_tree(self, flat: list[dict]) -> list[dict]:
        """将平铺列表按目录层级组织成树结构。"""
        for cat_group in flat:
            cat_group["children"] = self._docs_to_tree(
                cat_group.pop("documents", []), cat_group["category"]
            )
        return flat

    def _docs_to_tree(self, documents: list[dict], category_id: str) -> list[dict]:
        """Build nested tree from flat document list by splitting doc id on '/' or '\\'.

        支持实体文件夹内含子文档的情况：当文档的中间路径也是另一个文档时，
        该节点升级为可展开的文档节点（带 children）。
        """
        root: dict[str, dict] = {}
        for doc in documents:
            parts = doc["id"].replace("\\", "/").split("/")
            current = root
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    # 叶子节点：文档
                    node = {
                        "name": doc["title"],
                        "type": "document",
                        "id": doc["id"],
                        "hash": doc["hash"],
                        "mtime": doc["mtime"],
                        "summary": doc["summary"],
                        "category_id": doc["category_id"],
                    }
                    if part in current and "children" in current[part]:
                        # 已有中间路径创建的 folder → 升级为可展开文档
                        node["children"] = current[part]["children"]
                    current[part] = node
                else:
                    if part not in current:
                        current[part] = {"name": part, "type": "folder", "children": {}}
                    elif "children" not in current[part]:
                        # 已有文档节点但无 children → 添加 children
                        current[part]["children"] = {}
                    current = current[part]["children"]
        return self._dict_tree_to_list(root)

    @staticmethod
    def _dict_tree_to_list(d: dict[str, dict]) -> list[dict]:
        """Convert interim dict-tree to sorted list-tree (folders first, then A-Z)."""
        result: list[dict] = []
        folders = [(k, v) for k, v in d.items() if v.get("type") == "folder"]
        docs = [(k, v) for k, v in d.items() if v.get("type") != "folder"]
        for name, node in sorted(folders, key=lambda x: x[0].lower()) + sorted(docs, key=lambda x: x[0].lower()):
            entry = dict(node)
            if "children" in entry and isinstance(entry["children"], dict):
                entry["children"] = DocumentManager._dict_tree_to_list(entry["children"])
            result.append(entry)
        return result

    # ── 文档读写 ──

    def read_document(self, category_id: str, doc_path: str) -> dict:
        """读取文档内容。

        Args:
            category_id: 类别 ID
            doc_path: 文档相对路径（相对于类别目录，不含 .md 后缀）

        Returns:
            {"metadata": {...}, "content": "...", "hash": "...", "path": "...",
             "filepath": "...", "frontmatter_raw": "..."}
        """
        filepath = self._resolve_path(category_id, doc_path)
        if not filepath or not os.path.isfile(filepath):
            raise DocumentNotFoundError(
                f"文档不存在: {category_id}/{doc_path}"
            )

        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()

        try:
            data = frontmatter.loads(raw)
            fm_raw = raw.split("---", 2)[1] if raw.startswith("---") else ""
        except Exception:
            data = type("obj", (object,), {"metadata": {}, "content": raw})()
            fm_raw = ""

        file_hash = self._hash_file(filepath)
        # 实体文件夹：path 不含 index.md，用文件夹名作为路径
        if os.path.basename(filepath) == "index.md":
            rel_path = os.path.relpath(os.path.dirname(filepath), self._root)
        else:
            rel_path = os.path.relpath(filepath, self._root)

        return {
            "metadata": data.metadata,
            "content": data.content,
            "frontmatter_raw": fm_raw,
            "hash": file_hash,
            "path": rel_path,
            "filepath": filepath,
        }

    def save_document(self, category_id: str, doc_path: str,
                      content: str, metadata: dict = None,
                      expected_hash: str = None) -> dict:
        """保存文档。

        如果提供了 expected_hash，写入前会校验文件当前哈希，
        不匹配则抛出 ConflictError。

        Args:
            category_id: 类别 ID
            doc_path: 文档相对路径（相对于类别目录，不含 .md）
            content: 正文内容（不含 frontmatter）
            metadata: frontmatter 字典（None 表示保留原值）
            expected_hash: 预期的文件哈希（用于冲突检测）

        Returns:
            {"hash": "...", "path": "..."}
        """
        filepath = self._resolve_path(category_id, doc_path)
        if not filepath:
            raise DocumentNotFoundError(
                f"文档不存在: {category_id}/{doc_path}"
            )

        # 确保父目录存在（对实体文件夹尤其重要）
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # 冲突检测
        if expected_hash:
            if os.path.isfile(filepath):
                current_hash = self._hash_file(filepath)
                if current_hash != expected_hash:
                    with open(filepath, "r", encoding="utf-8") as f:
                        current_content = f.read()
                    raise ConflictError(
                        path=filepath,
                        current_hash=current_hash,
                        expected_hash=expected_hash,
                        current_content=current_content,
                    )

        # 读取已有 frontmatter（如果 metadata 未提供则保留）
        if metadata is None:
            try:
                if os.path.isfile(filepath):
                    with open(filepath, "r", encoding="utf-8") as f:
                        existing = frontmatter.load(f)
                    metadata = existing.metadata
                else:
                    metadata = {}
            except Exception:
                metadata = {}

        # 写回文件
        with open(filepath, "w", encoding="utf-8") as f:
            if metadata:
                f.write("---\n")
                f.write(yaml.dump(metadata, allow_unicode=True,
                                  default_flow_style=False, sort_keys=False))
                f.write("---\n")
            f.write(content.lstrip("\n"))

        new_hash = self._hash_file(filepath)
        # 实体文件夹：path 用文件夹名
        if os.path.basename(filepath) == "index.md":
            rel_path = os.path.relpath(os.path.dirname(filepath), self._root)
        else:
            rel_path = os.path.relpath(filepath, self._root)
        logger.info("文档已保存: %s (%s)", rel_path, new_hash[:12])
        return {"hash": new_hash, "path": rel_path}

    def create_document(self, category_id: str, doc_id: str,
                        content: str = "", metadata: dict = None) -> dict:
        """创建新文档（实体文件夹模式：创建 {doc_id}/index.md）。

        Args:
            category_id: 类别 ID
            doc_id: 文档 ID（不含 .md 后缀，可包含子目录路径）
            content: 正文内容
            metadata: frontmatter 字典

        Returns:
            {"hash": "...", "path": "..."}
        """
        cat = self._categories.get(category_id)
        if not cat:
            raise ValueError(f"未知文档类别: {category_id}")

        entity_dir = os.path.join(cat.directory, doc_id)
        filepath = os.path.join(entity_dir, "index.md")

        if os.path.isfile(filepath):
            raise FileExistsError(f"文档已存在: {doc_id}")

        os.makedirs(entity_dir, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            if metadata:
                f.write("---\n")
                f.write(yaml.dump(metadata, allow_unicode=True,
                                  default_flow_style=False, sort_keys=False))
                f.write("---\n")
            if content:
                f.write("\n")
                f.write(content)

        new_hash = self._hash_file(filepath)
        rel_path = os.path.relpath(entity_dir, self._root)
        logger.info("文档已创建: %s", rel_path)
        return {"hash": new_hash, "path": rel_path}

    def delete_document(self, category_id: str, doc_path: str):
        """删除文档。

        实体文件夹模式：删除整个实体目录（含所有资产）。
        传统文件模式：仅删除 .md 文件。
        """
        filepath = self._resolve_path(category_id, doc_path)
        if not filepath or not os.path.isfile(filepath):
            raise DocumentNotFoundError(
                f"文档不存在: {category_id}/{doc_path}"
            )

        # 实体文件夹：删除整个目录
        if os.path.basename(filepath) == "index.md":
            entity_dir = os.path.dirname(filepath)
            shutil.rmtree(entity_dir)
            logger.info("实体文件夹已删除: %s", entity_dir)
        else:
            os.remove(filepath)
            logger.info("文档已删除: %s", filepath)

    # ── 文件夹操作 ──

    def create_folder(self, category_id: str, folder_path: str) -> dict:
        """在类别目录中创建空文件夹。"""
        cat = self._categories.get(category_id)
        if not cat:
            raise ValueError(f"未知文档类别: {category_id}")
        full_path = os.path.join(cat.directory, folder_path)
        if os.path.exists(full_path):
            raise FileExistsError(f"文件夹已存在: {folder_path}")
        os.makedirs(full_path, exist_ok=True)
        logger.info("文件夹已创建: %s", full_path)
        return {"path": folder_path, "category": category_id}

    def delete_folder(self, category_id: str, folder_path: str) -> dict:
        """删除空文件夹（仅当为空时允许）。"""
        cat = self._categories.get(category_id)
        if not cat:
            raise ValueError(f"未知文档类别: {category_id}")
        full_path = os.path.join(cat.directory, folder_path)
        if not os.path.isdir(full_path):
            raise DocumentNotFoundError(f"文件夹不存在: {folder_path}")
        if os.listdir(full_path):
            raise ValueError(f"文件夹非空: {folder_path}，请先删除内容")
        os.rmdir(full_path)
        logger.info("文件夹已删除: %s", full_path)
        return {"path": folder_path, "category": category_id}

    # ── 移动/重命名 ──

    def move_document(self, category_id: str, doc_path: str,
                      new_path: str = None) -> dict:
        """移动/重命名文档。

        实体文件夹：移动/重命名整个实体目录。
        传统文件：移动/重命名 .md 文件。
        new_path 为新的相对路径（相对于类别目录，不含 .md）。
        """
        old_filepath = self._resolve_path(category_id, doc_path)
        if not old_filepath or not os.path.isfile(old_filepath):
            raise DocumentNotFoundError(f"文档不存在: {category_id}/{doc_path}")

        target_rel = new_path or doc_path
        cat = self._categories[category_id]

        # 判断是实体文件夹还是传统文件
        if os.path.basename(old_filepath) == "index.md":
            old_entity_dir = os.path.dirname(old_filepath)
            new_entity_dir = os.path.join(cat.directory, target_rel)

            if old_entity_dir == new_entity_dir:
                raise ValueError("源路径和目标路径相同")

            if os.path.exists(new_entity_dir):
                raise FileExistsError(f"目标已存在: {target_rel}")

            os.makedirs(os.path.dirname(new_entity_dir), exist_ok=True)
            os.rename(old_entity_dir, new_entity_dir)
            self._cleanup_empty_dirs(os.path.dirname(old_entity_dir), cat.directory)
            logger.info("实体文件夹已移动: %s → %s", old_entity_dir, new_entity_dir)
        else:
            new_filepath = os.path.join(cat.directory, f"{target_rel}.md")

            if old_filepath == new_filepath:
                raise ValueError("源路径和目标路径相同")

            if os.path.exists(new_filepath):
                raise FileExistsError(f"目标已存在: {target_rel}")

            os.makedirs(os.path.dirname(new_filepath), exist_ok=True)
            os.rename(old_filepath, new_filepath)
            self._cleanup_empty_dirs(os.path.dirname(old_filepath), cat.directory)
            logger.info("文档已移动: %s → %s", old_filepath, new_filepath)

        return {
            "old_path": f"{category_id}/{doc_path}",
            "new_path": f"{category_id}/{target_rel}",
            "category": category_id,
        }

    def move_folder(self, category_id: str, folder_path: str,
                    new_path: str = None) -> dict:
        """移动/重命名文件夹。"""
        cat = self._categories.get(category_id)
        if not cat:
            raise ValueError(f"未知文档类别: {category_id}")

        old_full = os.path.join(cat.directory, folder_path)
        if not os.path.isdir(old_full):
            raise DocumentNotFoundError(f"文件夹不存在: {folder_path}")

        target_rel = new_path or folder_path
        new_full = os.path.join(cat.directory, target_rel)

        if old_full == new_full:
            raise ValueError("源路径和目标路径相同")

        if os.path.exists(new_full):
            raise FileExistsError(f"目标已存在: {target_rel}")

        os.makedirs(os.path.dirname(new_full), exist_ok=True)
        os.rename(old_full, new_full)

        self._cleanup_empty_dirs(os.path.dirname(old_full), cat.directory)

        logger.info("文件夹已移动: %s → %s", old_full, new_full)
        return {
            "old_path": f"{category_id}/{folder_path}",
            "new_path": f"{category_id}/{target_rel}",
            "category": category_id,
        }

    @staticmethod
    def _cleanup_empty_dirs(start_dir: str, stop_dir: str):
        """删除空的父目录链，直到 stop_dir（不含）。"""
        current = start_dir
        while current and current.startswith(stop_dir) and current != stop_dir:
            try:
                if not os.path.isdir(current):
                    break
                if os.listdir(current):
                    break
                os.rmdir(current)
                current = os.path.dirname(current)
            except OSError:
                break

    # ── Git 集成 ──

    def git_commit(self, filepath: str, message: str = None):
        """为单个文件变更创建 Git 提交。"""
        try:
            import subprocess
            rel = os.path.relpath(filepath, self._root)
            msg = message or f"docs: update {rel}"
            subprocess.run(
                ["git", "add", rel],
                cwd=self._root, capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "commit", "-m", msg, "--no-gpg-sign"],
                cwd=self._root, capture_output=True, timeout=10,
            )
        except Exception as e:
            logger.warning("Git 自动提交失败: %s", e)

    # ── 内部方法 ──

    def _resolve_path(self, category_id: str, doc_path: str) -> Optional[str]:
        """将 category_id + doc_path 解析为实际文件路径。

        使用实体文件夹格式：{dir}/{doc_path}/index.md
        """
        cat = self._categories.get(category_id)
        if not cat:
            return None
        return os.path.join(cat.directory, doc_path, "index.md")

    @staticmethod
    def _hash_file(filepath: str) -> str:
        """计算文件的 SHA256 哈希。"""
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def hash_content(content: str) -> str:
        """计算文本内容的 SHA256 哈希。"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
