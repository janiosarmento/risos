"""Tests for the LLM-flagged excluded audience on summaries."""

import json

from app.services.ai._api import _parse_summary_result


def _payload(**extra):
    body = {
        "summary_pt": "The article explains how much memory a gaming PC needs.",
        "one_line_summary": "16GB is enough for gaming.",
        "translated_title": None,
        "tags": ["gaming", "ram"],
    }
    body.update(extra)
    return json.dumps(body)


def test_excluded_audience_is_normalized():
    result = _parse_summary_result(_payload(excluded_audience=" Gamers "), False, "m")
    assert result.excluded_audience == "gamers"


def test_excluded_audience_null_variants_become_none():
    for value in (None, "null", "None", "", "n/a", 3):
        result = _parse_summary_result(
            _payload(excluded_audience=value), False, "m"
        )
        assert result.excluded_audience is None


def test_missing_key_is_none():
    assert _parse_summary_result(_payload(), False, "m").excluded_audience is None
