"""
LLM 后端管理器：启动时检测可用后端、提供状态、自动降级。

设计：
- 启动时同时检测云端 API 和本地 Ollama
- 按优先级选择主后端，另一作为备用
- 后端提供 get_llm() 获取 LLM 实例，调用失败时自动降级
- 前端通过状态端点实时了解可用后端
- 配置持久化到 config/llm_config.json，启动时加载
"""

import json
import os
import time
import logging
import threading
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

from load_llm import ApiLLM, ApiModelConfig, LocalLLM, ModelConfig

logger = logging.getLogger(__name__)

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "llm_config.json"

# 默认配置
_DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "",
    "cloud_model": ApiModelConfig.model,
    "ollama_url": "http://localhost:11434",
    "ollama_model": ModelConfig.model,
    "theme": "dark",
    "auto_generate_choices": False,
    "choice_count": 3,
}


def _read_config_file() -> dict:
    """读取 JSON 配置文件。"""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 LLM 配置文件失败: %s", e)
        return {}


def _write_config_file(config: dict):
    """写入 JSON 配置文件。"""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


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
        self._load_config()
        self._detect()

    def _load_config(self):
        """从 JSON 配置文件加载配置并同步到运行时。

        如果 JSON 文件不存在但 .env 中有值，自动迁移。
        """
        stored = _read_config_file()

        # 首次启动：从 .env 迁移已有配置
        if not stored:
            load_dotenv()
            env_config = {
                "api_key": os.getenv("API_KEY", ""),
                "base_url": os.getenv("BASE_URL") or os.getenv("API_URL", ""),
                "cloud_model": ApiModelConfig.model,
                "ollama_url": self.OLLAMA_URL,
                "ollama_model": ModelConfig.model,
            }
            # 只保存非空值
            stored = {k: v for k, v in env_config.items() if v}
            if stored:
                _write_config_file(stored)
                logger.info("已从 .env 迁移配置到 %s", _CONFIG_PATH)

        merged = {**_DEFAULT_CONFIG, **stored}

        # 同步到 os.environ 和 ApiModelConfig 类属性（类属性在 import 时求值，需显式覆盖）
        if merged.get("api_key"):
            os.environ["API_KEY"] = merged["api_key"]
            ApiModelConfig.api_key = merged["api_key"]
        if merged.get("base_url"):
            os.environ["BASE_URL"] = merged["base_url"]
            ApiModelConfig.base_url = merged["base_url"]

        # 同步模型名称到类属性
        if merged.get("cloud_model"):
            ApiModelConfig.model = merged["cloud_model"]
        if merged.get("ollama_url"):
            self.OLLAMA_URL = merged["ollama_url"]
        if merged.get("ollama_model"):
            ModelConfig.model = merged["ollama_model"]

        logger.info("LLM 配置已加载: cloud_model=%s, ollama_url=%s",
                     ApiModelConfig.model, self.OLLAMA_URL)

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

    # ── 配置管理 ──

    def get_config(self) -> dict:
        """返回当前有效配置。"""
        stored = _read_config_file()
        merged = {**_DEFAULT_CONFIG, **stored}
        return {
            "api_key": merged.get("api_key", ""),
            "base_url": merged.get("base_url", ""),
            "cloud_model": merged.get("cloud_model", ""),
            "ollama_url": merged.get("ollama_url", ""),
            "ollama_model": merged.get("ollama_model", ""),
            "theme": merged.get("theme", "dark"),
            "auto_generate_choices": merged.get("auto_generate_choices", False),
            "choice_count": merged.get("choice_count", 3),
        }

    def update_config(self, data: dict) -> dict:
        """更新 LLM 配置，写入 JSON 文件并重新检测端点。

        可更新字段：api_key, base_url, cloud_model, ollama_url, ollama_model, theme
        """
        # 读取已有配置，合并更新
        stored = _read_config_file()
        merged = {**_DEFAULT_CONFIG, **stored}

        if "api_key" in data:
            merged["api_key"] = data["api_key"]
        if "base_url" in data:
            merged["base_url"] = data["base_url"]
        if "cloud_model" in data:
            merged["cloud_model"] = data["cloud_model"]
        if "ollama_url" in data:
            merged["ollama_url"] = data["ollama_url"]
        if "ollama_model" in data:
            merged["ollama_model"] = data["ollama_model"]
        if "theme" in data:
            merged["theme"] = data["theme"]
        if "auto_generate_choices" in data:
            merged["auto_generate_choices"] = bool(data["auto_generate_choices"])
        if "choice_count" in data:
            merged["choice_count"] = max(1, min(5, int(data["choice_count"])))

        # 持久化到 JSON 文件
        _write_config_file(merged)

        # 同步到运行时（仅 LLM 相关字段）
        if merged.get("api_key"):
            os.environ["API_KEY"] = merged["api_key"]
            ApiModelConfig.api_key = merged["api_key"]
        if merged.get("base_url"):
            os.environ["BASE_URL"] = merged["base_url"]
            ApiModelConfig.base_url = merged["base_url"]
        ApiModelConfig.model = merged["cloud_model"]
        self.OLLAMA_URL = merged["ollama_url"]
        ModelConfig.model = merged["ollama_model"]

        # LLM 相关字段变更时重新检测端点
        if any(k in data for k in ("api_key", "base_url", "cloud_model", "ollama_url", "ollama_model")):
            self._detect()

        return self.get_config()

    def test_connection(self, endpoint_type: str, params: dict) -> dict:
        """测试指定类型后端的连通性（不持久化，不修改当前配置）。

        Returns:
            {"ok": bool, "latency_ms": float, "model": str, "detail": str}
        """
        if endpoint_type == "cloud":
            return self._test_cloud(**params)
        elif endpoint_type == "ollama":
            return self._test_ollama(**params)
        else:
            return {"ok": False, "latency_ms": 0, "model": "", "detail": f"未知后端类型: {endpoint_type}"}

    @staticmethod
    def _test_cloud(api_key: str = "", base_url: str = "", model: str = "") -> dict:
        """测试云端 API 连通性。"""
        if not api_key:
            return {"ok": False, "latency_ms": 0, "model": "", "detail": "未提供 API Key"}
        if not base_url:
            return {"ok": False, "latency_ms": 0, "model": "", "detail": "未提供 API 地址"}

        try:
            client = httpx.Client(
                base_url=base_url,
                timeout=10,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            start = time.time()

            # 优先 /models 端点
            try:
                r = client.get("/models")
                if r.status_code == 200:
                    models = r.json().get("data", [])
                    detected = model
                    if models and not detected:
                        detected = models[0].get("id", models[0].get("root", ""))
                    latency = (time.time() - start) * 1000
                    return {"ok": True, "latency_ms": round(latency, 1), "model": detected or model, "detail": ""}
            except Exception:
                pass

            # 回退：最小 chat 请求
            test_model = model or "gpt-3.5-turbo"
            r = client.post("/chat/completions", json={
                "model": test_model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            })
            r.raise_for_status()
            latency = (time.time() - start) * 1000
            return {"ok": True, "latency_ms": round(latency, 1), "model": test_model, "detail": ""}

        except httpx.ConnectError:
            return {"ok": False, "latency_ms": 0, "model": "", "detail": "无法连接到 API 地址"}
        except Exception as e:
            detail = str(e)
            # HTTP 错误提取响应体
            if hasattr(e, 'response') and e.response is not None:
                try:
                    detail = e.response.text[:200]
                except Exception:
                    pass
            return {"ok": False, "latency_ms": 0, "model": "", "detail": detail}

    @staticmethod
    def _test_ollama(ollama_url: str = "", model: str = "") -> dict:
        """测试 Ollama 连通性。"""
        url = ollama_url or "http://localhost:11434"
        try:
            start = time.time()
            r = httpx.get(f"{url}/api/tags", timeout=5)
            latency = (time.time() - start) * 1000

            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                if models:
                    return {"ok": True, "latency_ms": round(latency, 1), "model": models[0], "detail": f"{len(models)} 个模型"}
                else:
                    return {"ok": True, "latency_ms": round(latency, 1), "model": "", "detail": "服务在线但无模型"}
            else:
                return {"ok": False, "latency_ms": round(latency, 1), "model": "", "detail": f"HTTP {r.status_code}"}

        except httpx.ConnectError:
            return {"ok": False, "latency_ms": 0, "model": "", "detail": "Ollama 未运行"}
        except Exception as e:
            return {"ok": False, "latency_ms": 0, "model": "", "detail": str(e)}
