"""
共享辅助函数 — 供各 blueprint 使用。
"""

import json
from flask import jsonify, Response, stream_with_context


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
