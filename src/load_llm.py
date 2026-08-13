import httpx
import json
import hashlib
import logging
import os
import time

from world_book import estimate_tokens

logger = logging.getLogger(__name__)


# ── 结构化 LLM 错误（对齐 DSH：错误是事件/异常，绝不伪装成模型可读内容）──

class LLMError(Exception):
    """结构化 LLM 调用错误的基类。

    code: connect | timeout | http | unknown
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class LLMConnectError(LLMError):
    def __init__(self, message: str):
        super().__init__("connect", message)


class LLMTimeoutError(LLMError):
    def __init__(self, message: str):
        super().__init__("timeout", message)


class LLMHTTPError(LLMError):
    def __init__(self, status_code: int, body: str = ""):
        super().__init__("http", f"HTTP {status_code}")
        self.status_code = status_code
        self.body = body


def _request_fingerprint(messages: list) -> tuple[str, int]:
    """计算请求内容的 sha1 指纹与粗 token 估算。

    指纹是前缀缓存漂移的测量标尺：同一会话内指纹稳定 = 前缀缓存有效；
    指纹无故变化 = 找到了漂移源。
    """
    try:
        text = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = repr(messages)
    try:
        est = estimate_tokens(text)
    except Exception:
        est = len(text) // 4
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12], est


def _post_with_retry(client: httpx.Client, path: str, payload: dict,
                     max_retries: int = 2) -> httpx.Response:
    """POST 并在可重试失败（连接错误/429/5xx）上指数退避重试。

    读超时不重试（模型可能只是慢，重试会双倍计费）。
    """
    last_connect_error: LLMConnectError | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.post(path, json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            last_connect_error = LLMConnectError(str(e))
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise last_connect_error from e
        if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
            logger.warning("LLM %s 返回 %s，%.0fs 后重试 (%d/%d)",
                           path, response.status_code, 2 ** attempt, attempt + 1, max_retries)
            time.sleep(2 ** attempt)
            continue
        return response
    raise last_connect_error or LLMError("unknown", "request failed after retries")


class ModelConfig:
    """模型配置"""

    base_url: str = "http://localhost:11434"
    model: str = "mbenhamd/qwen2.5-7b-instruct-cline-128k-q8_0:latest"
    max_tokens: int = 4096
    temperature: float = 0.1
    timeout: int = 60


def _parse_tool_calls_ollama(message: dict) -> list[dict] | None:
    """从 Ollama 响应中提取 tool_calls（标准化格式）。"""
    raw = message.get("tool_calls")
    if not raw:
        return None
    result = []
    for tc in raw:
        func = tc.get("function", {})
        name = func.get("name", "")
        arguments = func.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        result.append({"name": name, "arguments": arguments})
    return result or None


def _parse_tool_calls_openai(message: dict) -> list[dict] | None:
    """从 OpenAI 兼容响应中提取 tool_calls（标准化格式）。"""
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


class LocalLLM:
    def __init__(self, config: ModelConfig = ModelConfig(), on_failure=None):
        """
        初始化本地大语言模型接口。

        Args:
            config: 模型配置。
            on_failure: 可选回调 `fn(code: str)`，真实调用失败（结构化错误）时触发，
                用于后端管理器标记端点失败并降级（DSH 式：真实失败驱动路由）。
        """
        self.config = config
        self._on_failure = on_failure
        self.client = httpx.Client(base_url=config.base_url, timeout=config.timeout)

    def _notify_failure(self, code: str):
        try:
            if self._on_failure:
                self._on_failure(code)
        except Exception:
            logger.exception("on_failure 回调异常（忽略）")

    def chat(self, messages: list, stream: bool = False, on_token=None,
             on_reasoning=None, tools: list[dict] | None = None,
             max_tokens: int | None = None) -> dict:
        """
        使用本地模型进行聊天，支持多轮对话。

        Args:
            messages: 对话消息列表。
            stream: 是否使用流式响应（tools 存在时强制关闭）。
            on_token: 流式模式下每收到一个 content token 时回调。
            on_reasoning: 流式模式下每收到一个 thinking token 时回调 (Ollama)。
            tools: 可选的工具定义列表 (Ollama 格式)。
            max_tokens: 覆盖默认的 max_tokens 限制。

        Returns:
            dict: {"type": "text", "content": str, "reasoning": str,
                   "usage": {...} | None, "finish_reason": str | None}
              或  {"type": "tool_call", "tool_calls": [...], "content": str, ...}
        """
        try:
            effective_stream = stream and tools is None
            num_predict = max_tokens if max_tokens is not None else self.config.max_tokens
            payload = {
                "model": self.config.model,
                "messages": messages,
                "stream": effective_stream,
                "options": {
                    "num_predict": num_predict,
                    "temperature": self.config.temperature,
                },
            }
            if tools:
                payload["tools"] = tools

            fingerprint, est_tokens = _request_fingerprint(messages)
            logger.info("[LLM] request fingerprint=%s est_tokens=%d messages=%d model=%s",
                        fingerprint, est_tokens, len(messages), self.config.model)

            response = _post_with_retry(self.client, "/api/chat", payload)
            response.raise_for_status()

            if effective_stream:
                full_response = ""
                full_reasoning = ""
                usage = None
                finish_reason = None
                for line in response.iter_lines():
                    if line:
                        json_part = json.loads(line)
                        content_part = json_part.get("message", {}).get("content", "")
                        if content_part:
                            full_response += content_part
                            if on_token:
                                on_token(content_part)
                        # Ollama thinking/reasoning (some models use "thinking" field)
                        thinking_part = json_part.get("message", {}).get("thinking", "")
                        if thinking_part:
                            full_reasoning += thinking_part
                            if on_reasoning:
                                on_reasoning(thinking_part)
                        if json_part.get("done"):
                            prompt_tokens = json_part.get("prompt_eval_count")
                            completion_tokens = json_part.get("eval_count")
                            if prompt_tokens is not None and completion_tokens is not None:
                                usage = {
                                    "prompt_tokens": prompt_tokens,
                                    "completion_tokens": completion_tokens,
                                    "total_tokens": prompt_tokens + completion_tokens,
                                }
                            finish_reason = json_part.get("done_reason", "stop")
                return {"type": "text", "content": full_response,
                        "reasoning": full_reasoning, "usage": usage,
                        "finish_reason": finish_reason}
            else:
                result = response.json()
                msg = result.get("message", {})
                content = msg.get("content", "") or ""
                reasoning = msg.get("thinking", "") or ""
                prompt_tokens = result.get("prompt_eval_count")
                completion_tokens = result.get("eval_count")
                usage = None
                if prompt_tokens is not None and completion_tokens is not None:
                    usage = {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    }
                finish_reason = result.get("done_reason", "stop")
                tool_calls = _parse_tool_calls_ollama(msg)
                if tool_calls:
                    return {"type": "tool_call", "tool_calls": tool_calls,
                            "content": content, "reasoning": reasoning,
                            "usage": usage, "finish_reason": finish_reason}
                return {"type": "text", "content": content,
                        "reasoning": reasoning, "usage": usage,
                        "finish_reason": finish_reason}

        except httpx.ReadTimeout as e:
            logger.error("Ollama 请求超时 (读取): %s", e)
            self._notify_failure("timeout")
            raise LLMTimeoutError(f"Ollama 响应超时（{self.config.timeout}s）") from e
        except httpx.HTTPStatusError as e:
            logger.error("Ollama HTTP 错误: %s", e)
            self._notify_failure("http")
            raise LLMHTTPError(e.response.status_code, e.response.text[:200]) from e
        except LLMError as e:
            # 来自重试助手（连接失败耗尽）等结构化错误：补一次失败通知
            self._notify_failure(e.code)
            raise
        except httpx.RequestError as e:
            logger.error("请求本地大模型时出错: %s", e)
            self._notify_failure("connect")
            raise LLMConnectError(str(e)) from e
        except Exception as e:
            logger.error("发生未知错误: %s", e)
            self._notify_failure("unknown")
            raise LLMError("unknown", f"处理请求时发生未知错误 ({type(e).__name__})") from e


class ApiModelConfig:
    """API模型配置"""

    api_key: str = os.getenv("API_KEY")
    base_url: str = os.getenv("BASE_URL")
    model: str = "deepseek-v4-flash"
    max_tokens: int = 4096
    temperature: float = 0.5
    timeout: int = 120


class ApiLLM:
    def __init__(self, config: ApiModelConfig = ApiModelConfig(), adapter=None,
                 enable_thinking: bool = False, reasoning_effort: str = "medium",
                 on_failure=None):
        """
        初始化API大语言模型接口。

        Args:
            config: API 配置。
            adapter: 可选的 ProviderAdapter，用于非 OpenAI 兼容平台。
            enable_thinking: 启用思考模式（DeepSeek reasoning_effort）。
            reasoning_effort: 推理强度 (low / medium / high)。
            on_failure: 可选回调 `fn(code: str)`，真实调用失败时触发（端点降级标记）。
        """
        self.config = config
        self.adapter = adapter
        self.enable_thinking = enable_thinking
        self.reasoning_effort = reasoning_effort
        self._on_failure = on_failure
        # If adapter provides auth headers, prefer them
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        if adapter:
            adapter_headers = adapter.auth_headers()
            if adapter_headers:
                headers = adapter_headers
        self.client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout,
            headers=headers,
        )

    def _notify_failure(self, code: str):
        try:
            if self._on_failure:
                self._on_failure(code)
        except Exception:
            logger.exception("on_failure 回调异常（忽略）")

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """
        调用 embedding API 获取文本向量。

        Args:
            texts (list[str]): 需要编码的文本列表。

        Returns:
            list[list[float]] | None: 向量列表，不支持时返回 None。
        """
        try:
            payload = {
                "model": "text-embedding-3-small",
                "input": texts,
            }
            response = self.client.post("/embeddings", json=payload)
            response.raise_for_status()
            result = response.json()
            data = sorted(result["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in data]
        except Exception:
            if not getattr(self, "_embed_warned", False):
                logger.warning("Embedding API 不可用 (将回退到滑动窗口模式)")
                self._embed_warned = True
            return None

    def chat(self, messages: list, stream: bool = False, on_token=None,
             on_reasoning=None, tools: list[dict] | None = None,
             max_tokens: int | None = None) -> dict:
        """
        使用API模型进行聊天。

        Args:
            messages: 对话消息列表。
            stream: 是否使用流式响应（tools 存在时强制关闭）。
            on_token: 流式模式下每收到一个 content token 时回调。
            on_reasoning: 流式模式下每收到一个 reasoning token 时回调。
            tools: 可选的工具定义列表 (OpenAI 格式)。
            max_tokens: 覆盖默认的 max_tokens 限制（发送至 API）。

        Returns:
            dict: {"type": "text", "content": str, "reasoning": str,
                   "usage": {...} | None, "finish_reason": str | None}
              或  {"type": "tool_call", "tool_calls": [...], "content": str, ...}
        """
        try:
            effective_stream = stream and tools is None
            mt = max_tokens if max_tokens is not None else self.config.max_tokens

            def _build_payload(include_stream_opts: bool) -> dict:
                if self.adapter:
                    return self.adapter.build_payload(
                        messages=messages,
                        stream=effective_stream,
                        max_tokens=mt,
                        temperature=self.config.temperature,
                        tools=tools,
                        include_stream_options=include_stream_opts,
                        enable_thinking=self.enable_thinking,
                        reasoning_effort=self.reasoning_effort,
                    )
                # Fallback: inline payload when no adapter
                payload: dict = {
                    "model": self.config.model,
                    "messages": messages,
                    "stream": effective_stream,
                    "temperature": self.config.temperature,
                }
                payload["max_tokens"] = mt
                if effective_stream and include_stream_opts:
                    payload["stream_options"] = {"include_usage": True}
                if tools:
                    payload["tools"] = tools
                return payload

            payload = _build_payload(True)
            fingerprint, est_tokens = _request_fingerprint(messages)
            logger.info("[LLM] request fingerprint=%s est_tokens=%d messages=%d model=%s",
                        fingerprint, est_tokens, len(messages), self.config.model)

            response = _post_with_retry(self.client, "/chat/completions", payload)

            # Graceful degradation: retry without stream_options on 400/422
            if response.status_code in (400, 422) and effective_stream:
                logger.info("stream_options 不被支持，回退为无 stream_options")
                payload = _build_payload(False)
                response = self.client.post("/chat/completions", json=payload)

            response.raise_for_status()

            if effective_stream:
                full_response = ""
                full_reasoning = ""
                usage = None
                finish_reason = None
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        line = line[6:]
                    if line.strip() == "[DONE]":
                        break
                    if line:
                        try:
                            json_part = json.loads(line)
                            delta = json_part.get("choices", [{}])[0].get("delta", {})
                            content_part = delta.get("content", "")
                            if content_part:
                                full_response += content_part
                                if on_token:
                                    on_token(content_part)
                            reasoning_part = delta.get("reasoning_content", "")
                            if reasoning_part:
                                full_reasoning += reasoning_part
                                if on_reasoning:
                                    on_reasoning(reasoning_part)
                            chunk_usage = json_part.get("usage")
                            if chunk_usage:
                                usage = {
                                    "prompt_tokens": chunk_usage.get("prompt_tokens"),
                                    "completion_tokens": chunk_usage.get("completion_tokens"),
                                    "total_tokens": chunk_usage.get("total_tokens"),
                                }
                            chunk_finish = json_part.get("choices", [{}])[0].get("finish_reason")
                            if chunk_finish:
                                finish_reason = chunk_finish
                        except json.JSONDecodeError:
                            logger.warning("无法解码JSON行: %s", line)
                            continue
                return {"type": "text", "content": full_response,
                        "reasoning": full_reasoning, "usage": usage,
                        "finish_reason": finish_reason}
            else:
                result = response.json()
                msg = result.get("choices", [{}])[0].get("message", {})
                content = msg.get("content", "") or ""
                reasoning = msg.get("reasoning_content", "") or ""
                finish_reason = result.get("choices", [{}])[0].get("finish_reason")
                api_usage = result.get("usage")
                usage = None
                if api_usage:
                    usage = {
                        "prompt_tokens": api_usage.get("prompt_tokens"),
                        "completion_tokens": api_usage.get("completion_tokens"),
                        "total_tokens": api_usage.get("total_tokens"),
                    }
                tool_calls = _parse_tool_calls_openai(msg)
                if tool_calls:
                    return {"type": "tool_call", "tool_calls": tool_calls,
                            "content": content, "reasoning": reasoning,
                            "usage": usage, "finish_reason": finish_reason}
                return {"type": "text", "content": content,
                        "reasoning": reasoning, "usage": usage,
                        "finish_reason": finish_reason}

        except httpx.ReadTimeout as e:
            logger.error("API 请求超时 (读取): %s", e)
            self._notify_failure("timeout")
            raise LLMTimeoutError(f"API 响应超时（{self.config.timeout}s）。思考模型可能需要更长时间，请调大超时。") from e
        except httpx.HTTPStatusError as e:
            logger.error("API HTTP 错误: %s", e)
            self._notify_failure("http")
            raise LLMHTTPError(e.response.status_code, e.response.text[:200]) from e
        except LLMError as e:
            # 来自重试助手等结构化错误：补一次失败通知
            self._notify_failure(e.code)
            raise
        except httpx.RequestError as e:
            logger.error("请求API模型时出错: %s", e)
            self._notify_failure("connect")
            raise LLMConnectError(f"请求失败 ({type(e).__name__}: {e})") from e
        except Exception as e:
            logger.error("发生未知错误: %s", e)
            self._notify_failure("unknown")
            raise LLMError("unknown", f"处理请求时发生未知错误 ({type(e).__name__})") from e


