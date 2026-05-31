"""
Wiki 预取 Hook：每轮叙述开始前自动预取剧情上下文中提到的 wiki 文档。

不增加 LLM 调用轮次——纯文件读取，毫秒级。
预取结果存入 session_context.wiki_retrieved，由 SceneManager 注入 prompt。
"""

from __future__ import annotations

import logging

from .base import HookContext, NarrativeHook

logger = logging.getLogger(__name__)

# 预取优先级：数字越小越优先
CATEGORY_PRIORITY: dict[str, int] = {
    "locations": 0,
    "factions": 1,
    "world": 2,
    "items": 3,
    "races": 4,
    "classes": 4,
    "attributes": 5,
    "weather": 5,
    "characters": 6,  # 角色已在 imports chain 预加载，通常不需要
    "plots": 7,
    "enemies": 7,
    "rules": 7,
}


class WikiPreFetchHook(NarrativeHook):
    """在每轮叙述开始前自动预取 wiki 文档。

    priority=80：在 AttributeRollHook(50) 之后执行，确保检定已完成。
    """

    MAX_PREFETCH = 5

    @property
    def priority(self) -> int:
        return 80

    def on_before_narration(self, ctx: HookContext) -> list[dict]:
        """执行预取，不产生 SSE 事件。"""
        self._prefetch(ctx)
        return []

    def get_prompt_injection(self, ctx: HookContext) -> str | None:
        """预取内容通过 SceneManager 注入 <reference>，不走此路径。"""
        return None

    # ── 预取逻辑 ──

    def _prefetch(self, ctx: HookContext) -> None:
        session = ctx.session
        overlay = session.overlay if hasattr(session, "overlay") else None
        scene = session.scene_manager if hasattr(session, "scene_manager") else None
        if not scene:
            return

        sc = scene._session_context if hasattr(scene, "_session_context") else None
        wm = scene._wiki_manager if hasattr(scene, "_wiki_manager") else None
        if not sc or not wm:
            return

        # 1. 收集候选文本源
        texts = self._collect_texts(ctx, overlay)

        if not texts:
            return

        # 2. 提取匹配 catalog 的实体
        entities = self._extract_entities(wm, texts, sc, overlay)

        if not entities:
            logger.debug("WikiPreFetch: 无新实体可预取")
            return

        # 3. 按优先级排序，限制数量
        entities = self._prioritize(entities)[:self.MAX_PREFETCH]

        # 4. 预取并存储
        for path, name in entities:
            try:
                category, doc_id = path.split("/", 1)
            except ValueError:
                continue
            content = wm.get_document(category, doc_id, "core")
            if content:
                sc.add_wiki_result(path, content)
                logger.debug("WikiPreFetch: 预取 %s (%s)", path, name)

        if entities:
            logger.info(
                "WikiPreFetch: 本轮预取 %d 个文档: %s",
                len(entities),
                ", ".join(name for _, name in entities[:5]),
            )

    # ── 文本收集 ──

    @staticmethod
    def _collect_texts(ctx: HookContext, overlay) -> list[str]:
        """收集用于实体提取的文本源。"""
        texts = []

        # 上一轮叙述文本
        session = ctx.session
        if hasattr(session, "_narration_history") and session._narration_history:
            last_entry = session._narration_history[-1]
            last_text = last_entry.get("text", "")
            if last_text:
                texts.append(last_text)

        if not overlay:
            return texts

        # 当前节拍
        current_beat = overlay.get_current_beat()
        if current_beat:
            for field in ("content", "reveals"):
                val = current_beat.get(field, "")
                if val:
                    texts.append(val)

        # 下一节拍
        next_beat = overlay.get_next_beat()
        if next_beat:
            for field in ("content", "reveals"):
                val = next_beat.get(field, "")
                if val:
                    texts.append(val)

        # 剧情日志（最近 3 条）
        plot_log = overlay.read_session_doc("plot_log.md") or ""
        if plot_log:
            # 取末尾的轮次条目
            log_lines = [l for l in plot_log.split("\n") if l.startswith("[轮次")]
            if log_lines:
                texts.append("\n".join(log_lines[-3:]))

        return texts

    # ── 实体提取 ──

    @staticmethod
    def _extract_entities(wm, texts: list[str], sc, overlay) -> list[tuple[str, str]]:
        """扫描 catalog 中所有文档名，在文本源中匹配。

        Returns:
            [(canonical_path, display_name), ...] 去重去已加载后的列表
        """
        combined = "\n".join(texts)
        results = []
        seen = set()

        for path, entry in wm._catalog.items():
            name = entry.get("name", "")
            if not name or len(name) < 2:
                continue
            if path in seen:
                continue
            if WikiPreFetchHook._is_loaded(path, name, sc):
                continue
            if name in combined:
                seen.add(path)
                results.append((path, name))

        return results

    @staticmethod
    def _is_loaded(path: str, name: str, sc) -> bool:
        """检查文档是否已被加载。"""
        if path in sc.preloaded:
            return True
        if path in sc.wiki_retrieved:
            return True
        # 也检查 name 作为 key（兼容旧的非规范化 key）
        if name in sc.wiki_retrieved:
            return True
        return False

    @staticmethod
    def _prioritize(entities: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """按类别优先级排序。"""
        def _sort_key(entity: tuple[str, str]) -> int:
            path = entity[0]
            category = path.split("/")[0] if "/" in path else ""
            return CATEGORY_PRIORITY.get(category, 8)

        return sorted(entities, key=_sort_key)
