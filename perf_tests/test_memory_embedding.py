# -*- coding: utf-8 -*-
"""回归测试：语义记忆嵌入源解析与降级行为。

背景（perf_tests/benchmark-report-2026-09-12.md B1）：生产 ApiLLM.embed 打
DeepSeek /embeddings（端点不存在），首次失败短路后语义检索从未运行，
全程纯滑窗。修复：CharacterAgent 构造时经 resolve_embed_fn 探测远端
embedding，不可用回退本地 ONNX 嵌入（chromadb DefaultEmbeddingFunction）。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from memory import VectorMemory, get_local_embed_fn, resolve_embed_fn  # noqa: E402


class _WorkingRemoteLLM:
    """远端 embedding 可用（如 OpenAI 兼容 /embeddings）。"""

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _ShortCircuitLLM:
    """模拟 DeepSeek：/embeddings 不存在，失败后短路返回 None。"""

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return None


class _RaisingLLM:
    """embed 直接抛异常的病态后端。"""

    def embed(self, texts):
        raise RuntimeError("embed backend crashed")


def test_resolve_prefers_working_remote_embed():
    llm = _WorkingRemoteLLM()
    fn = resolve_embed_fn(llm)
    assert fn == llm.embed


def test_resolve_falls_back_to_local_when_remote_short_circuits():
    if get_local_embed_fn() is None:
        pytest.skip("本地 ONNX 嵌入不可用（onnxruntime 缺失等）")
    llm = _ShortCircuitLLM()
    fn = resolve_embed_fn(llm)
    assert fn is not None
    assert fn != llm.embed
    vec = fn(["测试文本"])
    assert vec is not None and len(vec) == 1 and len(vec[0]) > 0
    # 探测只发生一次：短路后不再对远端发起无效调用
    assert llm.calls == 1


def test_resolve_survives_raising_remote_embed():
    llm = _RaisingLLM()
    fn = resolve_embed_fn(llm)  # 不应抛异常
    assert fn is get_local_embed_fn() or fn is None


def test_resolve_without_llm_uses_local():
    fn = resolve_embed_fn(None)
    assert fn is get_local_embed_fn() or fn is None


def test_vector_memory_end_to_end_with_local_embedding(tmp_path):
    local = get_local_embed_fn()
    if local is None:
        pytest.skip("本地 ONNX 嵌入不可用（onnxruntime 缺失等）")
    vm = VectorMemory("semantic_e2e_char", embed_fn=local,
                      persist_dir=str(tmp_path), recent_turns=1)
    facts = [
        ("阿米娅的共鸣石坠夜里会发光", "那是博士送的礼物"),
        ("临光的旧铠甲修过三次", "肩甲上有一道试剑的划痕"),
        ("银灰把铁路图纸锁在书房暗格", "只有灵知知道密码"),
    ]
    for user, resp in facts:
        vm.add(user, resp)
    got = vm.retrieve("脖子上那块会发光的石头是哪来的？", top_k=1)
    assert any("共鸣石" in d for d in got), got


def test_retrieve_degrades_on_dimension_mismatch(tmp_path):
    # 嵌入源切换（维度变化）后检索应降级为空列表而不是抛异常
    vm = VectorMemory("dim_mismatch_char", embed_fn=lambda t: [[1.0, 0.0] for _ in t],
                      persist_dir=str(tmp_path), recent_turns=2)
    vm.add("你好", "你好，博士")
    vm.embed_fn = lambda t: [[1.0, 0.0, 0.0] for _ in t]
    assert vm.retrieve("你好") == []


def test_add_survives_embedding_failure(tmp_path):
    # 嵌入函数抛异常：对话仍进入滑动窗口，不阻断
    def broken_embed(texts):
        raise RuntimeError("embed down")

    vm = VectorMemory("add_fail_char", embed_fn=broken_embed,
                      persist_dir=str(tmp_path), recent_turns=2)
    vm.add("你好", "你好，博士")
    ctx = vm.build_context("你好")
    assert "你好，博士" in ctx
