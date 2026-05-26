"""
Shared fixtures for prompt-related tests.

All tests that hit the LLM API must be marked @pytest.mark.llm.
Set environment variable ARKNIGHTS_API_KEY before running these tests.
"""

import json
import os
import re
import sys
import time
from collections.abc import Generator

import pytest

# Ensure project root and src/ are importable
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
_src = os.path.join(_project_root, "src")
if _src not in sys.path:
    sys.path.insert(0, _src)


# ── Regexes for output-format markers ──

ENV_RE = re.compile(r"<env:\s*(\{.*?\})\s*/>", re.DOTALL)


# ── Helpers ──

def parse_sse_events(response) -> list[dict]:
    """Parse a Flask SSE response into a list of event dicts.

    Each event has keys: ``type``, ``data`` (the unwrapped inner payload).

    SSE format::

        data: {"type": "text", "data": {"token": "x", ...}}

        data: {"type": "done", "data": {"stream_id": "..."}}

    The outer ``type`` becomes the event type; the inner ``data`` is unwrapped.
    """
    events = []
    current_data = ""
    # response.response yields bytes chunks that may contain multiple lines
    for chunk in response.response:
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
        for line in text.split("\n"):
            stripped = line.rstrip("\r")
            if stripped.startswith("data: "):
                current_data += stripped[6:]
            elif stripped == "" and current_data:
                try:
                    parsed = json.loads(current_data)
                    events.append({
                        "type": parsed.get("type", "unknown"),
                        "data": parsed.get("data", parsed),
                    })
                except json.JSONDecodeError:
                    events.append({"type": "raw", "data": {"raw": current_data}})
                current_data = ""
    # flush remaining
    if current_data.strip():
        try:
            parsed = json.loads(current_data)
            events.append({
                "type": parsed.get("type", "unknown"),
                "data": parsed.get("data", parsed),
            })
        except json.JSONDecodeError:
            events.append({"type": "raw", "data": {"raw": current_data}})
    return events


def sse_text(events: list[dict]) -> str:
    """Concatenate all ``text`` SSE events into a single string."""
    return "".join(e["data"].get("token", "") for e in events if e["type"] == "text")



def wait_for_event(events: list[dict], event_type: str, timeout: float = 60.0) -> dict | None:
    """Poll *events* (in-place) until an event of *event_type* appears or timeout.

    Used with background SSE streams that collect events asynchronously.
    For synchronous SSE collection (where all events arrive before we process),
    use a direct loop over ``events`` instead.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        for e in events:
            if e["type"] == event_type:
                return e["data"]
        time.sleep(0.5)
    return None


# ── Fixtures ──

@pytest.fixture(scope="session")
def app():
    """Create the Flask app (session-scoped, reused across tests)."""
    from app import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    """Flask test client (per-test to avoid cookie/session bleed)."""
    with app.test_client() as c:
        yield c


@pytest.fixture
def free_session(client):
    """Create a free-mode session with no plot."""
    resp = client.post("/api/sessions", json={"mode": "free", "name": "pytest-free"})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


@pytest.fixture
def story_session_narrative(client):
    """Create a narrative-mode story session using near-light plot."""
    resp = client.post(
        "/api/sessions",
        json={"mode": "story", "combat_mode": "narrative", "plot_id": "near-light",
              "name": "pytest-narrative"},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


@pytest.fixture
def story_session_tactical(client):
    """Create a tactical-mode story session using combat-test plot."""
    resp = client.post(
        "/api/sessions",
        json={"mode": "story", "combat_mode": "tactical", "plot_id": "combat-test",
              "name": "pytest-tactical"},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


@pytest.fixture
def session_with_amiya(client, free_session):
    """Free session with Amiya loaded as the active character."""
    sid = free_session["id"]
    resp = client.post(f"/api/sessions/{sid}/characters/load", json={"character": "阿米娅"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return free_session


def _narrate_sse(client, session_id: str, identity: str = "博士", action: str = "") -> list[dict]:
    """Collect all SSE events from a narrate GET request."""
    url = f"/api/sessions/{session_id}/narrate?identity={identity}&action={action}"
    resp = client.get(url, headers={"Accept": "text/event-stream"})
    assert resp.status_code == 200, f"SSE narrate failed: {resp.get_data(as_text=True)[:500]}"
    return parse_sse_events(resp)


def _narrate_nonstream(client, session_id: str, identity: str = "博士", action: str = "") -> dict:
    """Call narrate-continue (non-SSE) and return the parsed JSON body."""
    resp = client.post(
        f"/api/sessions/{session_id}/narrate-continue",
        json={"identity": identity, "action": action},
    )
    assert resp.status_code == 200, f"narrate-continue failed: {resp.get_data(as_text=True)[:500]}"
    return resp.get_json()


@pytest.fixture
def narrate_sse(client):
    """Bound helper: collect SSE events from a narrate request."""
    return lambda sid, identity="博士", action="": _narrate_sse(client, sid, identity, action)


@pytest.fixture
def narrate_nonstream(client):
    """Bound helper: call narrate-continue and return JSON."""
    return lambda sid, identity="博士", action="": _narrate_nonstream(client, sid, identity, action)
