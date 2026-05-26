"""
Unit tests for marker extraction helpers (no LLM dependency).

Run with::

    pytest tests/test_marker_extraction.py -v
"""

import json
import sys
import os

# Ensure project root and src/ are importable
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
_src = os.path.join(_project_root, "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from SceneManager import (
    _empty_extraction_result,
    _parse_extraction_json,
    _normalize_combat_field,
    _normalize_choices_field,
    _normalize_summary_field,
)


class TestEmptyExtractionResult:
    def test_all_fields_default(self):
        r = _empty_extraction_result()
        assert r["beat_complete"] is False
        assert r["combat"] is None
        assert r["choices"] is None
        assert r["summary"] is None
        assert r["usage"] is None
        assert r["error"] is None


class TestNormalizeCombatField:
    def test_valid(self):
        result = _normalize_combat_field({"encounter_id": "test_enc", "params": None})
        assert result == {"encounter_id": "test_enc", "params": None}

    def test_with_params(self):
        result = _normalize_combat_field({
            "encounter_id": "test_enc",
            "params": {"status_effects": {"doctor": {"hp_penalty": 0.5}}}
        })
        assert result["encounter_id"] == "test_enc"
        assert result["params"] == {"status_effects": {"doctor": {"hp_penalty": 0.5}}}

    def test_null(self):
        assert _normalize_combat_field(None) is None

    def test_empty_dict(self):
        assert _normalize_combat_field({}) is None

    def test_empty_encounter_id(self):
        assert _normalize_combat_field({"encounter_id": ""}) is None
        assert _normalize_combat_field({"encounter_id": "  "}) is None

    def test_non_dict(self):
        assert _normalize_combat_field("not_a_dict") is None
        assert _normalize_combat_field([]) is None

    def test_params_not_dict(self):
        result = _normalize_combat_field({
            "encounter_id": "test",
            "params": "not_a_dict"
        })
        assert result == {"encounter_id": "test", "params": None}


class TestNormalizeChoicesField:
    def test_valid(self):
        assert _normalize_choices_field(["A", "B", "C"]) == ["A", "B", "C"]

    def test_empty_list(self):
        assert _normalize_choices_field([]) is None

    def test_null(self):
        assert _normalize_choices_field(None) is None

    def test_non_list(self):
        assert _normalize_choices_field("not_a_list") is None

    def test_filters_empty_strings(self):
        assert _normalize_choices_field(["A", "", "B"]) == ["A", "B"]

    def test_filters_long_strings(self):
        long_str = "x" * 31
        assert _normalize_choices_field(["A", long_str, "B"]) == ["A", "B"]

    def test_all_filtered_out(self):
        assert _normalize_choices_field(["", ""]) is None


class TestNormalizeSummaryField:
    def test_valid(self):
        assert _normalize_summary_field("  test summary  ") == "test summary"

    def test_empty_string(self):
        assert _normalize_summary_field("") is None
        assert _normalize_summary_field("   ") is None

    def test_null(self):
        assert _normalize_summary_field(None) is None

    def test_non_string(self):
        assert _normalize_summary_field(123) is None


class TestParseExtractionJSON:
    def test_valid_json(self):
        data = {
            "beat_complete": True,
            "combat_trigger": None,
            "choices": ["选项一", "选项二"],
            "summary": "测试摘要",
        }
        result = _parse_extraction_json(json.dumps(data))
        assert result["beat_complete"] is True
        assert result["combat"] is None
        assert result["choices"] == ["选项一", "选项二"]
        assert result["summary"] == "测试摘要"

    def test_valid_json_with_combat(self):
        data = {
            "beat_complete": False,
            "combat_trigger": {"encounter_id": "test_enc", "params": None},
            "choices": None,
            "summary": None,
        }
        result = _parse_extraction_json(json.dumps(data))
        assert result["beat_complete"] is False
        assert result["combat"] == {"encounter_id": "test_enc", "params": None}
        assert result["choices"] is None
        assert result["summary"] is None

    def test_markdown_wrapped(self):
        data = {"beat_complete": False, "combat_trigger": None, "choices": None, "summary": "test"}
        text = "```json\n" + json.dumps(data) + "\n```"
        result = _parse_extraction_json(text)
        assert result["summary"] == "test"

    def test_markdown_wrapped_multi_line(self):
        data = {"beat_complete": False, "combat_trigger": None, "choices": None, "summary": "test"}
        text = "```\n" + json.dumps(data) + "\n```"
        result = _parse_extraction_json(text)
        assert result["summary"] == "test"

    def test_json_buried_in_text(self):
        data = {"beat_complete": False, "combat_trigger": None, "choices": None, "summary": "test"}
        text = "Here is the result: " + json.dumps(data) + " That's all."
        result = _parse_extraction_json(text)
        assert result["summary"] == "test"

    def test_invalid_json(self):
        result = _parse_extraction_json("this is not json at all")
        assert result == _empty_extraction_result()

    def test_empty_string(self):
        result = _parse_extraction_json("")
        assert result == _empty_extraction_result()

    def test_missing_fields_default_to_false_null(self):
        data = {"beat_complete": True}
        result = _parse_extraction_json(json.dumps(data))
        assert result["beat_complete"] is True
        assert result["combat"] is None
        assert result["choices"] is None
        assert result["summary"] is None

    def test_non_boolean_beat_complete_coerced(self):
        data = {"beat_complete": "yes"}
        result = _parse_extraction_json(json.dumps(data))
        assert result["beat_complete"] is True  # bool("yes") = True
