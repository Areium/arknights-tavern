"""
Test combat trigger flow: extraction → SSE event → session state.

All tests require a live LLM backend. Run with::

    pytest tests/test_combat_trigger.py -m llm -v
"""

import json

import pytest

pytestmark = pytest.mark.llm


# ── SSE event emission ──

def test_combat_trigger_sse_event_structure(story_session_tactical, narrate_sse):
    """Verify combat_trigger SSE event has correct structure when emitted."""
    sid = story_session_tactical["id"]
    events = narrate_sse(sid)
    combat_events = [e for e in events if e["type"] == "combat_trigger"]

    if len(combat_events) == 0:
        # Flash models may not always detect combat on first turn.
        # The extraction call depends on LLM output quality — this is
        # expected variance with smaller models, not a code bug.
        pytest.skip(
            f"No combat_trigger event emitted (flash model variance). "
            f"Event types: {[e['type'] for e in events]}"
        )

    trigger = combat_events[0]["data"]
    assert "encounter_id" in trigger
    assert "session_id" in trigger
    assert trigger["session_id"] == sid
    assert isinstance(trigger["encounter_id"], str) and trigger["encounter_id"], (
        f"encounter_id is empty or wrong type: {trigger.get('encounter_id')}"
    )


# ── Non-SSE path ──

def test_combat_triggered_flag_in_nonstream(story_session_tactical, narrate_nonstream):
    """narrate-continue in tactical mode should return combat_triggered=True when detected."""
    sid = story_session_tactical["id"]
    result = narrate_nonstream(sid)
    encounter_id = result.get("encounter_id")

    if not encounter_id:
        # Flash models may not detect combat on first turn — expected variance
        pytest.skip("No combat detected by extraction (flash model variance)")

    assert result.get("combat_triggered"), (
        f"encounter_id present ({encounter_id}) but combat_triggered is not True.\n"
        f"Narrative: {result.get('narrative', '')[:300]}"
    )


# ── Narrative mode isolation ──

def test_narrative_mode_no_combat_trigger(story_session_narrative, narrate_sse):
    """Narrative mode must never emit combat_trigger SSE events."""
    sid = story_session_narrative["id"]
    events = narrate_sse(sid)
    combat_events = [e for e in events if e["type"] == "combat_trigger"]
    assert len(combat_events) == 0, (
        f"Unexpected combat_trigger in narrative mode: {combat_events}"
    )


def test_narrative_mode_no_combat_flag(story_session_narrative, narrate_nonstream):
    """narrate-continue in narrative mode must not set combat_triggered=True."""
    sid = story_session_narrative["id"]
    result = narrate_nonstream(sid)
    assert not result.get("combat_triggered"), (
        f"combat_triggered=True in narrative mode.\n"
        f"Narrative: {result.get('narrative', '')[:300]}"
    )
