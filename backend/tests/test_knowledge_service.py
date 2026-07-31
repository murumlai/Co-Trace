"""Tests for the knowledge ingestion service (fake summarizer, real DOCX)."""
from __future__ import annotations

from docx import Document

from app.knowledge import parsing
from app.knowledge.models import ExtractedSection, KnowledgeSection
from app.knowledge.service import KnowledgeIngestionService
from app.knowledge.storage import KnowledgeStore


class FakeSummarizer:
    """Deterministic summarizer that never echoes raw document text."""

    def __init__(self, summary_prefix: str = "SUMMARY") -> None:
        self.prefix = summary_prefix

    def summarize(self, section: ExtractedSection, source_filename: str) -> KnowledgeSection:
        return KnowledgeSection(
            section_id=section.section_id,
            doc_id=section.doc_id,
            product_code=section.product_code,
            category=section.category,
            heading=section.heading,
            order=section.order,
            summary=f"{self.prefix} for {section.heading} voltage rail",
            source_filename=source_filename,
            summary_model="fake",
        )


def _store(tmp_path) -> KnowledgeStore:
    return KnowledgeStore(
        manifest_path=str(tmp_path / "product_knowledge.json"),
        index_path=str(tmp_path / "product_knowledge_index.json"),
        sections_path=str(tmp_path / "product_knowledge_sections.jsonl"),
    )


def _make_docx(tmp_path, name) -> str:
    path = tmp_path / name
    document = Document()
    document.add_heading("Power", level=1)
    document.add_paragraph("RAW_DOC_BODY_MARKER regulated 20V rails and caps.")
    document.add_heading("Comms", level=1)
    document.add_paragraph("RAW_DOC_BODY_MARKER USB link and handshakes.")
    document.save(str(path))
    return str(path)


class TestIngestionService:
    def test_build_writes_pack_and_manifest(self, tmp_path):
        store = _store(tmp_path)
        service = KnowledgeIngestionService(store=store, summarizer=FakeSummarizer())
        doc = parsing.describe_document(_make_docx(tmp_path, "N32828-201_HLD.docx"))
        manifest = service.build([doc])

        assert store.exists()
        codes = {p.product_code for p in manifest.products}
        assert "N32828-201" in codes
        entry = next(p for p in manifest.products if p.product_code == "N32828-201")
        assert entry.section_count == 2
        assert entry.category_counts.get("hld") == 2
        assert entry.knowledge_hash

    def test_no_raw_document_text_in_artifacts(self, tmp_path):
        store = _store(tmp_path)
        service = KnowledgeIngestionService(store=store, summarizer=FakeSummarizer())
        doc = parsing.describe_document(_make_docx(tmp_path, "N32828-201_HLD.docx"))
        service.build([doc])
        raw = open(store.sections_path, encoding="utf-8").read()
        assert "RAW_DOC_BODY_MARKER" not in raw

    def test_knowledge_hash_changes_with_summary(self, tmp_path):
        store = _store(tmp_path)
        doc = parsing.describe_document(_make_docx(tmp_path, "N32828-201_HLD.docx"))

        first = KnowledgeIngestionService(store=store, summarizer=FakeSummarizer("A")).build([doc])
        hash_a = first.product_hash("N32828-201")

        second = KnowledgeIngestionService(store=store, summarizer=FakeSummarizer("B")).build([doc])
        hash_b = second.product_hash("N32828-201")

        assert hash_a and hash_b
        assert hash_a != hash_b

    def test_index_has_token_weights(self, tmp_path):
        store = _store(tmp_path)
        service = KnowledgeIngestionService(store=store, summarizer=FakeSummarizer())
        doc = parsing.describe_document(_make_docx(tmp_path, "N32828-201_HLD.docx"))
        service.build([doc])
        index = store.load_index()
        entries = index.by_product["N32828-201"]
        assert entries
        assert any(e.token_weights for e in entries)
        assert all(e.byte_length > 0 for e in entries)
