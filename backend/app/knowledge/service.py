"""Knowledge-pack ingestion: scan -> parse -> summarize -> write artifacts.

The service is deliberately thin over the parsing/summarizer/storage modules so
it can be driven from either the build script or the Knowledge UI routes.
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from ..config import settings
from . import parsing, summarizer as summarizer_mod
from .models import (
    CATEGORY_PRIORITY,
    KnowledgeIndex,
    KnowledgeManifest,
    KnowledgeSection,
    ProductManifestEntry,
    SectionIndexEntry,
    SourceDocument,
    SourceDocumentMeta,
)
from .storage import KnowledgeStore
from .summarizer import LlmSectionSummarizer, ProductKnowledgeError

log = logging.getLogger("cotrace.knowledge")

IngestionProgress = Callable[[int, int, str], None]

_SCHEMA_VERSION = 1


class KnowledgeIngestionService:
    """Builds the repo-root knowledge pack from supporting product documents."""

    def __init__(
        self,
        store: KnowledgeStore | None = None,
        summarizer: LlmSectionSummarizer | None = None,
    ) -> None:
        self._store = store or KnowledgeStore()
        self._summarizer = summarizer or LlmSectionSummarizer()

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    def rebuild(self, progress: IngestionProgress | None = None) -> KnowledgeManifest:
        """Rebuild the pack from the configured source directories."""
        docs = parsing.scan_source_documents()
        return self.build(docs, progress=progress)

    def build(
        self,
        docs: list[SourceDocument],
        progress: IngestionProgress | None = None,
    ) -> KnowledgeManifest:
        sections: list[KnowledgeSection] = []
        doc_metas: list[SourceDocumentMeta] = []
        warnings: list[str] = []
        total = len(docs)
        if progress:
            progress(0, total, f"Ingesting {total} document(s)")

        for i, doc in enumerate(docs, start=1):
            meta = SourceDocumentMeta(
                doc_id=doc.doc_id,
                filename=doc.filename,
                product_code=doc.product_code,
                category=doc.category,
                size_bytes=doc.size_bytes,
                source_root=doc.source_root,
                warnings=list(doc.warnings),
            )
            try:
                content_hash, parsed_sections = parsing.parse_document(doc)
            except ProductKnowledgeError:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad doc must not kill the build
                msg = f"{doc.filename}: parse failed ({type(exc).__name__}: {exc})."
                log.warning(msg)
                meta.warnings.append(msg)
                warnings.append(msg)
                doc_metas.append(meta)
                if progress:
                    progress(i, total, f"Skipped {doc.filename}")
                continue

            meta.content_hash = content_hash
            if progress:
                progress(i - 1, total, f"Summarizing {doc.filename} ({len(parsed_sections)} sections)")
            doc_sections = self._summarize_sections(doc, parsed_sections, warnings, meta, progress)
            meta.section_count = len(doc_sections)
            sections.extend(doc_sections)
            doc_metas.append(meta)
            if progress:
                progress(i, total, f"Ingested {doc.filename}")

        manifest = self._build_manifest(doc_metas, sections, warnings)
        index = self._build_index(sections)
        self._store.write_pack(manifest, index, sections)
        if progress:
            progress(total, total, f"Wrote knowledge pack ({len(sections)} sections)")
        log.info(
            "Knowledge ingestion complete: %s docs, %s sections, %s products.",
            len(doc_metas), len(sections), len(manifest.products),
        )
        return manifest

    def remove_document(self, doc_id: str) -> tuple[KnowledgeManifest | None, bool]:
        """Prune one document and its sections from the existing pack.

        Remaining sections are already curated, so this needs no LLM and works
        even when no summarization backend is available. Returns the rewritten
        manifest and whether anything was removed.
        """
        manifest = self._store.load_manifest()
        if manifest is None:
            return None, False
        remaining_metas = [m for m in manifest.documents if m.doc_id != doc_id]
        if len(remaining_metas) == len(manifest.documents):
            return manifest, False
        remaining_sections = [s for s in self._store.iter_sections() if s.doc_id != doc_id]
        warnings = [w for meta in remaining_metas for w in meta.warnings]
        new_manifest = self._build_manifest(remaining_metas, remaining_sections, warnings)
        index = self._build_index(remaining_sections)
        self._store.write_pack(new_manifest, index, remaining_sections)
        log.info("Pruned document %s from knowledge pack.", doc_id)
        return new_manifest, True

    # --- internals -----------------------------------------------------------

    def _summarize_sections(
        self,
        doc: SourceDocument,
        parsed_sections: list,
        warnings: list[str],
        meta: SourceDocumentMeta,
        progress: IngestionProgress | None = None,
    ) -> list[KnowledgeSection]:
        out: list[KnowledgeSection] = []
        total = len(parsed_sections)
        for i, section in enumerate(parsed_sections, start=1):
            try:
                curated = self._summarizer.summarize(section, doc.filename)
            except ProductKnowledgeError:
                raise
            except Exception as exc:  # noqa: BLE001 - skip a bad section, keep going
                msg = f"{doc.filename} [{section.section_id}]: summarize failed ({type(exc).__name__})."
                log.warning(msg)
                warnings.append(msg)
                meta.warnings.append(msg)
                continue
            curated.keywords = summarizer_mod.derive_keywords(curated)
            out.append(curated)
            if progress:
                progress(i, total, f"Summarized {doc.filename} section {i}/{total}")
        return out

    def _build_manifest(
        self,
        doc_metas: list[SourceDocumentMeta],
        sections: list[KnowledgeSection],
        warnings: list[str],
    ) -> KnowledgeManifest:
        by_product: dict[str, list[KnowledgeSection]] = {}
        for section in sections:
            by_product.setdefault(section.product_code or "UNKNOWN", []).append(section)

        docs_by_product: dict[str, set[str]] = {}
        for meta in doc_metas:
            docs_by_product.setdefault(meta.product_code or "UNKNOWN", set()).add(meta.doc_id)

        products: list[ProductManifestEntry] = []
        for product_code in sorted(set(by_product) | set(docs_by_product)):
            prod_sections = by_product.get(product_code, [])
            category_counts: dict[str, int] = {}
            for section in prod_sections:
                category_counts[section.category] = category_counts.get(section.category, 0) + 1
            products.append(
                ProductManifestEntry(
                    product_code=product_code,
                    document_count=len(docs_by_product.get(product_code, set())),
                    section_count=len(prod_sections),
                    category_counts=category_counts,
                    knowledge_hash=_product_hash(prod_sections),
                )
            )

        category_counts_global: dict[str, int] = {}
        for section in sections:
            category_counts_global[section.category] = (
                category_counts_global.get(section.category, 0) + 1
            )

        return KnowledgeManifest(
            schema_version=_SCHEMA_VERSION,
            generated_at=_now(),
            summary_model=settings.PRODUCT_KNOWLEDGE_SUMMARY_MODEL,
            global_hash=_global_hash(products),
            products=products,
            documents=doc_metas,
            category_counts=category_counts_global,
            warnings=warnings,
        )

    def _build_index(self, sections: list[KnowledgeSection]) -> KnowledgeIndex:
        by_product: dict[str, list[SectionIndexEntry]] = {}
        for section in sections:
            key = section.product_code or "UNKNOWN"
            by_product.setdefault(key, []).append(
                SectionIndexEntry(
                    section_id=section.section_id,
                    product_code=section.product_code,
                    category=section.category,
                    heading=section.heading,
                    priority=CATEGORY_PRIORITY.get(section.category, 0),
                    token_weights=summarizer_mod.keyword_weights(section),
                )
            )
        return KnowledgeIndex(
            schema_version=_SCHEMA_VERSION, generated_at=_now(), by_product=by_product
        )


def _product_hash(sections: list[KnowledgeSection]) -> str:
    if not sections:
        return ""
    canonical = "\n".join(
        s.model_dump_json(exclude_none=True)
        for s in sorted(sections, key=lambda s: s.section_id)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _global_hash(products: list[ProductManifestEntry]) -> str:
    basis = "|".join(
        f"{p.product_code}:{p.knowledge_hash}"
        for p in sorted(products, key=lambda p: p.product_code)
    )
    basis = f"{settings.PRODUCT_KNOWLEDGE_SUMMARY_MODEL}|{basis}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
