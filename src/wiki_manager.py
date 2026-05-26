"""
WikiManager — 统一文档入口。

职责：
- 扫描 data/ 下所有文档，构建全量目录索引（name + summary + path + imports）
- 沿 imports 链 BFS 展开，按深度分级预加载（full / core / summary）
- 提供 query() 供 LLM Function Calling 按需查询
- 提供 format_catalog_summary() 生成轻量目录注入 system prompt

深度约定：
  depth 0 = full    入口文档全文（如角色卡）
  depth 1 = core    直接 imports 的关键章节
  depth 2 = summary imports 的 imports 的 one-liner
"""

import os
import re
import logging

import yaml
import frontmatter

logger = logging.getLogger(__name__)

from constants import CORE_SECTIONS, ATTR_ENG_TO_CN


class WikiManager:
    def __init__(self, project_root: str = None):
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._root = project_root
        # "category/id" → {category, id, name, summary, path, imports: [str]}
        self._catalog: dict[str, dict] = {}
        # {category: [id, ...]}
        self._by_category: dict[str, list[str]] = {}
        self._build_catalog()

    def refresh(self):
        """重建全量目录索引（文档增删后调用）。"""
        self._catalog.clear()
        self._by_category.clear()
        self._build_catalog()
        logger.info("WikiManager: 目录已刷新，共 %d 个文档", len(self._catalog))

    # ── 目录构建 ──

    def _build_catalog(self):
        """扫描 categories.yaml 所有类别，解析 frontmatter 构建全量索引。"""
        yaml_path = os.path.join(self._root, "data", "categories.yaml")
        if not os.path.isfile(yaml_path):
            logger.warning("categories.yaml 未找到: %s", yaml_path)
            return

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        categories = data.get("categories", {})

        for cat_name, cat_info in categories.items():
            dir_rel = cat_info if isinstance(cat_info, str) else cat_info.get("dir", "")
            # 解析相对于 project root 的路径
            if dir_rel.startswith("data/"):
                full_dir = os.path.join(self._root, dir_rel)
            else:
                full_dir = os.path.join(self._root, "data", dir_rel)
            if os.path.isdir(full_dir):
                self._scan_category(cat_name, full_dir)

        total = len(self._catalog)
        logger.info("WikiManager: 已索引 %d 个文档, %d 个类别", total, len(self._by_category))

    def _scan_category(self, cat_name: str, dir_path: str):
        """扫描一个类别目录，提取所有实体文档。"""
        ids = []

        for item in sorted(os.listdir(dir_path)):
            item_path = os.path.join(dir_path, item)
            # 实体文件夹 (item/index.md)
            index_md = os.path.join(item_path, "index.md")
            if os.path.isdir(item_path) and os.path.isfile(index_md):
                entry = self._parse_doc(cat_name, item, index_md)
                if entry:
                    self._catalog[f"{cat_name}/{item}"] = entry
                    ids.append(item)
                continue

        # 传统 .md 文件 (item.md)
        for fn in sorted(os.listdir(dir_path)):
            if not fn.endswith(".md"):
                continue
            if fn in ("_index.md", "_INDEX.md", "README.md", "TEMPLATE.md"):
                continue
            filepath = os.path.join(dir_path, fn)
            if not os.path.isfile(filepath):
                continue
            doc_id = os.path.splitext(fn)[0]
            path_key = f"{cat_name}/{doc_id}"
            if path_key in self._catalog:
                continue
            entry = self._parse_doc(cat_name, doc_id, filepath)
            if entry:
                self._catalog[path_key] = entry
                ids.append(doc_id)

        if ids:
            self._by_category[cat_name] = ids

    def _parse_doc(self, category: str, doc_id: str, filepath: str) -> dict | None:
        """解析单个文档的 frontmatter，返回 catalog entry。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                post = frontmatter.load(f)
        except Exception:
            return None

        meta = post.metadata
        name = meta.get("name", doc_id)
        summary = meta.get("summary", "") or self._first_line(post.content)

        # 提取 imports
        imports: list[str] = []
        raw = meta.get("imports", [])
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    # 取 "path | name" 的 path 部分
                    imports.append(item.strip().split(" | ")[0].strip())

        return {
            "category": category,
            "id": doc_id,
            "name": name,
            "summary": summary,
            "path": filepath,
            "imports": imports,
        }

    @staticmethod
    def _first_line(content: str) -> str:
        for line in content.strip().split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            return stripped[:80]
        return ""

    # ── 依赖链展开 ──

    def resolve_imports_chain(self, entry_paths: list[str], max_depth: int = 2) -> dict[str, dict]:
        """从入口文档沿 imports 链 BFS 展开，返回 {path: {depth, name, summary, content}}。

        depth 0: 入口文档 → full content
        depth 1: 直接 imports → core (关键章节)
        depth 2: imports 的 imports → summary (one-liner)
        """
        result: dict[str, dict] = {}
        visited: set[str] = set()
        # queue: (path, depth)
        queue: list[tuple[str, int]] = []

        for ep in entry_paths:
            ep = self._normalize_path(ep)
            if ep and ep not in visited:
                queue.append((ep, 0))
                visited.add(ep)

        while queue:
            path, depth = queue.pop(0)
            entry = self._catalog.get(path)
            if not entry:
                continue

            content = ""
            if depth == 0:
                content = self._read_content(entry["path"])
            elif depth == 1:
                content = self._extract_core(entry["category"], entry["path"])
            # depth >= 2: content 为空，仅注入 summary

            result[path] = {
                "depth": depth,
                "name": entry["name"],
                "summary": entry["summary"],
                "content": content,
                "category": entry["category"],
            }

            # 继续展开 imports
            if depth < max_depth:
                for imp in entry.get("imports", []):
                    imp = self._normalize_path(imp)
                    if imp and imp not in visited:
                        visited.add(imp)
                        queue.append((imp, depth + 1))

        return result

    def _normalize_path(self, path: str) -> str:
        """规范化路径为 'category/id' 格式。"""
        path = path.strip()
        if "/" not in path:
            return ""
        parts = path.split("/")
        if len(parts) < 2:
            return ""
        return f"{parts[0]}/{'/'.join(parts[1:])}"

    # ── 查询 ──

    def query(self, query_str: str) -> str:
        """模糊匹配文档。命中 1 个返回全文，多个返回候选列表，否则返回提示。"""
        q = query_str.strip().lower()
        if not q:
            return "（wiki_query: 请提供查询关键词）"

        # 精确 path 匹配
        exact = self._normalize_path(query_str)
        if exact and exact in self._catalog:
            return self._format_doc_full(exact)

        # 按 name/id 匹配
        matches: list[str] = []
        for path_key, entry in self._catalog.items():
            score = 0
            if q == entry["name"].lower():
                score = 100
            elif q == entry["id"].lower():
                score = 90
            elif q in entry["name"].lower():
                score = 50
            elif q in entry["id"].lower():
                score = 40
            elif q in entry["summary"].lower():
                score = 20
            if score > 0:
                matches.append((score, path_key))

        matches.sort(key=lambda x: x[0], reverse=True)

        if not matches:
            return f"（wiki_query: 未找到与 '{query_str}' 相关的文档。可用文档列表请参见目录摘要。）"

        if len(matches) == 1 or matches[0][0] >= 90:
            return self._format_doc_full(matches[0][1])

        # 多个候选：返回列表
        lines = [f"找到 {len(matches)} 个与 '{query_str}' 相关的文档："]
        for score, path_key in matches[:8]:
            entry = self._catalog[path_key]
            lines.append(f"- [{path_key}] {entry['name']}: {entry['summary'][:60]}")
        lines.append("\n请指定确切名称或路径以获取全文。")
        return "\n".join(lines)

    def get_document(self, category: str, doc_id: str, depth: str = "full") -> str:
        """精确获取指定文档内容。"""
        path_key = f"{category}/{doc_id}"
        entry = self._catalog.get(path_key)
        if not entry:
            return ""
        if depth == "summary":
            return entry["summary"]
        if depth == "core":
            return self._extract_core(category, entry["path"])
        return self._read_content(entry["path"])

    # ── 角色 context 构建 (从 RegistryManager 迁移) ──

    def build_character_context(self, metadata: dict, entity_whitelist: dict = None) -> str:
        """为角色构建引用上下文，注入到 system prompt。

        Args:
            metadata: 角色卡的 frontmatter 字典。
            entity_whitelist: 可选，会话索引配置 {mode, enabled_categories, enabled_entities}。
                mode="whitelist" 时仅注入白名单内的实体；None 或 mode="all" 时不限制。

        Returns:
            格式化的上下文文本。
        """
        if not metadata:
            return ""

        def _is_entity_allowed(category: str, key: str) -> bool:
            if entity_whitelist is None:
                return True
            if entity_whitelist.get("mode") != "whitelist":
                return True
            cats = entity_whitelist.get("enabled_categories", [])
            ents = entity_whitelist.get("enabled_entities", {})
            if category in cats:
                return True
            cat_ents = ents.get(category, [])
            return key in cat_ents

        parts = []

        race = metadata.get("race", "")
        if race and _is_entity_allowed("races", race):
            text = self.get_document("races", race, "core")
            if text:
                parts.append(f"【种族：{race}】\n{text}")

        class_ = metadata.get("class", "")
        if class_ and _is_entity_allowed("classes", class_):
            text = self.get_document("classes", class_, "core")
            if text:
                parts.append(f"【职业：{class_}】\n{text}")

        faction = metadata.get("faction", "")
        if faction and _is_entity_allowed("factions", faction):
            text = self.get_document("factions", faction, "summary")
            if text:
                parts.append(f"【所属势力：{faction}】\n{text}")

        key_items = metadata.get("key_items", [])
        if key_items:
            item_texts = []
            for item_name in key_items:
                if _is_entity_allowed("items", item_name):
                    text = self.get_document("items", item_name, "core")
                    if text:
                        item_texts.append(f"「{item_name}」：{text}")
            if item_texts:
                parts.append("【关键物品】\n" + "\n".join(item_texts))

        attrs = metadata.get("attributes", {})
        if attrs:
            attr_texts = self.build_character_attributes_context(attrs)
            if attr_texts:
                parts.append(f"【角色属性】\n{attr_texts}")

        return "\n\n".join(parts) if parts else ""

    def build_character_attributes_context(self, attributes: dict) -> str:
        """为角色的属性数值构建等级描述上下文。"""
        if not attributes:
            return ""

        lines = []
        for eng_name, level in sorted(attributes.items()):
            cn_name = ATTR_ENG_TO_CN.get(eng_name)
            if not cn_name:
                continue
            level = int(level) if level else 5
            level = max(1, min(10, level))

            full = self.get_document("attributes", cn_name, "full")
            if not full:
                summary = self.get_document("attributes", cn_name, "summary")
                lines.append(f"· {summary}: {level}/10")
                continue

            level_text = self._extract_level_description(full, level)
            if level_text:
                lines.append(f"· {level_text}")
            else:
                summary = self.get_document("attributes", cn_name, "summary")
                lines.append(f"· {summary}: {level}/10")

        return "\n".join(lines)

    @staticmethod
    def _extract_level_description(content: str, level: int) -> str:
        """从属性文件中提取指定等级的段落文本。"""
        import re as _re
        pattern = rf"### {level}\s*级\s*[—\-–]+\s*(.*?)(?=\n### |\Z)"
        m = _re.search(pattern, content, _re.DOTALL)
        if not m:
            return ""

        section = m.group(0).strip()
        first_line = section.split("\n")[0].strip().lstrip("#").strip()
        body_lines = section.split("\n")[1:]
        desc_parts = []
        for line in body_lines:
            line = line.strip()
            if line.startswith("**游戏表现**"):
                break
            if line:
                desc_parts.append(line)
        desc = " ".join(desc_parts)[:120]
        return f"{first_line}：{desc}" if desc else first_line

    def validate_imports(self) -> list[str]:
        """校验 catalog 中所有 imports 的引用完整性，返回问题描述列表。"""
        issues = []
        for path_key, entry in self._catalog.items():
            for imp in entry.get("imports", []):
                norm = self._normalize_path(imp)
                if norm and norm not in self._catalog:
                    issues.append(f"[{entry['category']}] '{entry['name']}': 引用不存在 → {imp}")
        if issues:
            logger.warning("imports 完整性检查发现 %d 个问题", len(issues))
        return issues

    def _format_doc_full(self, path_key: str) -> str:
        """格式化返回文档全文。"""
        entry = self._catalog[path_key]
        content = self._read_content(entry["path"])
        header = f"【{entry['category']}/{entry['id']}】{entry['name']}"
        if entry["summary"]:
            header += f"\n> {entry['summary']}"
        return f"{header}\n\n{content}"

    # ── 目录摘要 ──

    # 剧情叙述模式下注入的文档目录类别
    NARRATIVE_CATALOG_CATS = {"characters", "factions", "locations", "items", "world"}

    def format_catalog_summary(self, categories: set[str] | None = None) -> str:
        """格式化轻量目录，按类别分组，供 system prompt 注入。

        Args:
            categories: 要包含的类别集合。为 None 时包含全部类别。
        """
        if categories is not None and not isinstance(categories, set):
            categories = set(categories)

        lines = ["【可用文档目录】"]
        category_order = [
            ("characters", "角色"), ("world", "世界设定"),
            ("factions", "势力"), ("locations", "地点"),
            ("items", "物品"), ("races", "种族"), ("classes", "职业"),
            ("attributes", "属性"), ("weather", "天气"), ("enemies", "敌人"),
            ("rules", "规则"), ("plots", "剧情"),
        ]
        for cat_name, cat_label in category_order:
            if categories is not None and cat_name not in categories:
                continue
            ids = self._by_category.get(cat_name, [])
            if not ids:
                continue
            entries = []
            for doc_id in ids:
                entry = self._catalog.get(f"{cat_name}/{doc_id}")
                if entry:
                    entries.append((entry["name"], entry["summary"][:50]))
            if entries:
                lines.append(f"\n## {cat_label}")
                for name, summary in entries:
                    if summary:
                        lines.append(f"- {name}: {summary}")
                    else:
                        lines.append(f"- {name}")
        return "\n".join(lines)

    # ── 内容读取辅助 ──

    def _read_content(self, filepath: str) -> str:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                post = frontmatter.load(f)
            return post.content.strip()
        except Exception:
            return ""

    def _extract_core(self, category: str, filepath: str) -> str:
        """提取文档的关键章节 (core 深度)。复用 RegistryManager 的三级深度模式。"""
        content = self._read_content(filepath)
        if not content:
            return ""

        rules = CORE_SECTIONS.get(category, [])
        if not rules:
            return content.strip()[:150]

        sections = self._split_by_headings(content)
        extracted = []
        for heading, body in sections:
            heading_text = re.sub(r"^#{1,2}\s*", "", heading.strip())
            for rule_heading, para_limit in rules:
                rule_text = re.sub(r"^#{1,2}\s*", "", rule_heading)
                if heading_text == rule_text:
                    text = self._truncate_paragraphs(body, para_limit)
                    if text:
                        extracted.append(f"{heading}\n{text}")
                    break

        return "\n\n".join(extracted) if extracted else ""

    @staticmethod
    def _split_by_headings(content: str) -> list[tuple[str, str]]:
        content = content.strip()
        parts = re.split(r"\n(?=##?\s)", content)
        result = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            m = re.match(r"(#{1,2}\s.*?)(?:\n|$)", part)
            if m:
                heading = m.group(1)
                body = part[len(heading):].strip()
                result.append((heading, body))
        return result

    @staticmethod
    def _truncate_paragraphs(text: str, limit: int | None) -> str:
        if not text:
            return ""
        if limit is None:
            return text
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return "\n\n".join(paragraphs[:limit])

    # ── 摘要回填 ──

    _SUMMARY_PROMPT = (
        "你是一个文档摘要生成器。根据以下内容，输出一句中文摘要（≤50字），"
        "概括该文档的核心主题。\n"
        "文档类别：{category}\n"
        "文档名称：{name}\n"
        "---\n"
        "{content}\n"
        "---\n"
        "只输出摘要文本，不要引号、前缀或解释。"
    )

    def _needs_summary(self, filepath: str) -> bool:
        """检查文档的 frontmatter 是否缺少 summary 字段。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                post = frontmatter.load(f)
            return not post.metadata.get("summary", "").strip()
        except Exception:
            return False

    def backfill_summaries(self, llm, dry_run: bool = False) -> dict:
        """为所有缺少 summary 的文档用 LLM 生成摘要并写回 frontmatter。

        Args:
            llm: LLM 实例（需有 chat 方法，返回 dict 格式）
            dry_run: True 时只预览，不修改文件

        Returns:
            {"generated": int, "skipped": int, "errors": int, "details": [...]}
        """
        generated = 0
        skipped = 0
        errors = 0
        details: list[dict] = []

        for path_key, entry in self._catalog.items():
            filepath = entry["path"]
            if not self._needs_summary(filepath):
                skipped += 1
                continue

            content = self._read_content(filepath)
            prompt = self._SUMMARY_PROMPT.format(
                category=entry["category"],
                name=entry["name"],
                content=content[:2000],
            )

            try:
                result = llm.chat(
                    [{"role": "user", "content": prompt}],
                    stream=False,
                )
                summary = result.get("content", "").strip()
            except Exception as e:
                logger.error("摘要生成失败 [%s]: %s", path_key, e)
                errors += 1
                details.append({"path": path_key, "summary": "", "error": str(e)})
                continue

            # 清理生成结果中可能残留的引号和换行
            summary = summary.strip().strip("「」『』\"'“”").strip()
            if not summary:
                errors += 1
                details.append({"path": path_key, "summary": "", "error": "空摘要"})
                continue

            if dry_run:
                details.append({"path": path_key, "summary": summary, "dry_run": True})
                generated += 1
                continue

            if self._inject_summary(filepath, summary):
                details.append({"path": path_key, "summary": summary, "written": True})
                generated += 1
                logger.info("摘要已写入: %s → %s", path_key, summary)
            else:
                errors += 1
                details.append({"path": path_key, "summary": summary, "error": "写入失败"})

        if not dry_run and generated > 0:
            self.refresh()

        logger.info(
            "backfill_summaries 完成: 生成=%d, 跳过=%d, 错误=%d",
            generated, skipped, errors,
        )
        return {"generated": generated, "skipped": skipped, "errors": errors, "details": details}

    @staticmethod
    def _inject_summary(filepath: str, summary: str) -> bool:
        """在文档 frontmatter 中 name 字段后插入 summary。保留其他格式不变。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception:
            return False

        if not raw.startswith("---"):
            return False
        end_idx = raw.find("---", 3)
        if end_idx == -1:
            return False

        yaml_str = raw[3:end_idx]
        body = raw[end_idx + 3:]

        lines = yaml_str.split("\n")
        # 去掉首尾空白行
        while lines and lines[0].strip() == "":
            lines.pop(0)
        while lines and lines[-1].strip() == "":
            lines.pop()

        new_lines = []
        inserted = False
        for line in lines:
            new_lines.append(line)
            if not inserted and re.match(r"^name:", line):
                indent = line[:len(line) - len(line.lstrip())]
                escaped = summary.replace('"', '\\"')
                new_lines.append(f'{indent}summary: "{escaped}"')
                inserted = True

        if not inserted:
            escaped = summary.replace('"', '\\"')
            new_lines.insert(0, f'summary: "{escaped}"')

        new_raw = "---\n" + "\n".join(new_lines) + "\n---" + body

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_raw)
            return True
        except Exception:
            return False
