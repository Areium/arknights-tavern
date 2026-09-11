"""
共享辅助函数 — 供各 blueprint 使用。
"""

import logging
from flask import jsonify, Response, stream_with_context

logger = logging.getLogger(__name__)


def json_error(message: str, status: int = 400):
    """返回 JSON 错误响应。"""
    return jsonify({"error": message}), status


def make_sse_response(generator_func):
    """创建 SSE (Server-Sent Events) 流式响应。

    统一处理 Content-Type、缓存控制头等样板代码。
    """
    return Response(
        stream_with_context(generator_func()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def inject_memory_context(session, env_context: str) -> str:
    """注入最近回忆上下文到环境描述中，帮助 LLM 保持剧情连贯。"""
    recent_memories = session.get_memories()[-3:]
    if not recent_memories:
        return env_context

    lines = ["\n【剧情回顾】"]
    for m in recent_memories:
        lines.append(f"- 第{m['round_start']}-{m['round_end']}轮：{m['summary']}")
    return env_context + "\n".join(lines)


def build_character_metas(session, doc_mgr):
    """从 session overlay 和磁盘构建角色元数据列表，供战斗初始化使用。

    对每个场景角色：加载角色文档 → 合并 session overlay 覆盖 →
    返回合并后的 metadata 列表。
    """
    character_metas = []
    character_names = session.scene_manager.get_scene_characters()

    for name in character_names:
        try:
            doc = doc_mgr.read_document("characters", name)
        except Exception:
            logger.warning("Character doc not found: %s", name)
            continue

        merged_meta, _merged_content = session.overlay.apply_character_overrides(
            name, doc["metadata"], doc.get("content", "")
        )
        character_metas.append(merged_meta)

        if not session.overlay.has_character_overrides(name):
            session.overlay.set_character_overrides(name, {})

    return character_metas
