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

from load_llm import ApiLLM, ApiModelConfig, LLMError, LocalLLM, ModelConfig
from providers import get_adapter

logger = logging.getLogger(__name__)

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "llm_config.json"
_EXAMPLE_PATH = _PROJECT_ROOT / "config" / "llm_config.example.json"

# 默认配置
_DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "",
    "cloud_model": ApiModelConfig.model,
    "ollama_url": "http://localhost:11434",
    "ollama_model": ModelConfig.model,
    "theme": "dark",
    # UI 皮肤：default（默认）/ prts（PRTS 全息终端）/ tavern（酒馆手札）。
    # 皮肤是自带完整色板的独立主题，激活时前端禁用明暗切换。
    "skin": "default",
    "provider": "auto",
    "enable_thinking": False,
    "reasoning_effort": "medium",
    # 叙述/角色对话的思考档位（按调用覆盖全局 enable_thinking）。
    # 默认 none：实测混合模型（deepseek-v4-flash）缺省思考 ~550 tok、medium 1.3k~4k tok，
    # 是叙述延迟主因；分类/提取/回忆生成固定走 none（见各调用点）。
    "narration_reasoning_effort": "none",
    "auto_generate_choices": False,
    "choice_count": 3,
    "memory_interval": 5,
    "edit_before_send": False,
    "dialogue_bubble_mode": False,
    "max_output_tokens": 16384,
    "word_limit": 500,
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
        self._endpoint_fail_time: dict[str, float] = {}
        self._verified_at: dict[str, float] = {}  # 端点最近一次健康检查通过时间
        self._instances: dict[str, ApiLLM | LocalLLM] = {}  # 端点 id → 复用的 LLM 实例
        self._instance_lock = threading.Lock()
        self._detect_gen = 0  # 检测代数：用于丢弃过期的异步探测结果
        self._detected = False
        self._provider: str = "auto"
        self._enable_thinking: bool = False
        self._reasoning_effort: str = "medium"
        self._ensure_config()
        self._load_config()

    # 健康检查 TTL：DSH 式「信任路由，真实失败驱动降级」——ping 只作为
    # 低频探活（每端点每 120s 至多一次），而非每次取实例都测一次。
    VERIFY_TTL = 120.0

    @staticmethod
    def _ensure_config():
        """若 config/llm_config.json 不存在，自动从 example 复制创建。"""
        if _CONFIG_PATH.exists():
            return
        if not _EXAMPLE_PATH.exists():
            logger.info("未找到 %s 和 %s，跳过自动创建", _CONFIG_PATH, _EXAMPLE_PATH)
            return
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(_EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info("已从 %s 自动创建 %s", _EXAMPLE_PATH.name, _CONFIG_PATH.name)

    def _load_config(self):
        """从 JSON 配置文件加载配置并同步到运行时。"""
        stored = _read_config_file()
        merged = {**_DEFAULT_CONFIG, **stored}

        # 同步到 os.environ 和 ApiModelConfig 类属性（类属性在 import 时求值，需显式覆盖）
        if "api_key" in merged:
            os.environ["API_KEY"] = merged["api_key"]
            ApiModelConfig.api_key = merged["api_key"]
        if "base_url" in merged:
            os.environ["BASE_URL"] = merged["base_url"]
            ApiModelConfig.base_url = merged["base_url"]

        # 同步模型名称到类属性
        if merged.get("cloud_model"):
            ApiModelConfig.model = merged["cloud_model"]
        if merged.get("ollama_url"):
            self.OLLAMA_URL = merged["ollama_url"]
        if merged.get("ollama_model"):
            ModelConfig.model = merged["ollama_model"]
        if merged.get("max_output_tokens"):
            max_tok = merged["max_output_tokens"]
            ApiModelConfig.max_tokens = max_tok
            ModelConfig.max_tokens = max_tok

        self._provider = merged.get("provider", "auto")
        self._enable_thinking = bool(merged.get("enable_thinking", False))
        self._reasoning_effort = merged.get("reasoning_effort", "medium")

        logger.info("LLM 配置已加载: cloud_model=%s, provider=%s, ollama_url=%s",
                     ApiModelConfig.model, self._provider, self.OLLAMA_URL)

    # ── 检测 ──

    def _ensure_detected(self):
        """延迟检测：仅在首次需要检测结果时执行。"""
        if not self._detected:
            self._detect()
            self._detected = True

    def _detect(self):
        """检测所有可用后端。

        云端可用时，Ollama 探测放到后台线程：本机未监听 11434 时，connect 到
        localhost 要 2~4s 才返回拒绝（IPv6/IPv4 各一次），而它只是备选信息，
        没必要拖着启动不放。云端不可用时 Ollama 可能是唯一后端，必须同步探测。
        """
        with self._lock:
            # 端点即将重建：丢弃已缓存实例，确保新的 base_url/api_key 生效
            with self._instance_lock:
                self._instances.clear()
            self._detect_gen += 1
            gen = self._detect_gen
            cloud = self._check_cloud()

            if cloud is not None and cloud.available:
                self._all_endpoints = [cloud]
                self._apply_endpoints()
                self._detected = True
                logger.info("LLM 后端检测完成: primary=%s (Ollama 后台探测中)",
                            self._primary.name if self._primary else "无")
                threading.Thread(target=self._probe_ollama_async, args=(gen,),
                                 daemon=True, name="ollama-detect").start()
                return

            local = self._check_ollama()
            self._all_endpoints = [ep for ep in [cloud, local] if ep is not None]
            self._apply_endpoints()
            self._detected = True
            logger.info(
                "LLM 后端检测完成: primary=%s, fallback=%s",
                self._primary.name if self._primary else "无",
                self._fallback.name if self._fallback else "无",
            )

    def _apply_endpoints(self):
        """按优先级（云端 > Ollama）从 _all_endpoints 选出主/备后端。"""
        available = [ep for ep in self._all_endpoints if ep.available]
        if available:
            self._primary = available[0]
            self._fallback = available[1] if len(available) > 1 else None
        else:
            self._primary = None
            self._fallback = None

    def _probe_ollama_async(self, gen: int):
        """后台探测 Ollama 并登记端点（gen 不匹配说明已重新检测，丢弃过期结果）。"""
        try:
            local = self._check_ollama()
        except Exception as e:  # noqa: BLE001
            logger.debug("Ollama 后台探测异常（忽略）: %s", e)
            return
        if local is None:
            return
        with self._lock:
            if gen != self._detect_gen:
                logger.debug("Ollama 后台探测结果已过期，丢弃")
                return
            self._all_endpoints = [ep for ep in self._all_endpoints if ep.id != "ollama"]
            self._all_endpoints.append(local)
            self._apply_endpoints()
            logger.info("LLM 后端检测完成(异步): primary=%s, fallback=%s",
                        self._primary.name if self._primary else "无",
                        self._fallback.name if self._fallback else "无")

    def _check_cloud(self) -> Optional[LLMEndpoint]:
        """检测云端 API 连通性。"""
        api_key = os.getenv("API_KEY")
        if not api_key:
            return LLMEndpoint("cloud", "云端 API", "cloud", "", False, detail="未配置 API_KEY")

        try:
            config = ApiModelConfig()
            adapter = get_adapter(
                self._provider,
                api_key=api_key,
                base_url=config.base_url,
                model=config.model,
            )

            client = httpx.Client(
                base_url=config.base_url,
                timeout=10,
                headers=adapter.auth_headers() if adapter else {"Authorization": f"Bearer {api_key}"},
            )
            start = time.time()

            # Use adapter's connectivity check if available
            if adapter:
                check_method, _ = adapter.build_connectivity_check()
                if check_method == "GET /models":
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
                # Fall through to default chat test

            # 回退：最小 chat 请求 (max_tokens=1)
            endpoint = adapter.chat_endpoint if adapter else "/chat/completions"
            test_model = config.model or "gpt-3.5-turbo"
            r = client.post(endpoint, json={
                "model": test_model,
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
            # trust_env=False：localhost 必须绕过系统代理，否则会被代理拒掉
            # （本机实测代理返回 502/超时 → 明明是本地服务却永远检测失败）。
            # connect=1.0：未监听时本机 connect 到 localhost 要 2~4s 才返回拒绝，
            # 这里主动设上限，避免探测把启动拖住。
            response = httpx.get(
                f"{self.OLLAMA_URL}/api/tags",
                timeout=httpx.Timeout(3.0, connect=1.0),
                trust_env=False,
            )
            latency = (time.time() - start) * 1000

            if response.status_code == 200:
                models = [m["name"] for m in response.json().get("models", [])]
                # 优先使用用户配置的模型名，否则取检测到的第一个
                preferred = ModelConfig.model
                selected = preferred if preferred in models else (models[0] if models else "无模型")
                if models:
                    logger.info("Ollama 检测成功: %d 个模型可用, 主模型=%s", len(models), selected)
                else:
                    logger.warning("Ollama 在线但无可用模型")

                return LLMEndpoint(
                    "ollama", "Ollama 本地", "local",
                    selected,
                    available=len(models) > 0,
                    latency_ms=latency,
                    detail=f"{len(models)} 个模型可用" if models else "无可用模型",
                )
            else:
                return LLMEndpoint(
                    "ollama", "Ollama 本地", "local", "", False,
                    latency, detail=f"HTTP {response.status_code}",
                )
        except (httpx.ConnectError, httpx.TimeoutException):
            # 连接被拒 / connect 超时：都等价于"本地没跑 Ollama"，按 INFO 记录即可
            # （之前超时落到下面的通用分支，会打出"检测异常: timed out"的 WARNING 噪音）
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

        DSH 式路由：信任近期验证过的端点直接返回实例（不每次 ping）；
        真实调用失败由客户端 on_failure 回调标记降级冷却；
        健康检查仅在验证缓存过期时低频执行一次。

        Returns:
            tuple[ApiLLM | LocalLLM | None, str]: (llm 实例, 使用中的后端 id)
            均不可用时返回 (None, "")。
        """
        self._ensure_detected()
        now = time.time()
        cooldown = 30.0

        candidates = []
        for ep, role in [(self._primary, "primary"), (self._fallback, "fallback")]:
            if ep is None:
                continue
            last_fail = self._endpoint_fail_time.get(ep.id, 0)
            if now - last_fail < cooldown:
                continue
            candidates.append((ep, role))

        for ep, role in candidates:
            # 验证缓存未过期：跳过 ping，直接返回实例（真实失败会标记端点）
            if now - self._verified_at.get(ep.id, 0.0) < self.VERIFY_TTL:
                try:
                    return self._instantiate(ep), ep.id
                except Exception:
                    self._endpoint_fail_time[ep.id] = now
                    continue

            try:
                llm = self._instantiate(ep)
                # 能返回即视为健康（错误不再伪装成文本，直接抛 LLMError）
                llm.chat([{"role": "user", "content": "."}], max_tokens=1)
                self._verified_at[ep.id] = now
                return llm, ep.id
            except LLMError:
                self._endpoint_fail_time[ep.id] = now
                continue
            except Exception:
                self._endpoint_fail_time[ep.id] = now
                continue

        # 都失败：重试一次主后端（不 ping，信任最后一次探测结果）
        if self._primary:
            try:
                llm = self._instantiate(self._primary)
                if llm:
                    return llm, self._primary.id
            except Exception:
                pass

        return None, ""

    def mark_endpoint_failed(self, endpoint_id: str):
        """标记端点调用失败，进入降级冷却（由客户端 on_failure 回调触发）。"""
        self._endpoint_fail_time[endpoint_id] = time.time()
        logger.warning("LLM 端点 %s 标记失败，%ss 内降级到备用后端",
                       endpoint_id, 30.0)

    def _instantiate(self, ep: LLMEndpoint) -> ApiLLM | LocalLLM:
        """返回端点对应的 LLM 实例（同一端点全程复用同一个实例）。

        复用是启动性能的关键：ApiLLM/LocalLLM 内部的 httpx.Client 构造在本机
        约 0.8s（httpx 每次都重新读取系统代理并重建代理 transport 与 SSL 上下文）。
        旧实现每次 get_llm() 都新建实例，而启动时会恢复全部历史会话（本机 158 个），
        每个会话都会 refresh_llm() → 新建 client ≈ 0.8s，累计 ~2 分钟；这段时间
        端口还没开始监听，前端所有 /api 请求都是 ECONNREFUSED。
        复用同一实例同时收敛了连接池，避免每轮对话都重建 client。

        实例在 _detect() 重建端点时清空（配置变更后不会复用旧 base_url/api_key）。
        """
        with self._instance_lock:
            cached = self._instances.get(ep.id)
            if cached is not None:
                return cached
            llm = self._create_instance(ep)
            if llm is not None:
                self._instances[ep.id] = llm
            return llm

    def _create_instance(self, ep: LLMEndpoint) -> ApiLLM | LocalLLM:
        """根据端点类型创建 LLM 实例（真实失败经 on_failure 标记端点降级）。"""
        def _on_failure(code: str):
            self.mark_endpoint_failed(ep.id)

        if ep.type == "cloud":
            adapter = get_adapter(
                self._provider,
                api_key=os.getenv("API_KEY", ""),
                base_url=os.getenv("BASE_URL", ""),
                model=ApiModelConfig.model,
            )
            return ApiLLM(adapter=adapter,
                          enable_thinking=self._enable_thinking,
                          reasoning_effort=self._reasoning_effort,
                          on_failure=_on_failure)
        elif ep.type == "local":
            config = ModelConfig()
            config.base_url = self.OLLAMA_URL
            config.model = ep.model
            return LocalLLM(config, on_failure=_on_failure)
        return None

    # ── 状态查询 ──

    def get_status(self) -> dict:
        """返回前端状态栏所需信息。"""
        self._ensure_detected()
        return {
            "primary": self._primary.to_dict() if self._primary else None,
            "fallback": self._fallback.to_dict() if self._fallback else None,
            "endpoints": [ep.to_dict() for ep in self._all_endpoints],
            "available": self._primary is not None and self._primary.available,
        }

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
            "skin": merged.get("skin", "default"),
            "provider": merged.get("provider", "auto"),
            "enable_thinking": merged.get("enable_thinking", False),
            "reasoning_effort": merged.get("reasoning_effort", "medium"),
            "narration_reasoning_effort": merged.get("narration_reasoning_effort", "none"),
            "auto_generate_choices": merged.get("auto_generate_choices", False),
            "choice_count": merged.get("choice_count", 3),
            "memory_interval": merged.get("memory_interval", 5),
            "edit_before_send": merged.get("edit_before_send", False),
            "dialogue_bubble_mode": merged.get("dialogue_bubble_mode", False),
            "max_output_tokens": merged.get("max_output_tokens", 16384),
            "word_limit": merged.get("word_limit", 500),
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
        if "skin" in data:
            skin = str(data["skin"]).strip().lower()
            merged["skin"] = skin if skin in ("default", "prts", "tavern") else "default"
        if "auto_generate_choices" in data:
            merged["auto_generate_choices"] = bool(data["auto_generate_choices"])
        if "choice_count" in data:
            merged["choice_count"] = max(1, min(5, int(data["choice_count"])))
        if "memory_interval" in data:
            merged["memory_interval"] = max(1, min(20, int(data["memory_interval"])))
        if "edit_before_send" in data:
            merged["edit_before_send"] = bool(data["edit_before_send"])
        if "dialogue_bubble_mode" in data:
            merged["dialogue_bubble_mode"] = bool(data["dialogue_bubble_mode"])
        if "max_output_tokens" in data:
            merged["max_output_tokens"] = max(256, min(32768, int(data["max_output_tokens"])))
        if "word_limit" in data:
            merged["word_limit"] = max(100, min(3000, int(data["word_limit"])))
        if "provider" in data:
            merged["provider"] = data["provider"]
        if "enable_thinking" in data:
            merged["enable_thinking"] = bool(data["enable_thinking"])
        if "reasoning_effort" in data:
            merged["reasoning_effort"] = data["reasoning_effort"]
        if "narration_reasoning_effort" in data:
            effort = str(data["narration_reasoning_effort"]).strip().lower()
            if effort not in ("none", "low", "medium", "high"):
                effort = "none"
            merged["narration_reasoning_effort"] = effort

        # 持久化到 JSON 文件
        _write_config_file(merged)

        # 同步到运行时（仅 LLM 相关字段）
        if "api_key" in merged:
            os.environ["API_KEY"] = merged["api_key"]
            ApiModelConfig.api_key = merged["api_key"]
        if "base_url" in merged:
            os.environ["BASE_URL"] = merged["base_url"]
            ApiModelConfig.base_url = merged["base_url"]
        ApiModelConfig.model = merged["cloud_model"]
        ApiModelConfig.max_tokens = merged.get("max_output_tokens", 8192)
        ModelConfig.max_tokens = merged.get("max_output_tokens", 8192)
        self.OLLAMA_URL = merged["ollama_url"]
        ModelConfig.model = merged["ollama_model"]
        self._provider = merged.get("provider", "auto")
        self._enable_thinking = bool(merged.get("enable_thinking", False))
        self._reasoning_effort = merged.get("reasoning_effort", "medium")

        self._detected = False

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
            r = httpx.get(f"{url}/api/tags", timeout=5, trust_env=False)
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
