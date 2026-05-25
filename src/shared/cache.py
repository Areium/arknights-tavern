"""
缓存失效 — 统一处理文档变更后的缓存刷新。
"""

import logging

logger = logging.getLogger(__name__)


def invalidate_all_caches(idxmgr, wiki_manager):
    """文档变更后统一刷新索引缓存和 wiki 目录。"""
    try:
        idxmgr.invalidate_cache()
    except Exception as e:
        logger.warning("索引缓存失效失败: %s", e)
    try:
        wiki_manager.refresh()
    except Exception as e:
        logger.warning("WikiManager 刷新失败: %s", e)
