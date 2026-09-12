"""OpenAI-compatible adapter."""

import logging

from .base import ProviderAdapter

logger = logging.getLogger(__name__)


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
        reasoning_effort: str = "medium",
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
        if enable_thinking and reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        return payload

    def build_connectivity_check(self) -> tuple[str, dict | None]:
        # Prefer /models endpoint (no token cost)
        return ("GET /models", None)
