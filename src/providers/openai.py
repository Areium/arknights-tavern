"""OpenAI-compatible adapter."""

import json
import logging
from typing import Any

from .base import ProviderAdapter

logger = logging.getLogger(__name__)


def _parse_tool_calls(message: dict) -> list[dict] | None:
    raw = message.get("tool_calls")
    if not raw:
        return None
    result = []
    for tc in raw:
        func = tc.get("function", {})
        name = func.get("name", "")
        args_str = func.get("arguments", "{}")
        try:
            arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            arguments = {}
        result.append({"name": name, "arguments": arguments})
    return result or None


class OpenAIAdapter(ProviderAdapter):
    """Standard OpenAI-compatible API adapter.

    Works with: OpenAI, vLLM, Ollama (openai-compat mode), and most
    OpenAI-compatible proxies.
    """

    @property
    def chat_endpoint(self) -> str:
        return "/chat/completions"

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def build_payload(
        self,
        messages: list[dict],
        stream: bool = False,
        max_tokens: int = 4096,
        temperature: float = 0.5,
        tools: list[dict] | None = None,
        include_stream_options: bool = True,
        enable_thinking: bool = False,
    ) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
        }
        payload["max_tokens"] = max_tokens
        if stream and include_stream_options:
            payload["stream_options"] = {"include_usage": True}
        if tools:
            payload["tools"] = tools
        return payload

    def parse_response(self, response_json: dict) -> dict:
        msg = self._safe_get(response_json, "choices", 0, "message", default={})
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        finish_reason = self._safe_get(response_json, "choices", 0, "finish_reason")

        api_usage = response_json.get("usage")
        usage = None
        if api_usage:
            usage = {
                "prompt_tokens": api_usage.get("prompt_tokens"),
                "completion_tokens": api_usage.get("completion_tokens"),
                "total_tokens": api_usage.get("total_tokens"),
            }

        tool_calls = _parse_tool_calls(msg)
        if tool_calls:
            return {
                "type": "tool_call",
                "tool_calls": tool_calls,
                "content": content,
                "reasoning": reasoning,
                "usage": usage,
                "finish_reason": finish_reason,
            }
        return {
            "type": "text",
            "content": content,
            "reasoning": reasoning,
            "usage": usage,
            "finish_reason": finish_reason,
        }

    def parse_stream_chunk(self, chunk_json: dict) -> dict:
        delta = self._safe_get(chunk_json, "choices", 0, "delta", default={})
        content = delta.get("content") or None
        reasoning = delta.get("reasoning_content") or None
        finish_reason = self._safe_get(chunk_json, "choices", 0, "finish_reason")

        chunk_usage = chunk_json.get("usage")
        usage = None
        if chunk_usage:
            usage = {
                "prompt_tokens": chunk_usage.get("prompt_tokens"),
                "completion_tokens": chunk_usage.get("completion_tokens"),
                "total_tokens": chunk_usage.get("total_tokens"),
            }
        return {
            "content": content,
            "reasoning": reasoning,
            "usage": usage,
            "finish_reason": finish_reason,
        }

    def build_connectivity_check(self) -> tuple[str, dict | None]:
        # Prefer /models endpoint (no token cost)
        return ("GET /models", None)
