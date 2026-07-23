"""LLM service unit tests — error mapping and JSON extraction (no network calls)."""
from __future__ import annotations

import pytest

from app.services.llm_service import LLMError, _extract_json, _friendly


@pytest.mark.parametrize(
    "raw,needle",
    [
        ("Error code: 401 invalid api key", "key"),
        ("429 rate limit exceeded", "rate limit"),
        ("request timed out", "timed out"),
        ("getaddrinfo failed", "reach"),
        ("404 model not found", "not found"),
        ("some unexpected boom", "failed"),
    ],
)
def test_friendly_error_mapping(raw, needle):
    msg = str(_friendly(Exception(raw)))
    assert needle.lower() in msg.lower()


def test_friendly_passthrough_llmerror():
    original = LLMError("already friendly")
    assert _friendly(original) is original


def test_extract_json_from_fenced_text():
    text = 'Here you go:\n```json\n{"a": 1, "b": {"c": 2}}\n```\nDone.'
    assert _extract_json(text) == '{"a": 1, "b": {"c": 2}}'


def test_extract_json_raises_when_absent():
    with pytest.raises(LLMError):
        _extract_json("no json here")
