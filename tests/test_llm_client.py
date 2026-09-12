# -*- coding: utf-8 -*-
"""LLM 客户端传输层测试：请求指纹、重试、结构化错误。"""

import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from load_llm import (  # noqa: E402
    LLMConnectError,
    LLMError,
    LocalLLM,
    _post_with_retry,
    _request_fingerprint,
)


def _make_connect_error():
    try:
        return httpx.ConnectError("boom", request=None)
    except TypeError:
        return httpx.ConnectError("boom")


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = "body"

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://fake/api/chat")
            try:
                raise httpx.HTTPStatusError(
                    f"HTTP {self.status_code}", request=request, response=self)
            except TypeError:
                raise httpx.HTTPStatusError(
                    f"HTTP {self.status_code}", request, self)


class _FlakyClient:
    """前 N 次连接失败 / 状态码可编程的假客户端。"""

    def __init__(self, statuses, connect_failures=0):
        self.statuses = list(statuses)
        self.connect_failures = connect_failures
        self.calls = 0

    def post(self, path, json=None):
        self.calls += 1
        if self.connect_failures > 0:
            self.connect_failures -= 1
            raise _make_connect_error()
        return _FakeResponse(self.statuses.pop(0))


# ── 请求指纹 ──

def test_fingerprint_deterministic():
    msgs = [{"role": "system", "content": "你是测试角色。"},
            {"role": "user", "content": "你好"}]
    fp1, est1 = _request_fingerprint(msgs)
    fp2, est2 = _request_fingerprint([dict(m) for m in msgs])
    assert fp1 == fp2 and est1 == est2 > 0


def test_fingerprint_sensitive_to_prefix_change():
    """system 前缀变化必须改变指纹（这是漂移检测的基础）。"""
    base = [{"role": "system", "content": "稳定前缀"}, {"role": "user", "content": "hi"}]
    changed = [{"role": "system", "content": "稳定前缀变了"}, {"role": "user", "content": "hi"}]
    fp1, _ = _request_fingerprint(base)
    fp2, _ = _request_fingerprint(changed)
    assert fp1 != fp2


# ── 重试 ──

def test_retry_on_connect_error_then_success():
    client = _FlakyClient([200], connect_failures=2)
    resp = _post_with_retry(client, "/api/chat", {})
    assert resp.status_code == 200 and client.calls == 3


def test_retry_on_429_then_success(monkeypatch):
    monkeypatch.setattr("load_llm.time.sleep", lambda _: None)
    client = _FlakyClient([429, 503, 200])
    resp = _post_with_retry(client, "/api/chat", {})
    assert resp.status_code == 200 and client.calls == 3


def test_connect_error_raises_after_exhaust(monkeypatch):
    monkeypatch.setattr("load_llm.time.sleep", lambda _: None)
    client = _FlakyClient([], connect_failures=99)
    with pytest.raises(LLMConnectError):
        _post_with_retry(client, "/api/chat", {})


def test_non_retryable_status_returned_directly():
    """400 不重试，直接交给调用方 raise_for_status 转结构化 HTTP 错误。"""
    client = _FlakyClient([400])
    resp = _post_with_retry(client, "/api/chat", {})
    assert resp.status_code == 400 and client.calls == 1


# ── 结构化错误（不再伪装成模型回复）──

def test_chat_raises_structured_error_and_notifies_failure(monkeypatch):
    monkeypatch.setattr("load_llm.time.sleep", lambda _: None)
    failures = []
    llm = LocalLLM()
    llm._on_failure = lambda code: failures.append(code)
    llm.client = _FlakyClient([], connect_failures=99)

    with pytest.raises(LLMConnectError) as exc_info:
        llm.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.code == "connect"
    assert failures == ["connect"]  # on_failure 回调被触发（降级标记）


def test_chat_http_error_mapped_to_llm_http_error(monkeypatch):
    monkeypatch.setattr("load_llm.time.sleep", lambda _: None)
    llm = LocalLLM()
    llm._on_failure = lambda code: None
    llm.client = _FlakyClient([500, 500, 500])

    with pytest.raises(LLMError) as exc_info:
        llm.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.code == "http"
    assert exc_info.value.status_code == 500
