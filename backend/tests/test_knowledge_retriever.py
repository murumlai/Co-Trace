"""Tests for the lexical product-knowledge retriever."""
from __future__ import annotations

import pytest

from app.config import settings
from app.knowledge import summarizer as summarizer_mod
from app.knowledge.models import (
    CATEGORY_PRIORITY,
    AcronymDefinition,
    KnowledgeIndex,
    KnowledgeManifest,
    KnowledgeSection,
    KnownFailureEntry,
    LimitSpecRecord,
    ProductManifestEntry,
    SectionIndexEntry,
)
from app.knowledge.retriever import LexicalKnowledgeRetriever
from app.knowledge.storage import KnowledgeStore
from app.models import UnitRecord


def _store(tmp_path) -> KnowledgeStore:
    return KnowledgeStore(
        manifest_path=str(tmp_path / "product_knowledge.json"),
        index_path=str(tmp_path / "product_knowledge_index.json"),
        sections_path=str(tmp_path / "product_knowledge_sections.jsonl"),
    )


def _write(store, sections):
    by_product: dict[str, list[SectionIndexEntry]] = {}
    for s in sections:
        by_product.setdefault(s.product_code or "UNKNOWN", []).append(
            SectionIndexEntry(
                section_id=s.section_id,
                product_code=s.product_code,
                category=s.category,
                heading=s.heading,
                priority=CATEGORY_PRIORITY[s.category],
                token_weights=summarizer_mod.keyword_weights(s),
            )
        )
    index = KnowledgeIndex(by_product=by_product)
    manifest = KnowledgeManifest(
        products=[
            ProductManifestEntry(product_code=code, section_count=len(v),
                                 knowledge_hash=f"h_{code}")
            for code, v in by_product.items()
        ],
        global_hash="g",
    )
    store.write_pack(manifest, index, sections)


def _sections() -> list[KnowledgeSection]:
    return [
        KnowledgeSection(
            section_id="A-s000", doc_id="A", product_code="M79060-001",
            category="debug_learning", heading="Power Faults",
            summary="voltage droop on the rail during eeprom flashing",
            known_failures=[KnownFailureEntry(symptom="voltage droop", root_cause="cap")],
            acronyms=[AcronymDefinition(acronym="PDB", definition="Power Distribution Board")],
            source_filename="M79060-001_Debug.pdf",
        ),
        KnowledgeSection(
            section_id="A-s001", doc_id="A", product_code="M79060-001",
            category="hld", heading="Power Architecture",
            summary="voltage regulation architecture and rails",
            limits=[LimitSpecRecord(name="12V rail", value="11.4", unit="V")],
            source_filename="M79060-001_HLD.pdf",
        ),
        KnowledgeSection(
            section_id="B-s000", doc_id="B", product_code="M13983-700",
            category="product_overview", heading="Card",
            summary="sedona usb test card overview and connectors",
            source_filename="M13983-700_Card.pdf",
        ),
    ]


def _rec(product_code, failing_step=None, error_code=None, error_message=None) -> UnitRecord:
    return UnitRecord(
        unit_id="u1", result="FAIL", product_code=product_code,
        failing_step=failing_step, error_code=error_code, error_message=error_message,
        run_folder="u1",
    )


class TestRetriever:
    def test_debug_learning_ranks_first_on_symptom_overlap(self, tmp_path):
        store = _store(tmp_path)
        _write(store, _sections())
        retriever = LexicalKnowledgeRetriever(store)
        ctx = retriever.retrieve(_rec("M79060-001", error_message="voltage droop"))
        assert ctx.match_status == "matched"
        assert ctx.matched is True
        assert ctx.matches[0].category == "debug_learning"
        assert "A-s000" in ctx.matched_section_ids

    def test_product_partitioning(self, tmp_path):
        store = _store(tmp_path)
        _write(store, _sections())
        retriever = LexicalKnowledgeRetriever(store)
        ctx = retriever.retrieve(_rec("M13983-700", error_message="voltage droop"))
        # Query tokens don't hit the overview section, so it's a fallback match,
        # but every returned section must still belong to M13983-700.
        assert all(m.product_code == "M13983-700" for m in ctx.matches)

    def test_acronym_matching(self, tmp_path):
        store = _store(tmp_path)
        _write(store, _sections())
        retriever = LexicalKnowledgeRetriever(store)
        ctx = retriever.retrieve(_rec("M79060-001", error_message="PDB fault"))
        assert ctx.match_status == "matched"
        assert any(m.section_id == "A-s000" for m in ctx.matches)

    def test_limit_matching(self, tmp_path):
        store = _store(tmp_path)
        _write(store, _sections())
        retriever = LexicalKnowledgeRetriever(store)
        ctx = retriever.retrieve(_rec("M79060-001", failing_step="12V rail check"))
        assert ctx.matched
        assert any(m.section_id == "A-s001" for m in ctx.matches)

    def test_byte_offset_read_returns_summary(self, tmp_path):
        store = _store(tmp_path)
        _write(store, _sections())
        retriever = LexicalKnowledgeRetriever(store)
        ctx = retriever.retrieve(_rec("M79060-001", error_message="voltage droop"))
        top = ctx.matches[0]
        assert "voltage droop" in top.summary
        assert ctx.context_text

    def test_no_product_code(self, tmp_path):
        store = _store(tmp_path)
        _write(store, _sections())
        retriever = LexicalKnowledgeRetriever(store)
        ctx = retriever.retrieve(_rec(None, error_message="voltage"))
        assert ctx.match_status == "no_product_code"

    def test_no_product_knowledge(self, tmp_path):
        store = _store(tmp_path)
        _write(store, _sections())
        retriever = LexicalKnowledgeRetriever(store)
        ctx = retriever.retrieve(_rec("ZZZZ-999", error_message="voltage"))
        assert ctx.match_status == "no_product_knowledge"

    def test_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "PRODUCT_KNOWLEDGE_ENABLED", False)
        store = _store(tmp_path)
        _write(store, _sections())
        retriever = LexicalKnowledgeRetriever(store)
        ctx = retriever.retrieve(_rec("M79060-001", error_message="voltage"))
        assert ctx.match_status == "disabled"

    def test_knowledge_hash_reported(self, tmp_path):
        store = _store(tmp_path)
        _write(store, _sections())
        retriever = LexicalKnowledgeRetriever(store)
        ctx = retriever.retrieve(_rec("M79060-001", error_message="voltage droop"))
        assert ctx.knowledge_hash == "h_M79060-001"
