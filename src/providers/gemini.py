"""Google Gemini adapter — not yet implemented."""

import logging

from .base import ProviderAdapter

logger = logging.getLogger(__name__)


class GeminiAdapter(ProviderAdapter):
    """Google Gemini API adapter. **Not yet implemented.**

    The Gemini API uses:
        - POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
        - API key as query parameter
        - Different message format (``contents`` / ``parts`` / ``role: "user"/"model"``)
        - Different streaming format (server-sent chunks with different structure)
    """

    def __init__(self, api_key: str = "", base_url: str = "", model: str = ""):
        super().__init__(
            api_key,
            base_url or "https://generativelanguage.googleapis.com/v1beta",
            model or "gemini-2.5-flash",
        )

    @property
    def chat_endpoint(self) -> str:
        return f"/models/{self.model}:generateContent"

    def auth_headers(self) -> dict[str, str]:
        # Gemini uses API key as query param, not header
        return {}

    def build_payload(self, **kwargs) -> dict:
        raise NotImplementedError("Gemini adapter is not yet implemented")

    def parse_response(self, response_json: dict) -> dict:
        raise NotImplementedError("Gemini adapter is not yet implemented")

    def parse_stream_chunk(self, chunk_json: dict) -> dict:
        raise NotImplementedError("Gemini adapter is not yet implemented")

    def build_connectivity_check(self) -> tuple[str, dict | None]:
        raise NotImplementedError("Gemini adapter is not yet implemented")
