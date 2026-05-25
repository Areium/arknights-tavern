import httpx
import json
import logging
import os

logger = logging.getLogger(__name__)

class ModelConfig:
    """模型配置"""

    base_url: str = "http://localhost:11434"
    model: str = "mbenhamd/qwen2.5-7b-instruct-cline-128k-q8_0:latest"
    max_tokens: int = 4096
    temperature: float = 0.1
    timeout: int = 30


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
    def __init__(self, config: ModelConfig = ModelConfig()):
        """
        初始化本地大语言模型接口。
        """
        self.config = config
        self.client = httpx.Client(base_url=config.base_url, timeout=config.timeout)

    def chat(self, messages: list, stream: bool = False, on_token=None,
             tools: list[dict] | None = None) -> dict:
        """
        使用本地模型进行聊天，支持多轮对话。

        Args:
            messages: 对话消息列表。
            stream: 是否使用流式响应（tools 存在时强制关闭）。
            on_token: 流式模式下每收到一个 token 时回调。
            tools: 可选的工具定义列表 (Ollama 格式)。

        Returns:
            dict: {"type": "text", "content": str, "usage": {...} | None}
              或  {"type": "tool_call", "tool_calls": [...], "content": str, "usage": {...} | None}
        """
        try:
            effective_stream = stream and tools is None
            payload = {
                "model": self.config.model,
                "messages": messages,
                "stream": effective_stream,
                "options": {
                    "num_predict": self.config.max_tokens,
                    "temperature": self.config.temperature,
                },
            }
            if tools:
                payload["tools"] = tools

            response = self.client.post("/api/chat", json=payload)
            response.raise_for_status()

            if effective_stream:
                full_response = ""
                usage = None
                for line in response.iter_lines():
                    if line:
                        json_part = json.loads(line)
                        content_part = json_part.get("message", {}).get("content", "")
                        if content_part:
                            full_response += content_part
                            if on_token:
                                on_token(content_part)
                        if json_part.get("done"):
                            prompt_tokens = json_part.get("prompt_eval_count")
                            completion_tokens = json_part.get("eval_count")
                            if prompt_tokens is not None and completion_tokens is not None:
                                usage = {
                                    "prompt_tokens": prompt_tokens,
                                    "completion_tokens": completion_tokens,
                                    "total_tokens": prompt_tokens + completion_tokens,
                                }
                return {"type": "text", "content": full_response, "usage": usage}
            else:
                result = response.json()
                msg = result.get("message", {})
                content = msg.get("content", "")
                prompt_tokens = result.get("prompt_eval_count")
                completion_tokens = result.get("eval_count")
                usage = None
                if prompt_tokens is not None and completion_tokens is not None:
                    usage = {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    }
                tool_calls = _parse_tool_calls_ollama(msg)
                if tool_calls:
                    return {"type": "tool_call", "tool_calls": tool_calls,
                            "content": content, "usage": usage}
                return {"type": "text", "content": content, "usage": usage}

        except httpx.RequestError as e:
            logger.error("请求本地大模型时出错: %s", e)
            return {"type": "text", "content": f"错误: 无法连接到模型服务于 {self.config.base_url}。", "usage": None}
        except Exception as e:
            logger.error("发生未知错误: %s", e)
            return {"type": "text", "content": "错误: 处理请求时发生未知错误。", "usage": None}


class ApiModelConfig:
    """API模型配置"""

    api_key: str = os.getenv("API_KEY")
    base_url: str = os.getenv("BASE_URL")  
    model: str = "deepseek-v4-flash"
    max_tokens: int = 4096
    temperature: float = 0.5
    timeout: int = 30


class ApiLLM:
    def __init__(self, config: ApiModelConfig = ApiModelConfig()):
        """
        初始化API大语言模型接口。
        """
        self.config = config
        self.client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout,
            headers={"Authorization": f"Bearer {self.config.api_key}"},
        )

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
             tools: list[dict] | None = None) -> dict:
        """
        使用API模型进行聊天。

        Args:
            messages: 对话消息列表。
            stream: 是否使用流式响应（tools 存在时强制关闭）。
            on_token: 流式模式下每收到一个 token 时回调。
            tools: 可选的工具定义列表 (OpenAI 格式)。

        Returns:
            dict: {"type": "text", "content": str, "usage": {...} | None}
              或  {"type": "tool_call", "tool_calls": [...], "content": str, "usage": {...} | None}
        """
        try:
            effective_stream = stream and tools is None
            payload: dict = {
                "model": self.config.model,
                "messages": messages,
                "stream": effective_stream,
            }
            if effective_stream:
                payload["stream_options"] = {"include_usage": True}
            if tools:
                payload["tools"] = tools

            response = self.client.post("/chat/completions", json=payload)
            response.raise_for_status()

            if effective_stream:
                full_response = ""
                usage = None
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        line = line[6:]
                    if line.strip() == "[DONE]":
                        break
                    if line:
                        try:
                            json_part = json.loads(line)
                            content_part = (
                                json_part.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if content_part:
                                full_response += content_part
                                if on_token:
                                    on_token(content_part)
                            chunk_usage = json_part.get("usage")
                            if chunk_usage:
                                usage = {
                                    "prompt_tokens": chunk_usage.get("prompt_tokens"),
                                    "completion_tokens": chunk_usage.get("completion_tokens"),
                                    "total_tokens": chunk_usage.get("total_tokens"),
                                }
                        except json.JSONDecodeError:
                            logger.warning("无法解码JSON行: %s", line)
                            continue
                return {"type": "text", "content": full_response, "usage": usage}
            else:
                result = response.json()
                msg = result.get("choices", [{}])[0].get("message", {})
                content = msg.get("content", "")
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
                            "content": content, "usage": usage}
                return {"type": "text", "content": content, "usage": usage}

        except httpx.RequestError as e:
            logger.error("请求API模型时出错: %s", e)
            return {"type": "text", "content": f"错误: 无法连接到模型服务于 {self.config.base_url}。", "usage": None}
        except Exception as e:
            logger.error("发生未知错误: %s", e)
            return {"type": "text", "content": "错误: 处理请求时发生未知错误。", "usage": None}


def chat_text(llm, messages: list, stream: bool = False, on_token=None) -> str:
    """向后兼容辅助：调用 llm.chat() 并提取纯文本内容。"""
    result = llm.chat(messages, stream=stream, on_token=on_token)
    return result.get("content", "") if isinstance(result, dict) else str(result)


