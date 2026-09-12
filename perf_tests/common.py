"""perf_tests 公共工具：加载 LLM 配置并构建 ApiLLM 客户端（不打印密钥）。"""
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)

_CONFIG_PATH = ROOT / "config" / "llm_config.json"


def load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_llm():
    """按 config/llm_config.json 构建 ApiLLM（云端通道，与后端一致）。"""
    from load_llm import ApiLLM, ApiModelConfig

    cfg = load_config()
    api_key = cfg.get("api_key") or ""
    base_url = cfg.get("base_url") or "https://api.deepseek.com/v1"
    model = cfg.get("cloud_model") or "deepseek-v4-flash"
    if not api_key:
        raise RuntimeError("config/llm_config.json 未配置 api_key")
    config = ApiModelConfig()
    config.api_key = api_key
    config.base_url = base_url
    config.model = model
    config.max_tokens = 4096
    config.temperature = 0.5
    config.timeout = 120
    return ApiLLM(config=config)


def sanitize_usage(usage: dict | None) -> dict:
    """规整 usage 字段，避免流式返回缺键。"""
    if not usage:
        return {}
    return {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "cache_hit": usage.get("prompt_cache_hit_tokens", 0),
        "cache_miss": usage.get("prompt_cache_miss_tokens", 0),
    }