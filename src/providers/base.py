"""Base ProviderAdapter — abstract interface for LLM API backends."""

from abc import ABC, abstractmethod
from typing import Any


class ProviderAdapter(ABC):
    """Encapsulates all provider-specific API differences.

    Each implementation handles:
        - endpoint URL construction
        - authentication headers
        - request payload building
        - response parsing (streaming and non-streaming)
        - connectivity check
    """

    def __init__(self, api_key: str = "", base_url: str = "", model: str = ""):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    # ── Endpoint ──

    @property
    @abstractmethod
    def chat_endpoint(self) -> str:
        """Full URL for chat completions (appended to base_url or absolute)."""
        ...

    # ── Auth ──

    @abstractmethod
    def auth_headers(self) -> dict[str, str]:
        """Headers required for authentication."""
        ...

    # ── Payload ──

    @abstractmethod
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
        """Build the JSON request payload for a chat completion."""
        ...

    # ── Response parsing ──

    @abstractmethod
    def parse_response(self, response_json: dict) -> dict:
        """Parse a non-streaming API response into the standard result dict.

        Returns:
            {"type": "text", "content": "...", "reasoning": "...",
             "usage": {...} | None, "finish_reason": str | None}
            or {"type": "tool_call", "tool_calls": [...], ...}
        """
        ...

    @abstractmethod
    def parse_stream_chunk(self, chunk_json: dict) -> dict:
        """Parse a single SSE chunk into delta tokens.

        Returns:
            {"content": str | None, "reasoning": str | None,
             "usage": dict | None, "finish_reason": str | None}
        """
        ...

    # ── Connectivity check ──

    @abstractmethod
    def build_connectivity_check(self) -> tuple[str, dict | None]:
        """Return (method_and_path, payload_or_none) for a lightweight
        connectivity test. E.g. ("GET /models", None) or
        ("POST /chat/completions", {"model": ...}).

        Used by LLMBackendManager._check_cloud().
        """
        ...

    # ── Utility ──

    @staticmethod
    def _safe_get(data, *keys, default: Any = None) -> Any:
        """Deep dict.get() / list[idx] chain — returns default if any key is missing."""
        for k in keys:
            if isinstance(data, dict):
                data = data.get(k, None)
                if data is None:
                    return default
            elif isinstance(data, list) and isinstance(k, int) and 0 <= k < len(data):
                data = data[k]
            else:
                return default
        return data
