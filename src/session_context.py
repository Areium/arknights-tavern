"""
SessionContext — 会话级文档缓存。

职责：
- 持有预加载文档（沿 imports 链展开的结果）和 Wiki 按需查询缓存
- 格式化为 system prompt 可注入的文本
- 角色变化时刷新预加载
"""

import re
import logging

logger = logging.getLogger(__name__)


class SessionContext:
    """会话共享的文档上下文缓存。"""

    def __init__(self):
        # {path: {depth, name, summary, content, category}}
        self.preloaded: dict[str, dict] = {}
        # {path: content}
        self.wiki_retrieved: dict[str, str] = {}

    def refresh_preload(self, wiki_manager, character_names: list[str]):
        """根据当前场景角色刷新预加载文档。

        Args:
            wiki_manager: WikiManager 实例
            character_names: 场景中所有角色名列表
        """
        if not wiki_manager:
            return

        entry_paths = [f"characters/{name}" for name in character_names]
        self.preloaded = wiki_manager.resolve_imports_chain(entry_paths, max_depth=1)

        depth0 = sum(1 for d in self.preloaded.values() if d["depth"] == 0)
        depth1 = sum(1 for d in self.preloaded.values() if d["depth"] == 1)
        logger.info(
            "SessionContext: 预加载 %d 个文档 (depth0=%d depth1=%d)",
            len(self.preloaded), depth0, depth1,
        )

    def add_wiki_result(self, path: str, content: str):
        """缓存一次 Wiki 查询结果。key 规范化为 canonical path 格式。

        content 首行格式为 【category/id】name，从中提取 canonical path。
        如果 path 已经是 "category/id" 格式则直接使用。
        """
        normalized = self._normalize_wiki_key(path, content)
        self.wiki_retrieved[normalized] = content

    @staticmethod
    def _normalize_wiki_key(path: str, content: str) -> str:
        """从 query_str 或 content 中提取 canonical path。"""
        if "/" in path and not path.startswith("【"):
            return path
        match = re.match(r"【(.+?)】", content)
        if match:
            return match.group(1)
        return path

    def format_preloaded(self) -> str:
        """将预加载文档格式化为 system prompt 可注入的文本。"""
        if not self.preloaded:
            return ""

        parts = ["【预加载资料】"]

        # depth 0: 角色卡原文（如有）
        depth0 = {p: d for p, d in self.preloaded.items() if d["depth"] == 0}
        if depth0:
            parts.append("\n## 场景角色")
            for path, doc in depth0.items():
                if doc["content"]:
                    parts.append(f"\n### {doc['name']} [{path}]")
                    parts.append(doc["content"])

        # depth 1: 直接引用 — core
        depth1 = {p: d for p, d in self.preloaded.items() if d["depth"] == 1 and d["content"]}
        if depth1:
            parts.append("\n## 相关设定")
            for path, doc in depth1.items():
                parts.append(f"\n### {doc['name']} [{path}]")
                parts.append(doc["content"])

        # depth 2: 间接引用 — summary
        depth2 = {p: d for p, d in self.preloaded.items() if d["depth"] >= 2}
        if depth2:
            parts.append("\n## 延伸参考")
            for path, doc in depth2.items():
                parts.append(f"- {doc['name']} [{path}]: {doc['summary']}")

        return "\n".join(parts)

    def format_wiki_retrieved(self) -> str:
        """格式化已缓存的 Wiki 查询结果。"""
        if not self.wiki_retrieved:
            return ""
        parts = ["\n【已查询的 Wiki 文档】"]
        for path, content in self.wiki_retrieved.items():
            parts.append(f"\n### [{path}]\n{content}")
        return "\n".join(parts)
