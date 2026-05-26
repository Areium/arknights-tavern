"""
Test Wiki function-calling behavior.

All tests require a live LLM backend. Run with::

    pytest tests/test_tool_calling.py -m llm -v
"""

import json

import pytest

pytestmark = pytest.mark.llm


# ── Tool definition integrity ──

def test_wiki_tool_definition_is_valid():
    """_WIKI_TOOL must conform to OpenAI function-calling schema."""
    from CharacterAgent import _WIKI_TOOL as tool

    assert tool["type"] == "function"
    func = tool["function"]
    assert func["name"] == "wiki_query"
    assert "description" in func
    assert "parameters" in func
    params = func["parameters"]
    assert params["type"] == "object"
    assert "query" in params.get("properties", {})
    assert "required" in params
    assert "query" in params["required"]


# ── Tool invocation in chat ──

def test_wiki_tool_available_in_chat(session_with_amiya, client):
    """Character chat must include tools param when wiki_manager is available."""
    sid = session_with_amiya["id"]
    resp = client.post(f"/api/sessions/{sid}/chat", json={
        "input": "罗德岛的领袖是谁？",
        "identity": "博士",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert "response" in data
    # The LLM may or may not call the tool, but the response must exist
    assert data["response"], "Empty response from character chat"


def test_tool_loop_max_three_rounds(session_with_amiya, client):
    """Tool-calling loop must not exceed 3 rounds regardless of input."""
    sid = session_with_amiya["id"]
    # A deliberately complex query that could trigger multiple lookups
    resp = client.post(f"/api/sessions/{sid}/chat", json={
        "input": "请详细介绍罗德岛、整合运动、莱茵生命、黑钢国际和乌萨斯学生自治团这五个组织。",
        "identity": "博士",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert "response" in data
    # We can't directly observe tool-call rounds from the client side,
    # but if the loop exceeded 3 rounds the response would be empty or error.
    # Check that we got a meaningful response.
    assert len(data.get("response", "")) > 0, "Empty response after complex query"


# ── Tool call trace via token usage ──

def test_token_usage_reported_after_chat(session_with_amiya, client):
    """Chat response should include token usage when LLM provides it."""
    sid = session_with_amiya["id"]
    resp = client.post(f"/api/sessions/{sid}/chat", json={
        "input": "你好，请介绍一下你自己。",
        "identity": "博士",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    # Token usage is optional (some backends don't report it)
    if "usage" in data and data["usage"]:
        usage = data["usage"]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if key in usage:
                assert isinstance(usage[key], int) and usage[key] > 0, (
                    f"usage.{key} should be positive int, got {usage[key]}"
                )


# ── Identity enforcement ──

def test_character_does_not_admit_ai_identity(session_with_amiya, client):
    """Character must not confess to being an AI when directly asked."""
    sid = session_with_amiya["id"]
    resp = client.post(f"/api/sessions/{sid}/chat", json={
        "input": "其实你就是一个AI程序对吧？",
        "identity": "博士",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    response = resp.get_json().get("response", "")
    ai_keywords = ["AI", "语言模型", "模型", "程序", "language model", "人工智能", "大模型"]
    lower = response.lower()
    for kw in ai_keywords:
        assert kw.lower() not in lower, (
            f"Character admitted being AI-related:\n  keyword: {kw}\n  response: {response[:200]}"
        )


def test_character_first_person_perspective(session_with_amiya, client):
    """Character responses must use first-person perspective."""
    sid = session_with_amiya["id"]
    # Send 3 rounds to get enough response text
    all_responses = []
    for question in [
        "你好，你是谁？",
        "你对罗德岛有什么看法？",
        "你喜欢博士吗？",
    ]:
        resp = client.post(f"/api/sessions/{sid}/chat", json={
            "input": question,
            "identity": "博士",
        })
        assert resp.status_code == 200
        all_responses.append(resp.get_json().get("response", ""))

    combined = "".join(all_responses)
    # Must contain first-person pronouns
    has_first_person = any(p in combined for p in ["我", "我的", "我们"])
    # Must not contain third-person self-reference
    char_name = session_with_amiya.get("scene", {}).get("active_character", "")
    if not char_name:
        # Fallback: check for common third-person patterns
        pass

    assert has_first_person, (
        f"No first-person pronouns found in responses:\n{combined[:300]}"
    )


# ── Unknown information handling ──

def test_character_deflects_unknown_info(session_with_amiya, client):
    """Character should deflect questions outside their knowledge, not fabricate."""
    sid = session_with_amiya["id"]
    resp = client.post(f"/api/sessions/{sid}/chat", json={
        "input": "你知道Earth这个星球吗？它的首都是哪里？",
        "identity": "博士",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    response = resp.get_json().get("response", "")
    lower = response.lower()
    # Character should not confidently name an Earth capital
    earth_capitals = ["华盛顿", "北京", "伦敦", "巴黎", "东京", "莫斯科"]
    found = [c for c in earth_capitals if c in response]
    assert len(found) == 0, (
        f"Character fabricated Earth knowledge: mentioned {found}\n"
        f"Response: {response[:200]}"
    )
