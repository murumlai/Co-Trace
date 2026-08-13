"""Pydantic schemas for the product-knowledge pack.

Two families of models live here:

* Curated, at-rest records written into the generated artifacts
  (``KnowledgeSection``, ``KnowledgeManifest``, ``KnowledgeIndex``). These NEVER
  contain raw extracted document text — only curated summaries and metadata.
* Runtime/transient models used while parsing and retrieving
  (``SourceDocument``, ``ExtractedSection``, ``RetrievalMatch``,
  ``KnowledgeContext``). ``ExtractedSection.text`` holds raw text but is only
  used in-process to drive summarization; it is never persisted.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

DocumentCategory = Literal["hld", "debug_learning", "product_overview", "rfc_knowledge", "uncategorized"]

# Higher number == retrieved first when scores tie. RFC knowledge directly maps
# failure signatures to RFC guidance, so it ranks above debug_learning.
CATEGORY_PRIORITY: dict[str, int] = {
    "rfc_knowledge": 4,
    "debug_learning": 3,
    "hld": 2,
    "product_overview": 1,
    "uncategorized": 0,
}


# ---------------------------------------------------------------------------
# Curated sub-records (safe to persist)
# ---------------------------------------------------------------------------

class RfcReference(BaseModel):
    """One RFC ID and associated notes from an RFC workbook row."""

    rfc_id: str
    notes: Optional[str] = None
    failed_test_name: Optional[str] = None
    error_message_or_finding: Optional[str] = None


class KnownFailureEntry(BaseModel):
    """One known symptom -> root cause -> fix learned from a debug-support doc."""

    symptom: Optional[str] = None
    log_signature: Optional[str] = None
    failing_step: Optional[str] = None
    root_cause: Optional[str] = None
    corrective_action: Optional[str] = None
    station_check: Optional[str] = None
    confidence: Optional[str] = None
    applies_to: Optional[str] = None
    rfc_references: list["RfcReference"] = Field(default_factory=list)


class AcronymDefinition(BaseModel):
    acronym: str
    definition: str


class LimitSpecRecord(BaseModel):
    name: str
    value: str
    unit: Optional[str] = None
    context: Optional[str] = None


# ---------------------------------------------------------------------------
# Transient parsing models (NOT persisted with raw text)
# ---------------------------------------------------------------------------

class SourceDocument(BaseModel):
    """A supporting product document discovered on disk."""

    doc_id: str
    path: str
    filename: str
    product_code: Optional[str] = None
    product_family_code: Optional[str] = None
    category: DocumentCategory = "uncategorized"
    content_hash: str = ""
    size_bytes: int = 0
    source_root: str = ""
    warnings: list[str] = Field(default_factory=list)


class ExtractedSection(BaseModel):
    """A parsed section. ``text`` is transient — summarized then discarded."""

    section_id: str
    doc_id: str
    product_code: Optional[str] = None
    category: DocumentCategory = "uncategorized"
    heading: Optional[str] = None
    order: int = 0
    text: str = ""

    @property
    def char_count(self) -> int:
        return len(self.text)


# ---------------------------------------------------------------------------
# Curated section record (one JSONL line each — no raw text)
# ---------------------------------------------------------------------------

class KnowledgeSection(BaseModel):
    """Curated section-summary record. One per line in the sections JSONL."""

    section_id: str
    doc_id: str
    product_code: Optional[str] = None
    product_family_code: Optional[str] = None
    category: DocumentCategory = "uncategorized"
    heading: Optional[str] = None
    order: int = 0
    summary: str = ""
    known_failures: list[KnownFailureEntry] = Field(default_factory=list)
    acronyms: list[AcronymDefinition] = Field(default_factory=list)
    limits: list[LimitSpecRecord] = Field(default_factory=list)
    product_aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    source_filename: str = ""
    summary_model: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Manifest models (product_knowledge.json)
# ---------------------------------------------------------------------------

class SourceDocumentMeta(BaseModel):
    doc_id: str
    filename: str
    product_code: Optional[str] = None
    product_family_code: Optional[str] = None
    category: DocumentCategory = "uncategorized"
    content_hash: str = ""
    size_bytes: int = 0
    section_count: int = 0
    source_root: str = ""
    warnings: list[str] = Field(default_factory=list)


class ProductManifestEntry(BaseModel):
    product_code: str
    document_count: int = 0
    section_count: int = 0
    category_counts: dict[str, int] = Field(default_factory=dict)
    knowledge_hash: str = ""


class KnowledgeManifest(BaseModel):
    schema_version: int = 1
    generated_at: str = ""
    summary_model: Optional[str] = None
    global_hash: str = ""
    products: list[ProductManifestEntry] = Field(default_factory=list)
    documents: list[SourceDocumentMeta] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def product_hash(self, product_code: str | None) -> str:
        if not product_code:
            return self.global_hash
        for entry in self.products:
            if entry.product_code == product_code:
                return entry.knowledge_hash
        return ""


# ---------------------------------------------------------------------------
# Index models (product_knowledge_index.json) — byte-offset addressable
# ---------------------------------------------------------------------------

class SectionIndexEntry(BaseModel):
    section_id: str
    product_code: Optional[str] = None
    product_family_code: Optional[str] = None
    category: DocumentCategory = "uncategorized"
    heading: Optional[str] = None
    priority: int = 0
    token_weights: dict[str, float] = Field(default_factory=dict)
    byte_offset: int = 0
    byte_length: int = 0


class KnowledgeIndex(BaseModel):
    schema_version: int = 1
    generated_at: str = ""
    # product_code -> its section index entries.
    by_product: dict[str, list[SectionIndexEntry]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Retrieval result models (runtime)
# ---------------------------------------------------------------------------

class RetrievalMatch(BaseModel):
    section_id: str
    doc_id: str
    product_code: Optional[str] = None
    product_family_code: Optional[str] = None
    category: DocumentCategory = "uncategorized"
    heading: Optional[str] = None
    summary: str = ""
    score: float = 0.0
    known_failures: list[KnownFailureEntry] = Field(default_factory=list)
    acronyms: list[AcronymDefinition] = Field(default_factory=list)
    limits: list[LimitSpecRecord] = Field(default_factory=list)
    source_filename: str = ""


MatchStatus = Literal[
    "matched", "no_match", "no_product_knowledge", "disabled", "no_product_code"
]


class KnowledgeContext(BaseModel):
    """Metadata + assembled prompt context returned by the retriever."""

    product_code: Optional[str] = None
    knowledge_hash: str = ""
    match_status: MatchStatus = "disabled"
    matched: bool = False
    matched_section_ids: list[str] = Field(default_factory=list)
    matched_categories: list[str] = Field(default_factory=list)
    matches: list[RetrievalMatch] = Field(default_factory=list)
    # Curated summaries assembled for the LLM prompt (never raw doc text).
    context_text: str = ""
    debug_learning_text: str = ""
