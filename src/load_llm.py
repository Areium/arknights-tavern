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


class LocalLLM:
    def __init__(self, config: ModelConfig = ModelConfig()):
        """
        初始化本地大语言模型接口。
        """
        self.config = config
        self.client = httpx.Client(base_url=config.base_url, timeout=config.timeout)

    def chat(self, messages: list, stream: bool = False) -> str:
        """
        使用本地模型进行聊天，支持多轮对话。

        Args:
            messages (list): 对话消息列表，格式为 [{"role": "user", "content": "..."}]。
            stream (bool): 是否使用流式响应。

        Returns:
            str: 模型生成的文本。
        """
        try:
            # 切换到 /api/chat 接口
            payload = {
                "model": self.config.model,
                "messages": messages,
                "stream": stream,
                "options": {
                    "num_predict": self.config.max_tokens,
                    "temperature": self.config.temperature,
                },
            }
            response = self.client.post("/api/chat", json=payload)
            response.raise_for_status()

            if stream:
                full_response = ""
                for line in response.iter_lines():
                    if line:
                        json_part = json.loads(line)
                        # 流式响应下，内容在 delta 中
                        content_part = json_part.get("message", {}).get("content", "")
                        full_response += content_part
                return full_response
            else:
                result = response.json()
                # 非流式响应下，内容在 message.content 中
                return result.get("message", {}).get("content", "")

        except httpx.RequestError as e:
            logger.error("请求本地大模型时出错: %s", e)
            return f"错误: 无法连接到模型服务于 {self.config.base_url}。"
        except Exception as e:
            logger.error("发生未知错误: %s", e)
            return f"错误: 处理请求时发生未知错误。"


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

    def chat(self, messages: list, stream: bool = False, on_token=None) -> str:
        """
        使用API模型进行聊天。

        Args:
            messages (list): 对话消息列表。
            stream (bool): 是否使用流式响应。
            on_token (callable | None): 流式模式下每收到一个 token 时回调。

        Returns:
            str: 模型生成的完整文本。
        """
        try:
            payload = {
                "model": self.config.model,
                "messages": messages,
                "stream": stream,
            }
            response = self.client.post("/chat/completions", json=payload)
            response.raise_for_status()

            if stream:
                full_response = ""
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
                        except json.JSONDecodeError:
                            logger.warning("无法解码JSON行: %s", line)
                            continue
                return full_response
            else:
                result = response.json()
                return (
                    result.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )

        except httpx.RequestError as e:
            logger.error("请求API模型时出错: %s", e)
            return f"错误: 无法连接到模型服务于 {self.config.base_url}。"
        except Exception as e:
            logger.error("发生未知错误: %s", e)
            return f"错误: 处理请求时发生未知错误。"





