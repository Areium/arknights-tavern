"""
LLM 后端管理器：启动时检测可用后端、提供状态、自动降级。

设计：
- 启动时同时检测云端 API 和本地 Ollama
- 按优先级选择主后端，另一作为备用
- 后端提供 get_llm() 获取 LLM 实例，调用失败时自动降级
- 前端通过状态端点实时了解可用后端
"""

import os
import time
import logging
import threading
from typing import Optional

import httpx
from dotenv import load_dotenv

from load_llm import ApiLLM, ApiModelConfig, LocalLLM, ModelConfig

logger = logging.getLogger(__name__)


class LLMEndpoint:
    """单个 LLM 后端的描述信息。"""

    def __init__(
        self,
        endpoint_id: str,
        name: str,
        backend_type: str,
        model: str,
        available: bool,
        latency_ms: float = 0.0,
        detail: str = "",
    ):
        self.id = endpoint_id
        self.name = name
        self.type = backend_type  # "cloud" | "local"
        self.model = model
        self.available = available
        self.latency_ms = latency_ms
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "model": self.model,
            "available": self.available,
            "latency_ms": round(self.latency_ms, 1),
            "detail": self.detail,
        }


class LLMBackendManager:
    """LLM 后端管理器：检测、选择、降级。"""

    OLLAMA_URL = "http://localhost:11434"

    def __init__(self):
        self._primary: Optional[LLMEndpoint] = None
        self._fallback: Optional[LLMEndpoint] = None
        self._all_endpoints: list[LLMEndpoint] = []
        self._lock = threading.Lock()
        self._last_fail_time: float = 0.0
        self._detect()

    # ── 检测 ──

    def _detect(self):
        """启动时检测所有可用后端。"""
        cloud = self._check_cloud()
        local = self._check_ollama()

        self._all_endpoints = [ep for ep in [cloud, local] if ep is not None]

        # 按优先级选择主后端：云端 > Ollama
        available = [ep for ep in self._all_endpoints if ep.available]
        if available:
            self._primary = available[0]
            self._fallback = available[1] if len(available) > 1 else None
        else:
            self._primary = None
            self._fallback = None

        logger.info(
            "LLM 后端检测完成: primary=%s, fallback=%s",
            self._primary.name if self._primary else "无",
            self._fallback.name if self._fallback else "无",
        )

    def _check_cloud(self) -> Optional[LLMEndpoint]:
        """检测云端 API 连通性。"""
        load_dotenv()
        api_key = os.getenv("API_KEY")
        api_url = os.getenv("BASE_URL")
        if not api_key:
            return LLMEndpoint("cloud", "云端 API", "cloud", "", False, detail="未配置 API_KEY")

        try:
            config = ApiModelConfig()
            # 轻量连通性检测：请求模型列表或最小 chat 请求
            client = httpx.Client(
                base_url=config.base_url,
                timeout=10,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            start = time.time()

            # 优先尝试 /models 端点（无需消耗 token）
            try:
                r = client.get("/models")
                if r.status_code == 200:
                    models = r.json().get("data", [])
                    model_name = config.model
                    if models:
                        model_name = models[0].get("id", models[0].get("root", config.model))
                    latency = (time.time() - start) * 1000
                    return LLMEndpoint(
                        "cloud", "云端 API", "cloud",
                        model_name, True, latency,
                    )
            except Exception:
                pass

            # 回退：最小 chat 请求 (max_tokens=1)
            r = client.post("/chat/completions", json={
                "model": config.model,
                "messages": [{"role": "user", "content": "."}],
                "max_tokens": 1,
            })
            r.raise_for_status()
            latency = (time.time() - start) * 1000
            return LLMEndpoint(
                "cloud", "云端 API", "cloud",
                config.model, True, latency,
            )

        except Exception as e:
            logger.warning("云端 API 不可用: %s", e)
            return LLMEndpoint(
                "cloud", "云端 API", "cloud", "", False,
                detail=f"连接失败: {e!s}",
            )

    def _check_ollama(self) -> Optional[LLMEndpoint]:
        """检测本地 Ollama 服务。"""
        try:
            start = time.time()
            response = httpx.get(f"{self.OLLAMA_URL}/api/tags", timeout=3)
            latency = (time.time() - start) * 1000

            if response.status_code == 200:
                models = [m["name"] for m in response.json().get("models", [])]
                if models:
                    logger.info("Ollama 检测成功: %d 个模型可用, 主模型=%s", len(models), models[0])
                else:
                    logger.warning("Ollama 在线但无可用模型")

                return LLMEndpoint(
                    "ollama", "Ollama 本地", "local",
                    models[0] if models else "无模型",
                    available=len(models) > 0,
                    latency_ms=latency,
                    detail=f"{len(models)} 个模型可用" if models else "无可用模型",
                )
            else:
                return LLMEndpoint(
                    "ollama", "Ollama 本地", "local", "", False,
                    latency, detail=f"HTTP {response.status_code}",
                )
        except httpx.ConnectError:
            logger.info("Ollama 未运行")
            return LLMEndpoint(
                "ollama", "Ollama 本地", "local", "", False,
                detail="Ollama 未运行",
            )
        except Exception as e:
            logger.warning("Ollama 检测异常: %s", e)
            return LLMEndpoint(
                "ollama", "Ollama 本地", "local", "", False,
                detail=str(e),
            )

    # ── 获取 LLM 实例（含自动降级）──

    def get_llm(self) -> tuple[ApiLLM | LocalLLM | None, str]:
        """获取当前可用的 LLM 实例。

        Returns:
            tuple[ApiLLM | LocalLLM | None, str]: (llm 实例, 使用中的后端 id)
            均不可用时返回 (None, "")。
        """
        # 如果上次失败在 30 秒内，跳过主后端直接试备用
        skip_primary = (time.time() - self._last_fail_time) < 30.0

        candidates = []
        if self._primary and not skip_primary:
            candidates.append((self._primary, "primary"))
        if self._fallback:
            candidates.append((self._fallback, "fallback"))

        for ep, role in candidates:
            try:
                llm = self._instantiate(ep)
                if llm:
                    # 轻量连通性检查
                    test = llm.chat([{"role": "user", "content": "."}])
                    if test and "错误" not in test:
                        return llm, ep.id
            except Exception:
                continue

        # 都失败：重试一次主后端（更新检测状态）
        if self._primary:
            try:
                llm = self._instantiate(self._primary)
                if llm:
                    return llm, self._primary.id
            except Exception:
                pass

        self._last_fail_time = time.time()
        return None, ""

    def get_llm_for_endpoint(self, endpoint_id: str) -> ApiLLM | LocalLLM | None:
        """为指定端点创建 LLM 实例（前端手动选择时用）。"""
        for ep in self._all_endpoints:
            if ep.id == endpoint_id and ep.available:
                return self._instantiate(ep)
        return None

    def _instantiate(self, ep: LLMEndpoint) -> ApiLLM | LocalLLM:
        """根据端点类型创建 LLM 实例。"""
        if ep.type == "cloud":
            return ApiLLM()
        elif ep.type == "local":
            config = ModelConfig()
            config.base_url = self.OLLAMA_URL
            config.model = ep.model
            return LocalLLM(config)
        return None

    # ── 状态查询 ──

    def get_status(self) -> dict:
        """返回前端状态栏所需信息。"""
        return {
            "primary": self._primary.to_dict() if self._primary else None,
            "fallback": self._fallback.to_dict() if self._fallback else None,
            "endpoints": [ep.to_dict() for ep in self._all_endpoints],
            "available": self._primary is not None and self._primary.available,
        }

    def is_available(self) -> bool:
        """是否有至少一个可用后端。"""
        return any(ep.available for ep in self._all_endpoints)
