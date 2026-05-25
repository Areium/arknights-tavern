"""Anthropic (Claude) adapter — not yet implemented."""

import logging

from .base import ProviderAdapter

logger = logging.getLogger(__name__)


class AnthropicAdapter(ProviderAdapter):
    """Anthropic Messages API adapter. **Not yet implemented.**

    The Anthropic API uses:
        - POST https://api.anthropic.com/v1/messages
        - ``x-api-key`` header (not Bearer)
        - ``anthropic-version`` header
        - Different message format (system as top-level, no multi-turn tool messages)
        - Different streaming format (SSE with ``text`` / ``content_block_delta`` events)
    """

    def __init__(self, api_key: str = "", base_url: str = "", model: str = ""):
        super().__init__(api_key, base_url or "https://api.anthropic.com/v1",
                         model or "claude-sonnet-4-6")
        self._api_version = "2023-06-01"

    @property
    def chat_endpoint(self) -> str:
        return "/messages"

    def auth_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": self._api_version,
        }

    def build_payload(self, **kwargs) -> dict:
        raise NotImplementedError("Anthropic adapter is not yet implemented")

    def parse_response(self, response_json: dict) -> dict:
        raise NotImplementedError("Anthropic adapter is not yet implemented")

    def parse_stream_chunk(self, chunk_json: dict) -> dict:
        raise NotImplementedError("Anthropic adapter is not yet implemented")

    def build_connectivity_check(self) -> tuple[str, dict | None]:
        raise NotImplementedError("Anthropic adapter is not yet implemented")
