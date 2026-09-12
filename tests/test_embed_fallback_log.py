# -*- coding: utf-8 -*-
"""回归测试：embedding 端点不可用时不得刷终端日志噪音。

背景：DeepSeek 等端点不提供 /embeddings，每个 CharacterAgent 都会新建 ApiLLM
并探测一次。此前是逐实例 WARNING，启动时会在终端刷出多行
"Embedding API 不可用 (将回退到滑动窗口模式)"。

约定（本测试固定）：
- 端点不可用是常态，终端（INFO 及以上）不得出现任何提示；
- 每个端点每进程只留一条 DEBUG 记录；
- 同一端点已判定不支持后不再重复发起探测请求；
- 换端点（换成支持 /embeddings 的服务）仍会重新探测。
"""

import logging
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from load_llm import ApiLLM, ApiModelConfig  # noqa: E402


def _embed_records(caplog):
    return [r for r in caplog.records
            if r.name == "load_llm" and "mbed" in r.getMessage()]


def _make_llm(base_url, transport=None):
    cfg = ApiModelConfig()
    cfg.base_url = base_url
    cfg.api_key = "test-key"
    cfg.timeout = 5
    llm = ApiLLM(config=cfg)
    if transport is not None:
        llm.client = httpx.Client(base_url=base_url, timeout=5, transport=transport)
    return llm


def _failing_transport(counter):
    """模拟“端点无 /embeddings”：返回 404，不触网。"""
    def handler(request):
        counter.append(str(request.url))
        return httpx.Response(404, json={"error": {"message": "Not Found"}})
    return httpx.MockTransport(handler)


def _ok_transport(counter):
    def handler(request):
        counter.append(str(request.url))
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [0.3, 0.4]},
            {"index": 0, "embedding": [0.1, 0.2]},
        ]})
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _fresh_endpoint_cache(monkeypatch):
    """每个用例用干净的端点记忆，避免用例间互相短路。"""
    monkeypatch.setattr("load_llm._EMBED_UNSUPPORTED_ENDPOINTS", set())


def test_unavailable_endpoint_logs_nothing_visible(caplog):
    """端点不可用：终端（INFO+）零提示，每个端点仅一条 DEBUG。"""
    caplog.set_level(logging.DEBUG, logger="load_llm")
    calls = []
    base = "http://embed-unavailable.test/v1"
    for _ in range(3):
        llm = _make_llm(base, _failing_transport(calls))
        assert llm.embed(["探测"]) is None
        # 同实例二次调用命中实例级短路，不再发请求
        assert llm.embed(["探测"]) is None

    visible = [r for r in _embed_records(caplog) if r.levelno >= logging.INFO]
    assert visible == [], f"终端不应出现 embedding 提示，实际 {len(visible)} 条"
    debug_recs = [r for r in _embed_records(caplog) if r.levelno < logging.INFO]
    assert len(debug_recs) == 1, "每个端点每进程只应留一条 DEBUG 记录"
    # 端点级短路：3 个实例只探测 1 次（多数情况下启动时少发 2 个注定失败的请求）
    assert len(calls) == 1, f"同一端点被重复探测了 {len(calls)} 次"


def test_working_endpoint_returns_embeddings_in_index_order(caplog):
    """支持 /embeddings 的端点：正常返回向量（按 index 排序），无提示日志。"""
    caplog.set_level(logging.DEBUG, logger="load_llm")
    calls = []
    llm = _make_llm("http://embed-ok.test/v1", _ok_transport(calls))
    assert llm.embed(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]
    # 同一实例可继续调用（未被误短路）
    assert llm.embed(["c"]) == [[0.1, 0.2], [0.3, 0.4]]
    assert calls[0].endswith("/v1/embeddings")
    assert _embed_records(caplog) == []


def test_switching_to_capable_endpoint_reprobes(caplog):
    """先失败后换端点：新端点仍会重新探测（短路按 base_url 记忆）。"""
    caplog.set_level(logging.DEBUG, logger="load_llm")
    dead_calls = []
    assert _make_llm("http://embed-dead.test/v1",
                     _failing_transport(dead_calls)).embed(["x"]) is None

    ok_calls = []
    llm = _make_llm("http://embed-ok2.test/v1", _ok_transport(ok_calls))
    assert llm.embed(["x"]) == [[0.1, 0.2], [0.3, 0.4]]
    assert len(ok_calls) == 1, "换端点后应重新探测"


class _DeadRemoteLLM:
    """远端 embed 恒定返回 None（DeepSeek 形态）。"""

    def embed(self, texts):
        return None


def test_remote_fallback_notice_logged_once(caplog, monkeypatch):
    """回退本地的 INFO 每个进程只出现一次（多角色不再逐行重复）。"""
    import memory

    caplog.set_level(logging.INFO, logger="memory")
    monkeypatch.setattr("memory._REMOTE_FALLBACK_LOGGED", False)
    # 不加载真实 ONNX 模型，只验证日志与定源行为
    monkeypatch.setattr("memory.get_local_embed_fn",
                        lambda: (lambda texts: [[0.0] for _ in texts]))

    for _ in range(3):
        assert memory.resolve_embed_fn(_DeadRemoteLLM()) is not None

    fallback = [r for r in caplog.records
                if r.name == "memory" and "回退本地" in r.getMessage()]
    assert len(fallback) == 1, f"回退提示重复了 {len(fallback)} 次"
    assert fallback[0].levelno == logging.INFO
