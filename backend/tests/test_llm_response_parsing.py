import asyncio
from types import SimpleNamespace

import pytest

from app import copilot_client


def test_copilot_complete_structured_json_is_parsed():
    result = copilot_client._parse_json_content(
        '{"root_cause":"fixture contact","suggested_solution":"reseat",'
        '"confidence":0.87,"root_cause_category":"fixture",'
        '"evidence_summary":"voltage dropped","next_debug_action":"inspect pins",'
        '"likely_owner":"fixture team","safety_or_escape_risk":"medium",'
        '"needs_more_evidence":false}'
    )

    assert result.confidence == 0.87
    assert result.root_cause_category == "fixture"
    assert result.evidence_summary == "voltage dropped"
    assert result.next_debug_action == "inspect pins"
    assert result.likely_owner == "fixture team"
    assert result.safety_or_escape_risk == "medium"
    assert result.needs_more_evidence is False


def test_copilot_partial_structured_json_omits_unknown_fields():
    result = copilot_client._parse_json_content(
        '{"root_cause":"fixture contact","suggested_solution":"reseat",'
        '"confidence":"unknown","needs_more_evidence":"true"}'
    )

    assert result.confidence is None
    assert result.root_cause_category is None
    assert result.needs_more_evidence is True


def test_copilot_empty_json_fields_return_actionable_fallback():
    result = copilot_client._parse_json_content(
        '{"root_cause":"","suggested_solution":""}',
        "E123",
        "voltage droop",
    )

    assert "No root cause returned" not in result.root_cause
    assert "failure code 'E123'" in result.root_cause
    assert "voltage droop" in result.root_cause
    assert "reanalyze with more failure evidence" in result.suggested_solution


def test_copilot_malformed_content_returns_actionable_fallback_solution():
    result = copilot_client._parse_json_content("", "FFFFFFFF", "Reading 20V failed")

    assert "failure code 'FFFFFFFF'" in result.root_cause
    assert "See root cause above" not in result.suggested_solution
    assert "reanalyze with more failure evidence" in result.suggested_solution
    assert result.needs_more_evidence is True


def test_copilot_stream_raises_on_session_error(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.handler = None

        def on(self, handler):
            self.handler = handler

        async def send(self, prompt):  # noqa: ARG002
            self.handler(SimpleNamespace(
                type=SimpleNamespace(value="session.error"),
                data=SimpleNamespace(message="Session was not created with authentication info"),
            ))

        async def disconnect(self):
            pass

    class FakeClient:
        async def start(self):
            pass

        async def create_session(self, **kwargs):  # noqa: ARG002
            return FakeSession()

        async def stop(self):
            pass

    monkeypatch.setattr(copilot_client, "_create_client", lambda: FakeClient())

    with pytest.raises(RuntimeError, match="authentication info"):
        asyncio.run(copilot_client._stream_once("prompt", "model", "system"))