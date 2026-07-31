"""Tests for the knowledge pack storage (byte-offset JSONL + manifest/index)."""
from __future__ import annotations

from app.knowledge import summarizer as summarizer_mod
from app.knowledge.models import (
    CATEGORY_PRIORITY,
    KnowledgeIndex,
    KnowledgeManifest,
    KnowledgeSection,
    KnownFailureEntry,
    ProductManifestEntry,
    SectionIndexEntry,
)
from app.knowledge.storage import KnowledgeStore


def _store(tmp_path) -> KnowledgeStore:
    return KnowledgeStore(
        manifest_path=str(tmp_path / "product_knowledge.json"),
        index_path=str(tmp_path / "product_knowledge_index.json"),
        sections_path=str(tmp_path / "product_knowledge_sections.jsonl"),
    )


def _sections() -> list[KnowledgeSection]:
    return [
        KnowledgeSection(
            section_id="A-s000",
            doc_id="A",
            product_code="M79060-001",
            category="debug_learning",
            heading="Power",
            order=0,
            summary="12V rail droop causes EEPROM3 failures",
            known_failures=[KnownFailureEntry(symptom="droop", root_cause="cap")],
            source_filename="M79060-001_Debug.pdf",
        ),
        KnowledgeSection(
            section_id="B-s000",
            doc_id="B",
            product_code="M13983-700",
            category="product_overview",
            heading="Card",
            order=0,
            summary="Sedona USB test card overview",
            source_filename="M13983-700_Card.pdf",
        ),
    ]


def _pack(sections):
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
            ProductManifestEntry(product_code=code, section_count=len(entries),
                                 knowledge_hash=f"h_{code}")
            for code, entries in by_product.items()
        ],
        global_hash="global",
    )
    return manifest, index


class TestKnowledgeStore:
    def test_read_section_uses_byte_offsets(self, tmp_path):
        store = _store(tmp_path)
        sections = _sections()
        manifest, index = _pack(sections)
        store.write_pack(manifest, index, sections)

        entry_a = index.by_product["M79060-001"][0]
        entry_b = index.by_product["M13983-700"][0]
        assert entry_a.byte_length > 0
        read_a = store.read_section(entry_a)
        read_b = store.read_section(entry_b)
        assert read_a.section_id == "A-s000"
        assert read_a.summary.startswith("12V rail droop")
        assert read_b.section_id == "B-s000"

    def test_iter_sections_roundtrip(self, tmp_path):
        store = _store(tmp_path)
        sections = _sections()
        manifest, index = _pack(sections)
        store.write_pack(manifest, index, sections)
        ids = {s.section_id for s in store.iter_sections()}
        assert ids == {"A-s000", "B-s000"}

    def test_manifest_and_index_load(self, tmp_path):
        store = _store(tmp_path)
        sections = _sections()
        manifest, index = _pack(sections)
        store.write_pack(manifest, index, sections)
        loaded_manifest = store.load_manifest()
        loaded_index = store.load_index()
        assert loaded_manifest.product_hash("M79060-001") == "h_M79060-001"
        assert "M13983-700" in loaded_index.by_product

    def test_delete_pack_removes_files(self, tmp_path):
        store = _store(tmp_path)
        sections = _sections()
        manifest, index = _pack(sections)
        store.write_pack(manifest, index, sections)
        assert store.exists()
        store.delete_pack()
        assert not store.exists()

    def test_no_raw_document_text_persisted(self, tmp_path):
        """KnowledgeSection has no raw-text field; the JSONL must not carry it."""
        store = _store(tmp_path)
        sections = _sections()
        manifest, index = _pack(sections)
        store.write_pack(manifest, index, sections)
        raw = open(store.sections_path, encoding="utf-8").read()
        assert "text" not in KnowledgeSection.model_fields
        assert "RAW_DOC_BODY" not in raw
