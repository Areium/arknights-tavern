import httpx
import json
from dotenv import load_dotenv
import os

load_dotenv()  # 加载 .env 文件

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
            print(f"请求本地大模型时出错: {e}")
            return f"错误: 无法连接到模型服务于 {self.config.base_url}。"
        except Exception as e:
            print(f"发生未知错误: {e}")
            return f"错误: 处理请求时发生未知错误。"


class ApiModelConfig:
    """API模型配置"""

    api_key: str = os.getenv("API_KEY")
    base_url: str = os.getenv("API_URL")  
    model: str = "Gemini-1.5-Flash"
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

    def chat(self, messages: list, stream: bool = False) -> str:
        """
        使用API模型进行聊天。

        Args:
            messages (list): 对话消息列表，格式为 [{"role": "user", "content": "..."}]。
            stream (bool): 是否使用流式响应。

        Returns:
            str: 模型生成的文本。
        """
        try:
            payload = {
                "model": self.config.model,
                "messages": messages,
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
                            full_response += content_part
                        except json.JSONDecodeError:
                            print(f"无法解码JSON行: {line}")
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
            print(f"请求API模型时出错: {e}")
            return f"错误: 无法连接到模型服务于 {self.config.base_url}。"
        except Exception as e:
            print(f"发生未知错误: {e}")
            return f"错误: 处理请求时发生未知错误。"





