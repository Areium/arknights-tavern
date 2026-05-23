import os
import re
import logging

import frontmatter

logger = logging.getLogger(__name__)

# ── 核心章节提取规则 ──
# 每个类别定义一组 (章节名, 段落数) 规则，None 表示取该章节全文。
# 优先级从高到低：先匹配到的先提取。
_CORE_SECTIONS = {
    "races": [
        ("## 生理特征", 3),
        ("## 角色扮演提示", None),
    ],
    "classes": [
        ("## 战斗定位", 3),
        ("## 子职业一览", 1),
        ("## 角色扮演提示", None),
    ],
    "factions": [
        ("## 组织概述", 2),
    ],
    "items": [
        ("## 物品描述", 3),
        ("## 功能与效果", 2),
    ],
    "locations": [
        ("# 描述", 2),
    ],
    "weather": [
        ("## 天气概述", 2),
        ("## 视觉特征", 2),
    ],
}


# ── 属性英文名 → 中文名映射 ──
_ATTR_ENG_TO_CN = {
    "physical_strength": "物理强度",
    "tactical_planning": "战术规划",
    "emotional_stability": "情绪稳定性",
    "combat_skill": "战斗技巧",
    "originium_arts_assimilation": "源石技艺适应性",
    "charisma": "魅力",
    "physiological_tolerance": "生理耐受",
    "mobility": "战场机动",
}


class RegistryManager:
    """层级索引管理器：按深度加载 Markdown 数据文件，控制 token 注入量。

    核心概念：
      summary — 来自 _index.md 的 one-liner（始终注入，~30 token/条）
      core    — 文件中的关键章节（角色加载时注入，~150 token/条）
      full    — 完整文件内容（玩家显式检视时注入，~400 token/条）

    用法:
        registry = RegistryManager(project_root)
        ctx = registry.build_character_context({"race": "卡特斯", "class": "术师", ...})
    """

    def __init__(self, project_root: str = None):
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._root = project_root

        # {type: {key: {file, summary, ...}}}
        self._indexes: dict[str, dict] = {}
        # {type: {key: full_content}} — 文件内容级缓存
        self._file_cache: dict[str, dict[str, str]] = {}

        self._load()

    # ── 公开 API ──

    def resolve(self, type_: str, key: str, depth: str = "core") -> str:
        """解析一个引用，返回对应深度的文本。

        Args:
            type_: 数据类别（races / classes / factions / items / locations / weather）
            key:   索引中的键名（如 "卡特斯"、"术师"）
            depth: summary | core | full

        Returns:
            解析后的文本；引用断裂时返回空字符串。
        """
        if not key:
            return ""

        entries = self._indexes.get(type_, {})
        entry = entries.get(key)
        if entry is None:
            logger.debug("索引未命中: type=%s key=%s", type_, key)
            return ""

        if depth == "summary":
            return entry.get("summary", "")

        filepath = entry.get("file", "")
        content = self._read_file(type_, key, filepath)
        if not content:
            return entry.get("summary", "")

        if depth == "core":
            return self._extract_core(content, type_)

        # full
        return content

    def get_summary(self, type_: str, key: str) -> str:
        """快捷方法：获取一项的 summary。"""
        return self.resolve(type_, key, "summary")

    def get_full(self, type_: str, key: str) -> str:
        """快捷方法：获取一项的全文（玩家检视物品时调用）。"""
        return self.resolve(type_, key, "full")

    def build_character_context(self, metadata: dict) -> str:
        """为角色构建引用上下文，注入到 system prompt。

        Args:
            metadata: 角色卡的 frontmatter 字典，需含 race / class / faction / key_items 字段。

        Returns:
            格式化的上下文文本，可直接拼接到 system prompt。
        """
        if not metadata:
            return ""

        parts = []

        race = metadata.get("race", "")
        if race:
            text = self.resolve("races", race, "core")
            if text:
                parts.append(f"【种族：{race}】\n{text}")

        class_ = metadata.get("class", "")
        if class_:
            text = self.resolve("classes", class_, "core")
            if text:
                parts.append(f"【职业：{class_}】\n{text}")

        faction = metadata.get("faction", "")
        if faction:
            text = self.resolve("factions", faction, "summary")
            if text:
                parts.append(f"【所属势力：{faction}】\n{text}")

        # 角色自身的关键物品注入 core 深度
        key_items = metadata.get("key_items", [])
        if key_items:
            item_texts = []
            for item_name in key_items:
                text = self.resolve("items", item_name, "core")
                if text:
                    item_texts.append(f"「{item_name}」：{text}")
            if item_texts:
                parts.append("【关键物品】\n" + "\n".join(item_texts))

        # 角色属性注入 core 深度（每个属性提取对应等级的完整描述）
        attrs = metadata.get("attributes", {})
        if attrs:
            attr_texts = self.build_character_attributes_context(attrs)
            if attr_texts:
                parts.append(f"【角色属性】\n{attr_texts}")

        return "\n\n".join(parts) if parts else ""

    def build_character_attributes_context(self, attributes: dict) -> str:
        """为角色的属性数值构建等级描述上下文。

        Args:
            attributes: 角色卡的 attributes 字典，如 {physical_strength: 7, tactical_planning: 5}

        Returns:
            格式化的属性等级描述文本。
        """
        if not attributes:
            return ""

        lines = []
        for eng_name, level in sorted(attributes.items()):
            cn_name = _ATTR_ENG_TO_CN.get(eng_name)
            if not cn_name:
                continue
            level = int(level) if level else 5
            level = max(1, min(10, level))

            # 读取对应属性文件的完整内容
            full = self.resolve("attributes", cn_name, "full")
            if not full:
                summary = self.resolve("attributes", cn_name, "summary")
                lines.append(f"· {summary}: {level}/10")
                continue

            # 从完整文件中提取该等级的段落
            level_text = self._extract_level_description(full, level)
            if level_text:
                lines.append(f"· {level_text}")
            else:
                summary = self.resolve("attributes", cn_name, "summary")
                lines.append(f"· {summary}: {level}/10")

        return "\n".join(lines)

    def _extract_level_description(self, content: str, level: int) -> str:
        """从属性文件中提取指定等级的段落文本。

        属性文件中每个等级以 '### X 级' 开头，包含描述和游戏表现两部分。
        """
        # 匹配 "### 7 级 — 强壮" 或 "### 7 级 — 严厉认知障碍" 等
        pattern = rf"### {level}\s*级\s*[—\-–]+\s*(.*?)(?=\n### |\Z)"
        m = re.search(pattern, content, re.DOTALL)
        if not m:
            return ""

        section = m.group(0).strip()
        # 取第一行（标题行）作为简短描述
        first_line = section.split("\n")[0].strip().lstrip("#").strip()
        # 提取第一段正文（去掉游戏表现的后半段描述，只保留描述性文字）
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

    def build_item_context(self, item_name: str) -> str:
        """为指定物品构建全文上下文（玩家检视物品时调用）。"""
        return self.resolve("items", item_name, "full")

    def build_scene_items_context(self, item_names: list[str]) -> str:
        """为场景物品列表构建 summary 级上下文。

        场景物品默认只注入 summary，避免大量物品占满 prompt。
        """
        if not item_names:
            return ""
        lines = []
        for name in item_names:
            summary = self.resolve("items", name, "summary")
            if summary:
                lines.append(f"- {name}：{summary}")
        return "\n".join(lines) if lines else ""

    def list_keys(self, type_: str) -> list[str]:
        """列出某个类别下所有已注册的 key。"""
        return list(self._indexes.get(type_, {}).keys())

    def has(self, type_: str, key: str) -> bool:
        """检查某个引用是否存在。"""
        return key in self._indexes.get(type_, {})

    def validate(self) -> list[str]:
        """校验所有索引的引用完整性，返回问题描述列表。"""
        issues = []
        for type_, entries in self._indexes.items():
            for key, entry in entries.items():
                filepath = entry.get("file", "")
                if not filepath:
                    issues.append(f"[{type_}] '{key}': 缺少 file 字段")
                elif not os.path.isfile(filepath):
                    issues.append(f"[{type_}] '{key}': 文件不存在 → {filepath}")
        if issues:
            logger.warning("索引完整性检查发现 %d 个问题", len(issues))
        return issues

    # ── 内部方法 ──

    def _load(self):
        """加载 data/_INDEX.md 及各子索引。"""
        master_path = os.path.join(self._root, "data", "_INDEX.md")
        if not os.path.isfile(master_path):
            logger.warning("总索引文件未找到: %s", master_path)
            return

        try:
            with open(master_path, "r", encoding="utf-8") as f:
                master = frontmatter.load(f)
        except Exception as e:
            logger.error("加载总索引失败: %s", e)
            return

        categories = master.metadata.get("index", {})
        for cat_name, cat_info in categories.items():
            index_rel = cat_info.get("index", "")
            dir_rel = cat_info.get("dir", "")
            if not index_rel:
                continue

            index_path = os.path.join(self._root, index_rel)
            dir_path = os.path.join(self._root, dir_rel) if dir_rel else ""

            if os.path.isfile(index_path):
                self._load_category(cat_name, index_path, dir_path)
            else:
                logger.debug("子索引尚未创建，跳过: %s", index_path)

    def _load_category(self, cat_name: str, index_path: str, dir_path: str):
        """加载单个类别的 _index.md，构建 key→{file, summary, ...} 映射。"""
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = frontmatter.load(f)
        except Exception as e:
            logger.error("加载子索引失败 %s: %s", index_path, e)
            return

        entries = data.metadata.get("index") or {}
        self._indexes[cat_name] = {}

        for key, entry in entries.items():
            file_rel = entry.get("file", "")
            self._indexes[cat_name][key] = {
                "file": os.path.join(dir_path, file_rel) if file_rel and dir_path else "",
                "summary": entry.get("summary", ""),
                **{k: v for k, v in entry.items() if k not in ("file", "summary")},
            }

        logger.info("已加载索引 [%s]: %d 个条目", cat_name, len(self._indexes[cat_name]))

    def _read_file(self, type_: str, key: str, filepath: str) -> str:
        """读取详细 Markdown 文件，带缓存。

        支持实体文件夹（{name}/index.md）和传统文件（{name}.md）。
        """
        if type_ not in self._file_cache:
            self._file_cache[type_] = {}

        if key in self._file_cache[type_]:
            return self._file_cache[type_][key]

        # 解析实际文件路径
        actual = self._resolve_filepath(filepath)
        if not actual:
            return ""

        try:
            with open(actual, "r", encoding="utf-8") as f:
                data = frontmatter.load(f)
            content = data.content
            self._file_cache[type_][key] = content
            return content
        except Exception as e:
            logger.error("读取文件失败 %s: %s", actual, e)
            return ""

    @staticmethod
    def _resolve_filepath(filepath: str) -> str | None:
        """解析文件路径，支持实体文件夹和传统 .md 文件。"""
        if not filepath:
            return None
        if os.path.isfile(filepath):
            return filepath
        # 如果 filepath 是 {name}.md，尝试 {name}/index.md
        if filepath.endswith(".md"):
            stem = os.path.splitext(filepath)[0]
            entity = os.path.join(stem, "index.md")
            if os.path.isfile(entity):
                return entity
        # 如果 filepath 是 {name}/index.md，尝试 {name}.md
        if os.path.basename(filepath) == "index.md":
            parent = os.path.dirname(filepath)
            legacy = parent + ".md"
            if os.path.isfile(legacy):
                return legacy
        return None

    def _extract_core(self, content: str, type_: str) -> str:
        """从 Markdown 正文中提取核心章节。

        根据 _CORE_SECTIONS 配置，匹配指定章节并截取指定段落数。
        """
        rules = _CORE_SECTIONS.get(type_, [])
        if not rules:
            # 无规则 → 返回全文前 150 字作为 fallback
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
        """按 # 和 ## 标题拆分 Markdown 正文，返回 [(标题, 正文), ...] 列表。"""
        content = content.strip()

        # 按 # 或 ## 拆分（保留分隔符）
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
        """截取文本的前 N 个段落（空行分隔）。limit=None 时返回全文。"""
        if not text:
            return ""
        if limit is None:
            return text

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return "\n\n".join(paragraphs[:limit])
