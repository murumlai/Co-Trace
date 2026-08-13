"""Deterministic lexical retrieval over the product-knowledge pack.

Retrieval is intentionally lightweight (no embeddings) for v1: it joins on the
required ``PRODUCTCODE`` key, scores curated sections by token overlap with the
failure's ``failing_step`` / ``error_code`` / ``error_message``, and boosts
``debug_learning`` sections when symptom tokens overlap. Embeddings can later
slot in behind the same retriever interface.

Only matched sections are read from the JSONL (via recorded byte offsets), so
no whole document is ever loaded at diagnosis time.
"""
from __future__ import annotations

import logging
import os
import threading

from ..config import settings
from ..models import UnitRecord
from . import summarizer as summarizer_mod
from .models import (
    KnowledgeContext,
    KnowledgeIndex,
    KnowledgeManifest,
    RetrievalMatch,
    SectionIndexEntry,
)
from .storage import KnowledgeStore

log = logging.getLogger("cotrace.knowledge")

_RFC_KNOWLEDGE_BOOST = 2.0    # multiplier on token overlap for rfc_knowledge
_DEBUG_LEARNING_BOOST = 1.5   # multiplier on token overlap for debug_learning
_PRIORITY_WEIGHT = 0.1        # small additive tiebreak by category priority
_MAX_FALLBACK_SECTIONS = 2    # product context when no lexical overlap


class LexicalKnowledgeRetriever:
    """Loads the pack (cached by mtime) and retrieves per-failure context."""

    def __init__(self, store: KnowledgeStore | None = None) -> None:
        self._store = store or KnowledgeStore()
        self._lock = threading.Lock()
        self._index: KnowledgeIndex | None = None
        self._manifest: KnowledgeManifest | None = None
        self._loaded_signature: tuple[float, float] | None = None

    # --- public API (ProductKnowledgeRetriever contract) --------------------

    def retrieve(self, record: UnitRecord) -> KnowledgeContext:
        if not settings.PRODUCT_KNOWLEDGE_ENABLED:
            return KnowledgeContext(product_code=record.product_code, match_status="disabled")

        product_code = record.product_code
        if not product_code:
            return KnowledgeContext(match_status="no_product_code")

        index, manifest = self._ensure_loaded()
        if index is None or manifest is None:
            return KnowledgeContext(product_code=product_code, match_status="no_product_knowledge")

        # Build the candidate entry list: exact product-code match first,
        # then RFC sections from a family-level workbook as fallback.
        entries = list(index.by_product.get(product_code) or [])
        family_code = _family_code_for(product_code)
        if family_code and family_code != product_code:
            for entry in index.by_product.get(family_code) or []:
                if entry.category == "rfc_knowledge" and entry not in entries:
                    entries.append(entry)
            # Also check all other keys whose product_family_code matches.
            for key, key_entries in index.by_product.items():
                if key == product_code or key == family_code:
                    continue
                for entry in key_entries:
                    if (
                        entry.category == "rfc_knowledge"
                        and entry.product_family_code == family_code
                        and entry not in entries
                    ):
                        entries.append(entry)

        if not entries:
            return KnowledgeContext(
                product_code=product_code,
                knowledge_hash=manifest.product_hash(product_code),
                match_status="no_product_knowledge",
            )

        knowledge_hash = manifest.product_hash(product_code)
        query = summarizer_mod.tokenize(
            " ".join(
                v for v in (record.failing_step, record.error_code, record.error_message) if v
            )
        )
        scored, fallback = self._score(entries, query)

        if scored:
            top = scored[: settings.PRODUCT_KNOWLEDGE_TOP_K]
            matches = self._read_matches(top)
            return self._context(product_code, knowledge_hash, matches, matched=True)

        # No lexical overlap: still surface a little product context.
        top = fallback[:_MAX_FALLBACK_SECTIONS]
        matches = self._read_matches(top)
        ctx = self._context(product_code, knowledge_hash, matches, matched=False)
        ctx.match_status = "no_match"
        ctx.matched_section_ids = []
        ctx.matched_categories = []
        return ctx

    # --- scoring -------------------------------------------------------------

    def _score(
        self, entries: list[SectionIndexEntry], query: set[str]
    ) -> tuple[list[tuple[float, SectionIndexEntry]], list[tuple[float, SectionIndexEntry]]]:
        scored: list[tuple[float, SectionIndexEntry]] = []
        fallback: list[tuple[float, SectionIndexEntry]] = []
        for entry in entries:
            overlap = sum(entry.token_weights.get(tok, 0.0) for tok in query)
            priority_bonus = _PRIORITY_WEIGHT * entry.priority
            if overlap > 0:
                score = overlap
                if entry.category == "rfc_knowledge":
                    score *= _RFC_KNOWLEDGE_BOOST
                elif entry.category == "debug_learning":
                    score *= _DEBUG_LEARNING_BOOST
                score += priority_bonus
                scored.append((score, entry))
            else:
                fallback.append((float(entry.priority), entry))
        scored.sort(key=lambda pair: (pair[0], pair[1].priority), reverse=True)
        fallback.sort(key=lambda pair: pair[0], reverse=True)
        return scored, fallback

    def _read_matches(
        self, scored: list[tuple[float, SectionIndexEntry]]
    ) -> list[RetrievalMatch]:
        matches: list[RetrievalMatch] = []
        for score, entry in scored:
            section = self._store.read_section(entry)
            if section is None:
                continue
            matches.append(
                RetrievalMatch(
                    section_id=section.section_id,
                    doc_id=section.doc_id,
                    product_code=section.product_code,
                    product_family_code=section.product_family_code,
                    category=section.category,
                    heading=section.heading,
                    summary=section.summary,
                    score=round(score, 4),
                    known_failures=section.known_failures,
                    acronyms=section.acronyms,
                    limits=section.limits,
                    source_filename=section.source_filename,
                )
            )
        return matches

    def _context(
        self,
        product_code: str,
        knowledge_hash: str,
        matches: list[RetrievalMatch],
        matched: bool,
    ) -> KnowledgeContext:
        context_text, debug_text = _assemble_context(matches)
        return KnowledgeContext(
            product_code=product_code,
            knowledge_hash=knowledge_hash,
            match_status="matched" if matched else "no_match",
            matched=matched and bool(matches),
            matched_section_ids=[m.section_id for m in matches],
            matched_categories=sorted({m.category for m in matches}),
            matches=matches,
            context_text=context_text,
            debug_learning_text=debug_text,
        )

    # --- pack loading (mtime-cached) ----------------------------------------

    def _ensure_loaded(self) -> tuple[KnowledgeIndex | None, KnowledgeManifest | None]:
        with self._lock:
            signature = self._pack_signature()
            if signature != self._loaded_signature:
                self._index = self._store.load_index()
                self._manifest = self._store.load_manifest()
                self._loaded_signature = signature
            return self._index, self._manifest

    def _pack_signature(self) -> tuple[float, float]:
        return (_mtime(self._store.index_path), _mtime(self._store.manifest_path))

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_signature = None


def _family_code_for(product_code: str) -> str | None:
    """Return the base family code for a revisioned product code.

    ``N32828-201`` -> ``N32828``; ``N32828`` -> ``N32828``.
    """
    from .parsing import extract_product_family_code  # noqa: PLC0415
    return extract_product_family_code(product_code)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _assemble_context(matches: list[RetrievalMatch]) -> tuple[str, str]:
    """Build the prompt context (curated summaries only) within the char budget.

    Returns ``(all_context, debug_learning_only)``. Debug-learning and
    RFC-knowledge known-failure text is surfaced separately so prompts can
    present it as higher-priority historical evidence.
    """
    budget = settings.PRODUCT_KNOWLEDGE_MAX_CONTEXT_CHARS
    blocks: list[str] = []
    debug_blocks: list[str] = []
    used = 0
    # RFC + debug-learning first so they survive truncation.
    ordered = sorted(
        matches,
        key=lambda m: 0 if m.category in ("rfc_knowledge", "debug_learning") else 1,
    )
    for match in ordered:
        block = _format_match(match)
        if used + len(block) > budget and blocks:
            break
        blocks.append(block)
        used += len(block)
        if match.category in ("debug_learning", "rfc_knowledge"):
            debug_blocks.append(block)
    return "\n\n".join(blocks), "\n\n".join(debug_blocks)


def _format_match(match: RetrievalMatch) -> str:
    lines = [
        f"[{match.category}] {match.heading or '(section)'} "
        f"\u2014 {match.source_filename} (section {match.section_id})",
    ]
    if match.summary:
        lines.append(match.summary)
    for kf in match.known_failures:
        parts = []
        if kf.symptom:
            parts.append(f"symptom: {kf.symptom}")
        if kf.log_signature:
            parts.append(f"log signature: {kf.log_signature}")
        if kf.failing_step:
            parts.append(f"failing step: {kf.failing_step}")
        if kf.root_cause:
            parts.append(f"root cause: {kf.root_cause}")
        if kf.corrective_action:
            parts.append(f"fix: {kf.corrective_action}")
        if kf.station_check:
            parts.append(f"station check: {kf.station_check}")
        if parts:
            lines.append("- known failure: " + "; ".join(parts))
        for ref in kf.rfc_references:
            ref_parts = [f"RFC: {ref.rfc_id}"]
            if ref.failed_test_name:
                ref_parts.append(f"test: {ref.failed_test_name}")
            if ref.error_message_or_finding:
                ref_parts.append(f"finding: {ref.error_message_or_finding}")
            if ref.notes:
                ref_parts.append(f"notes: {ref.notes}")
            lines.append("  " + "; ".join(ref_parts))
    if match.acronyms:
        lines.append(
            "acronyms: " + "; ".join(f"{a.acronym}={a.definition}" for a in match.acronyms)
        )
    if match.limits:
        lines.append(
            "limits: "
            + "; ".join(
                f"{limit.name}={limit.value}{(' ' + limit.unit) if limit.unit else ''}"
                for limit in match.limits
            )
        )
    return "\n".join(lines)
