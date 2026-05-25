"""DeepSeek adapter — extends OpenAI with reasoning/thinking support.

DeepSeek V4 Pro returns ``reasoning_content`` in streaming and non-streaming
responses.  The content field may be ``null`` while the model is reasoning.

The ``enable_thinking`` flag injects DeepSeek-specific parameters:
    - For ``deepseek-reasoner`` / ``deepseek-chat``: ``reasoning_effort``
"""

import logging

from .openai import OpenAIAdapter

logger = logging.getLogger(__name__)


class DeepSeekAdapter(OpenAIAdapter):
    """DeepSeek API adapter — OpenAI-compatible with reasoning_content.

    Handles the case where thinking models return ``content: null`` while
    reasoning — the base OpenAI adapter already extracts ``reasoning_content``,
    so this adapter focuses on payload-level thinking controls.
    """

    DEFAULT_REASONING_EFFORT = "medium"

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
        payload = super().build_payload(
            messages=messages,
            stream=stream,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            include_stream_options=include_stream_options,
            enable_thinking=enable_thinking,
        )
        if enable_thinking:
            payload["reasoning_effort"] = self.DEFAULT_REASONING_EFFORT
            logger.info("DeepSeek thinking mode enabled (reasoning_effort=%s)",
                        self.DEFAULT_REASONING_EFFORT)
        return payload
