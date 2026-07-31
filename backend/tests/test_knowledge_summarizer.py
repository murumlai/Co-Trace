"""Tests for the LLM section summarizer (with an injected fake chat backend)."""
from __future__ import annotations

import json

import pytest

from app.knowledge import summarizer as summarizer_mod
from app.knowledge.models import ExtractedSection
from app.knowledge.summarizer import (
    LlmSectionSummarizer,
    ProductKnowledgeError,
    derive_keywords,
    keyword_weights,
    tokenize,
)


def _section(text: str, category: str = "debug_learning") -> ExtractedSection:
    return ExtractedSection(
        section_id="doc1-s000",
        doc_id="doc1",
        product_code="M79060-001",
        category=category,
        heading="Power Rail Faults",
        order=0,
        text=text,
    )


class TestLlmSectionSummarizer:
    def test_summarize_parses_structured_output(self):
        payload = {
            "summary": "12V rail sags under load causing EEPROM3 failures.",
            "known_failures": [
                {
                    "symptom": "12V droop",
                    "root_cause": "undersized cap",
                    "corrective_action": "replace C12",
                    "confidence": "high",
                }
            ],
            "acronyms": [{"acronym": "PDB", "definition": "Power Distribution Board"}],
            "limits": [{"name": "12V rail", "value": "11.4", "unit": "V"}],
            "product_aliases": ["Sedona"],
            "confidence": "high",
        }

        def fake_chat(system_prompt, user_prompt):  # noqa: ARG001
            return json.dumps(payload)

        summarizer = LlmSectionSummarizer(chat=fake_chat, model="fake-mini")
        section = summarizer.summarize(_section("raw text"), "M79060-001_Debug.pdf")

        assert section.summary.startswith("12V rail")
        assert section.known_failures[0].root_cause == "undersized cap"
        assert section.acronyms[0].acronym == "PDB"
        assert section.limits[0].value == "11.4"
        assert section.product_aliases == ["Sedona"]
        assert section.summary_model == "fake-mini"
        assert section.source_filename == "M79060-001_Debug.pdf"

    def test_summarize_handles_code_fenced_json(self):
        def fake_chat(system_prompt, user_prompt):  # noqa: ARG001
            return '```json\n{"summary": "ok", "known_failures": []}\n```'

        summarizer = LlmSectionSummarizer(chat=fake_chat)
        section = summarizer.summarize(_section("x"), "f.pdf")
        assert section.summary == "ok"

    def test_summarize_tolerates_garbage(self):
        def fake_chat(system_prompt, user_prompt):  # noqa: ARG001
            return "not json at all"

        summarizer = LlmSectionSummarizer(chat=fake_chat)
        section = summarizer.summarize(_section("x"), "f.pdf")
        assert section.summary  # falls back to trimmed content


class TestKeywords:
    def test_derive_keywords_deterministic(self):
        def fake_chat(system_prompt, user_prompt):  # noqa: ARG001
            return json.dumps({"summary": "voltage droop on the power rail voltage"})

        section = LlmSectionSummarizer(chat=fake_chat).summarize(_section("x"), "f.pdf")
        kws = derive_keywords(section)
        assert "voltage" in kws
        assert derive_keywords(section) == kws
        weights = keyword_weights(section)
        assert weights["voltage"] >= 2.0

    def test_tokenize_drops_stopwords(self):
        toks = tokenize("the power rail failed with voltage")
        assert "power" in toks
        assert "the" not in toks


class TestDefaultChatRequiresLlm:
    def test_default_chat_raises_when_sdk_unavailable(self, monkeypatch):
        import app.copilot_client as cc

        monkeypatch.setattr(cc, "is_available", lambda: False)
        with pytest.raises(ProductKnowledgeError):
            summarizer_mod._default_chat("sys", "user")
