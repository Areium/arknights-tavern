# -*- coding: utf-8 -*-
"""回归测试：LLM 实例复用（后端启动性能的关键路径）。

背景：`SessionManager` 启动时会恢复全部历史会话（本机 158 个），每个会话都会
`Session.refresh_llm()` → `LLMBackendManager.get_llm()`。旧实现每次调用都新建
`ApiLLM`，而 `httpx.Client` 构造在本机约 0.8s（每次都重读系统代理、重建代理
transport 与 SSL 上下文）→ 启动累计约 2 分钟，端口迟迟不监听，前端全部
ECONNREFUSED（表现为“后端无法启动”）。

约定（本测试固定）：
- 同一端点全程复用同一个 LLM 实例，多次 get_llm() 不重复构造 client；
- 重新检测（配置变更后 _detected=False）会丢弃缓存，新配置不被旧 client 顶掉；
- 云端可用时 Ollama 探测转后台，且过期探测结果不得覆盖重新检测的结果。
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from llm_backend_manager import LLMBackendManager, LLMEndpoint  # noqa: E402


def _cloud_endpoint() -> LLMEndpoint:
    return LLMEndpoint("cloud", "云端 API", "cloud", "test-model", available=True)


def _make_manager(monkeypatch, endpoint=None):
    """构造一个不做真实网络探测的 manager。"""
    monkeypatch.setattr(LLMBackendManager, "_ensure_config", staticmethod(lambda: None))
    mgr = LLMBackendManager()
    ep = endpoint or _cloud_endpoint()
    monkeypatch.setattr(mgr, "_check_cloud", lambda: ep)
    monkeypatch.setattr(mgr, "_check_ollama", lambda: None)
    monkeypatch.setattr(mgr, "_probe_ollama_async", lambda gen: None)
    monkeypatch.setenv("API_KEY", "test-key")
    # 命中“验证缓存未过期”分支：不发起真实验证 chat（保持测试不触网）
    mgr._verified_at[ep.id] = time.time()
    return mgr, ep


def test_get_llm_reuses_same_instance(monkeypatch):
    """多次 get_llm() 必须返回同一实例（否则每个会话重建 client）。"""
    mgr, _ = _make_manager(monkeypatch)

    first, first_id = mgr.get_llm()
    second, second_id = mgr.get_llm()
    third, _ = mgr.get_llm()

    assert first is not None
    assert first is second is third, "同一端点被重复实例化（启动会被拖慢）"
    assert first_id == second_id == "cloud"
    assert list(mgr._instances) == ["cloud"]


def test_redetect_discards_cached_instance(monkeypatch):
    """配置变更触发重新检测后，必须换用新实例（旧 client 会带旧 base_url）。"""
    mgr, _ = _make_manager(monkeypatch)
    before, _ = mgr.get_llm()

    mgr._detected = False  # update_config() 会这样标记
    after, _ = mgr.get_llm()

    assert after is not before, "重新检测后仍复用旧实例"
    assert list(mgr._instances) == ["cloud"]


def test_cloud_available_defers_ollama_probe(monkeypatch):
    """云端可用时：同步探测不得调用 Ollama（未监听时本机要 2~4s）。"""
    probe_calls = []
    monkeypatch.setattr(LLMBackendManager, "_ensure_config", staticmethod(lambda: None))
    mgr = LLMBackendManager()
    monkeypatch.setattr(mgr, "_check_cloud", _cloud_endpoint)
    monkeypatch.setattr(mgr, "_check_ollama",
                        lambda: probe_calls.append("sync") or None)
    monkeypatch.setattr(mgr, "_probe_ollama_async",
                        lambda gen: probe_calls.append(("async", gen)))
    monkeypatch.setenv("API_KEY", "test-key")
    mgr._verified_at["cloud"] = time.time()

    mgr.get_llm()

    assert "sync" not in probe_calls, "云端可用时不应同步探测 Ollama"
    assert probe_calls == [("async", 1)]


def test_stale_ollama_probe_result_discarded(monkeypatch):
    """过期（重新检测前发起）的异步探测结果不得覆盖新状态。"""
    mgr = LLMBackendManager.__new__(LLMBackendManager)
    mgr._lock = threading.Lock()
    mgr._detect_gen = 3
    mgr._all_endpoints = [_cloud_endpoint()]
    mgr._primary = mgr._all_endpoints[0]
    mgr._fallback = None
    stale = LLMEndpoint("ollama", "Ollama 本地", "local", "m", available=True)
    monkeypatch.setattr(mgr, "_check_ollama", lambda: stale)

    mgr._probe_ollama_async(gen=2)  # 过期代数

    assert [ep.id for ep in mgr._all_endpoints] == ["cloud"], "过期结果被写入了端点表"
    assert mgr._fallback is None


def test_fresh_ollama_probe_registers_as_fallback(monkeypatch):
    """当前代数的探测结果应登记为备选端点，且不打乱主后端顺序。"""
    mgr = LLMBackendManager.__new__(LLMBackendManager)
    mgr._lock = threading.Lock()
    mgr._detect_gen = 5
    mgr._all_endpoints = [_cloud_endpoint()]
    mgr._primary = mgr._all_endpoints[0]
    mgr._fallback = None
    local = LLMEndpoint("ollama", "Ollama 本地", "local", "m", available=True)
    monkeypatch.setattr(mgr, "_check_ollama", lambda: local)

    mgr._probe_ollama_async(gen=5)

    assert [ep.id for ep in mgr._all_endpoints] == ["cloud", "ollama"]
    assert mgr._primary.id == "cloud"
    assert mgr._fallback is local
