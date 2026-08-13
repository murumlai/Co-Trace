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


class TestRfcSummarizerOutput:
    def test_rfc_empty_model_output_falls_back_to_structured_row_summary(self):
        rfc_section = ExtractedSection(
            section_id="rfc-s-fallback",
            doc_id="rfc-fallback",
            product_code="N32828-201",
            category="rfc_knowledge",
            heading="Functional Test RFC \u2014 12V Standby, 3.3 and PWR_OK Test",
            order=0,
            text=(
                "failed_test_name: 12V Standby, 3.3 and PWR_OK Test\n"
                "error_message_or_finding: 12V Standby, 3.3 and PWR_OK Test Failed\n"
                "rfc_entries:\n"
                "- RFC 1: Make sure cables at LTIB is connected\n"
                "- RFC 2: Make sure Ambery is configured correctly"
            ),
        )

        section = LlmSectionSummarizer(chat=lambda _system, _user: "").summarize(
            rfc_section, "N32828-201_RFC_.xlsx"
        )

        assert section.summary_model == "structured-rfc-parser"
        assert "12V Standby" in section.summary
        assert section.known_failures
        refs = section.known_failures[0].rfc_references
        assert [r.rfc_id for r in refs] == ["RFC 1", "RFC 2"]
        assert refs[0].notes == "Make sure cables at LTIB is connected"

    def test_rfc_references_coerced_from_known_failures(self):
        payload = {
            "summary": "POWER_TEST_01 fails; see RFC-1234.",
            "known_failures": [
                {
                    "symptom": "12V droop",
                    "failing_step": "POWER_TEST_01",
                    "rfc_references": [
                        {
                            "rfc_id": "RFC-1234",
                            "notes": "Replace cap C12",
                            "failed_test_name": "POWER_TEST_01",
                            "error_message_or_finding": "12V droop at load",
                        }
                    ],
                }
            ],
            "acronyms": [],
            "limits": [],
            "product_aliases": [],
            "confidence": "high",
        }

        def fake_chat(system_prompt, user_prompt):  # noqa: ARG001
            return json.dumps(payload)

        rfc_section = ExtractedSection(
            section_id="rfc-s000",
            doc_id="rfc1",
            product_code="N32828-201",
            category="rfc_knowledge",
            heading="RFC Table \u2014 POWER_TEST_01",
            order=0,
            text="failed_test_name: POWER_TEST_01\nrfcs: RFC-1234",
        )
        summarizer = LlmSectionSummarizer(chat=fake_chat, model="fake-mini")
        section = summarizer.summarize(rfc_section, "N32828_RFC.xlsx")
        assert section.known_failures
        kf = section.known_failures[0]
        assert kf.rfc_references
        ref = kf.rfc_references[0]
        assert ref.rfc_id == "RFC-1234"
        assert ref.notes == "Replace cap C12"
        assert ref.failed_test_name == "POWER_TEST_01"

    def test_rfc_tokens_indexed_as_keywords(self):
        payload = {
            "summary": "USB_ENUM_FAIL covered by RFC-0001.",
            "known_failures": [
                {
                    "symptom": "USB not detected",
                    "failing_step": "USB_ENUM_FAIL",
                    "rfc_references": [
                        {"rfc_id": "RFC-0001", "notes": "reseat connector", "failed_test_name": "USB_ENUM_FAIL"}
                    ],
                }
            ],
            "acronyms": [],
            "limits": [],
            "product_aliases": [],
            "confidence": "medium",
        }

        def fake_chat(system_prompt, user_prompt):  # noqa: ARG001
            return json.dumps(payload)

        rfc_section = ExtractedSection(
            section_id="rfc-s001",
            doc_id="rfc2",
            product_code="N32828",
            category="rfc_knowledge",
            heading="RFC Table",
            order=0,
            text="failed_test_name: USB_ENUM_FAIL\nrfcs: RFC-0001",
        )
        section = LlmSectionSummarizer(chat=fake_chat).summarize(rfc_section, "N32828_RFC.xlsx")
        kws = derive_keywords(section)
        weights = keyword_weights(section)
        # RFC ID tokens should be present
        assert any("RFC" in k.upper() or "rfc" in k for k in kws)
        assert any("USB" in k.upper() for k in kws)
        assert any(w > 0 for w in weights.values())


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
