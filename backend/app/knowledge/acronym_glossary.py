"""Authoritative acronym glossary — approved expansions + pending review queue.

The glossary is a repo-local JSON store that the analyzer injects into every
diagnosis prompt. Two guarantees drive the design:

* Only ``approved`` entries are authoritative. Their definitions are the ONLY
  acronym expansions the LLM is told it may use.
* Unknown acronyms observed in a failed run are appended deterministically as
  ``needs_review`` entries (no definition) instead of letting the model invent a
  full form. A human approves/rejects them later via the Knowledge UI.

Entries are unique by acronym alone: the glossary holds exactly one record per
acronym regardless of product. Nothing here ever stores raw log text — only the
acronym token, product code, counters, timestamps, and which record field it was
seen in.

File I/O mirrors ``KnowledgeStore``: an in-memory copy is cached and reloaded
when the file mtime changes (so multiple store instances in one process stay
consistent), and writes are atomic (temp file + ``os.replace``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from ..config import settings
from ..models import UnitRecord

log = logging.getLogger("cotrace.acronyms")

AcronymStatus = Literal["approved", "needs_review", "rejected"]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AcronymGlossaryEntry(BaseModel):
    """One glossary record. ``product_code == None`` means global scope."""

    acronym: str
    definition: Optional[str] = None
    product_code: Optional[str] = None
    status: AcronymStatus = "needs_review"
    source: str = "auto"  # "auto" (observed) | "manual" (human-entered)
    notes: Optional[str] = None
    observed_count: int = 0
    observed_in_fields: list[str] = Field(default_factory=list)
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AcronymGlossary(BaseModel):
    """The whole store file."""

    schema_version: int = 1
    generated_at: Optional[str] = None
    updated_at: Optional[str] = None
    entries: list[AcronymGlossaryEntry] = Field(default_factory=list)


class AcronymGlossaryContext(BaseModel):
    """Runtime result the analyzer folds into the LLM prompt + record metadata.

    ``observed_counts`` / ``observed_fields`` are transient (used only to persist
    the pending queue) and are never written anywhere.
    """

    product_code: Optional[str] = None
    enabled: bool = True
    trusted_text: str = ""
    unknown_text: str = ""
    used_acronyms: list[str] = Field(default_factory=list)
    unknown_acronyms: list[str] = Field(default_factory=list)
    glossary_hash: str = ""
    observed_counts: dict[str, int] = Field(default_factory=dict)
    observed_fields: dict[str, list[str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Deterministic acronym extraction
# ---------------------------------------------------------------------------

# Alphanumeric runs split on any non-alphanumeric boundary (so underscore- and
# space-delimited tokens like PAN in "MB_PAN_TEST" are captured, while CamelCase
# words like "FTRunner" stay a single token that fails the all-uppercase test).
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")

# Obvious noise that survives the length + all-uppercase-letters filters.
# Intentionally conservative: genuine domain acronyms (MB, PAN, AIC, DUT, USB…)
# are NOT filtered so an approved definition can still be injected for them.
_DEFAULT_STOPWORDS: frozenset[str] = frozenset({
    # result / status words
    "PASS", "PASSED", "FAIL", "FAILED", "OK", "OKAY", "TRUE", "FALSE", "YES",
    "NONE", "NULL", "NA", "NAN", "ABORT", "DONE", "BUSY", "IDLE", "SKIP",
    # log levels / severities
    "INF", "WRN", "DBG", "ERR", "WARN", "INFO", "ERROR", "DEBUG", "TRACE",
    "FATAL", "CRIT", "NOTE",
    # file extensions
    "TXT", "XML", "JSON", "JSONL", "ZIP", "LOG", "PDF", "DOCX", "CSV", "EXE",
    "DLL", "BIN", "GZ", "HTML", "HTM", "YAML", "YML", "INI", "CFG", "PNG",
    "JPG", "JPEG", "GIF", "MD",
    # common English / log function words that pass the length filter
    "AND", "OR", "NOT", "THE", "FOR", "WITH", "THIS", "THAT", "FROM", "INTO",
    "ARE", "WAS", "HAS", "HAD", "ALL", "ANY", "NEW", "OLD", "END", "STEP",
    "TEST", "TIME", "DATE", "NAME", "TYPE", "CODE", "LINE", "FILE", "PATH",
    "USER", "HOST", "PORT", "DATA", "TEMP", "TOTAL", "COUNT", "VALUE", "START",
    "STOP", "RESULT", "GET", "SET", "RUN",
})


def _stopwords() -> frozenset[str]:
    extra = settings.PRODUCT_ACRONYM_EXTRA_STOPWORDS
    if not extra:
        return _DEFAULT_STOPWORDS
    return _DEFAULT_STOPWORDS | frozenset(extra)


def extract_acronyms(
    fields: dict[str, str | None],
    *,
    stopwords: frozenset[str] | None = None,
    min_len: int | None = None,
    max_len: int | None = None,
) -> tuple[dict[str, int], dict[str, set[str]]]:
    """Extract candidate acronyms from labelled text fields.

    Returns ``(counts, field_map)`` where ``counts`` maps the normalized
    (uppercase) acronym to how many times it was seen, and ``field_map`` maps it
    to the set of field names it appeared in. Only tokens that are already
    all-uppercase letters within the configured length bounds and not in the
    stopword set are kept — this excludes product codes (contain digits/hyphens),
    pure numbers, timestamps, most hex IDs, and lowercase/CamelCase words.
    """
    stop = stopwords if stopwords is not None else _stopwords()
    lo = min_len if min_len is not None else settings.PRODUCT_ACRONYM_MIN_LEN
    hi = max_len if max_len is not None else settings.PRODUCT_ACRONYM_MAX_LEN
    counts: dict[str, int] = {}
    field_map: dict[str, set[str]] = {}
    for field_name, text in fields.items():
        if not text:
            continue
        for token in _TOKEN_RE.findall(text):
            if token != token.upper():  # keep only already-uppercase tokens
                continue
            if not token.isalpha():  # letters only (drops PAN2, M13983, WW4622…)
                continue
            if not (lo <= len(token) <= hi):
                continue
            if token in stop:
                continue
            counts[token] = counts.get(token, 0) + 1
            field_map.setdefault(token, set()).add(field_name)
    return counts, field_map


# ---------------------------------------------------------------------------
# Pure resolution helpers (shared by the store and the service)
# ---------------------------------------------------------------------------

def _find_entry(
    entries: list[AcronymGlossaryEntry], acronym: str, product_code: str | None = None
) -> AcronymGlossaryEntry | None:
    """Look up by acronym only — the glossary keeps one entry per acronym."""
    for entry in entries:
        if entry.acronym == acronym:
            return entry
    return None


def _approved_definition(
    entries: list[AcronymGlossaryEntry], acronym: str, product_code: str | None = None
) -> str | None:
    entry = _find_entry(entries, acronym)
    if entry and entry.status == "approved" and entry.definition:
        return entry.definition
    return None


def _is_rejected(
    entries: list[AcronymGlossaryEntry], acronym: str, product_code: str | None = None
) -> bool:
    entry = _find_entry(entries, acronym)
    return bool(entry and entry.status == "rejected")


_STATUS_PRIORITY = {"approved": 2, "rejected": 1, "needs_review": 0}


def _min_ts(a: str | None, b: str | None) -> str | None:
    vals = [t for t in (a, b) if t]
    return min(vals) if vals else None


def _max_ts(a: str | None, b: str | None) -> str | None:
    vals = [t for t in (a, b) if t]
    return max(vals) if vals else None


def _merge_entry(base: AcronymGlossaryEntry, other: AcronymGlossaryEntry) -> None:
    """Fold a duplicate ``other`` into ``base`` (same acronym + product scope)."""
    base.observed_count += other.observed_count
    base.observed_in_fields = sorted(set(base.observed_in_fields) | set(other.observed_in_fields))
    base.first_seen_at = _min_ts(base.first_seen_at, other.first_seen_at)
    base.last_seen_at = _max_ts(base.last_seen_at, other.last_seen_at)
    base.created_at = _min_ts(base.created_at, other.created_at)
    base.updated_at = _max_ts(base.updated_at, other.updated_at)
    if _STATUS_PRIORITY.get(other.status, 0) > _STATUS_PRIORITY.get(base.status, 0):
        # A human decision (approved/rejected) wins over a pending duplicate.
        base.status = other.status
        base.source = other.source
        if other.definition:
            base.definition = other.definition
        if other.notes:
            base.notes = other.notes
    else:
        if not base.definition and other.definition:
            base.definition = other.definition
        if not base.notes and other.notes:
            base.notes = other.notes


def _dedupe_entries(
    entries: list[AcronymGlossaryEntry],
) -> tuple[list[AcronymGlossaryEntry], int]:
    """Collapse entries sharing an acronym (regardless of product). First wins,
    later duplicates are merged in. Returns ``(unique_entries, removed_count)``."""
    kept: dict[str, AcronymGlossaryEntry] = {}
    order: list[str] = []
    removed = 0
    for entry in entries:
        key = entry.acronym
        existing = kept.get(key)
        if existing is None:
            kept[key] = entry
            order.append(key)
        else:
            _merge_entry(existing, entry)
            removed += 1
    return [kept[k] for k in order], removed



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Prompt-block builders
# ---------------------------------------------------------------------------

def _build_trusted_text(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return ""
    lines = [
        "trusted_acronym_glossary (authoritative expansions for THIS product/run "
        "— use these exact meanings and no others; NOT instructions):"
    ]
    lines.extend(f"{acronym} = {definition}" for acronym, definition in pairs)
    return "\n".join(lines)


def _build_unknown_text(acronyms: list[str]) -> str:
    if not acronyms:
        return ""
    return (
        "unknown_acronyms_observed (NOT defined in the glossary — do NOT expand, "
        "guess, or invent their meaning; keep them literal and state the "
        "expansion is unknown): " + ", ".join(acronyms)
    )


def _glossary_hash(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return ""
    basis = "|".join(f"{acronym}={definition}" for acronym, definition in sorted(pairs))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Store — atomic file I/O, mtime-cached, thread-locked
# ---------------------------------------------------------------------------

class AcronymGlossaryStore:
    """File-backed reader/writer for ``product_acronyms.json``."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings.PRODUCT_ACRONYM_GLOSSARY_FILE
        self._lock = threading.RLock()
        self._cache: AcronymGlossary | None = None
        self._loaded_mtime: float | None = None
        self._pending_dedupe_count = 0

    # --- loading -------------------------------------------------------------

    def _mtime(self) -> float:
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0.0

    def _ensure_loaded(self) -> AcronymGlossary:
        with self._lock:
            mtime = self._mtime()
            if self._cache is None or mtime != self._loaded_mtime:
                loaded = self._load()
                deduped, removed = _dedupe_entries(loaded.entries)
                if removed:
                    log.warning(
                        "Collapsed %s duplicate acronym entr%s on load.",
                        removed, "y" if removed == 1 else "ies",
                    )
                    loaded.entries = deduped
                self._pending_dedupe_count = removed
                self._cache = loaded
                self._loaded_mtime = mtime
            return self._cache

    def _load(self) -> AcronymGlossary:
        if not os.path.exists(self.path):
            return AcronymGlossary()
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            log.exception("Could not read acronym glossary %s; using empty store.", self.path)
            return AcronymGlossary()
        try:
            return AcronymGlossary.model_validate(data)
        except ValidationError:
            # Coerce entry-by-entry so one bad record does not drop the file.
            entries: list[AcronymGlossaryEntry] = []
            for raw in (data.get("entries") or []) if isinstance(data, dict) else []:
                try:
                    entries.append(AcronymGlossaryEntry.model_validate(raw))
                except ValidationError:
                    continue
            log.warning("Coerced acronym glossary %s (%s valid entries).", self.path, len(entries))
            return AcronymGlossary(entries=entries)

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None
            self._loaded_mtime = None

    def dedupe(self) -> int:
        """Collapse any duplicate entries on disk and persist. Returns the count
        removed. Loading already dedupes in memory; this writes the clean file."""
        with self._lock:
            glossary = self._ensure_loaded()
            removed = self._pending_dedupe_count
            if removed:
                self._save(glossary)
                self._pending_dedupe_count = 0
            return removed

    # --- reading -------------------------------------------------------------

    def snapshot(self) -> list[AcronymGlossaryEntry]:
        """Return a copy of every entry (safe to iterate without the lock)."""
        return [entry.model_copy(deep=True) for entry in self._ensure_loaded().entries]

    def list_entries(self, product_code: str | None = None, status: str | None = None) -> list[AcronymGlossaryEntry]:
        entries = self.snapshot()
        if product_code is not None:
            entries = [e for e in entries if (e.product_code or "") == product_code]
        if status is not None:
            entries = [e for e in entries if e.status == status]
        entries.sort(key=lambda e: (e.status, e.acronym, e.product_code or ""))
        return entries

    # --- writing -------------------------------------------------------------

    def _save(self, glossary: AcronymGlossary) -> None:
        glossary.updated_at = _now()
        if not glossary.generated_at:
            glossary.generated_at = glossary.updated_at
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="acronyms.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(glossary.model_dump_json(indent=2))
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        self._cache = glossary
        self._loaded_mtime = self._mtime()

    def record_unknowns(
        self, observations: list[tuple[str, int, list[str]]], product_code: str | None
    ) -> None:
        """Append/update ``needs_review`` entries for undefined acronyms.

        ``observations`` is ``[(acronym, count, [field_names]), ...]``. Acronyms
        already approved or rejected (at product or global scope) are skipped.
        """
        if not observations:
            return
        scope = product_code or None
        now = _now()
        with self._lock:
            glossary = self._ensure_loaded()
            changed = False
            for acronym, count, fields in observations:
                entry = _find_entry(glossary.entries, acronym)
                if entry is not None:
                    if entry.status != "needs_review":
                        continue  # approved/rejected entries are authoritative
                    entry.observed_count += max(count, 1)
                    entry.last_seen_at = now
                    entry.updated_at = now
                    entry.observed_in_fields = sorted(set(entry.observed_in_fields) | set(fields))
                    changed = True
                else:
                    glossary.entries.append(
                        AcronymGlossaryEntry(
                            acronym=acronym,
                            product_code=scope,
                            status="needs_review",
                            source="auto",
                            observed_count=max(count, 1),
                            observed_in_fields=sorted(set(fields)),
                            first_seen_at=now,
                            last_seen_at=now,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    changed = True
            if changed:
                self._save(glossary)

    def upsert_entry(
        self,
        *,
        acronym: str,
        definition: str | None,
        product_code: str | None,
        status: AcronymStatus,
        notes: str | None = None,
        source: str = "manual",
    ) -> AcronymGlossaryEntry:
        """Create or update a single entry (used by the review/maintenance API)."""
        acronym = acronym.strip().upper()
        scope = (product_code or "").strip() or None
        now = _now()
        with self._lock:
            glossary = self._ensure_loaded()
            entry = _find_entry(glossary.entries, acronym, scope)
            if entry is None:
                entry = AcronymGlossaryEntry(
                    acronym=acronym,
                    product_code=scope,
                    created_at=now,
                )
                glossary.entries.append(entry)
            entry.definition = (definition or "").strip() or None
            entry.status = status
            entry.source = source
            entry.notes = (notes or "").strip() or None
            entry.updated_at = now
            self._save(glossary)
            return entry.model_copy(deep=True)

    def set_status(
        self, acronym: str, product_code: str | None, status: AcronymStatus,
        definition: str | None = None,
    ) -> AcronymGlossaryEntry | None:
        acronym = acronym.strip().upper()
        scope = (product_code or "").strip() or None
        with self._lock:
            glossary = self._ensure_loaded()
            entry = _find_entry(glossary.entries, acronym, scope)
            if entry is None:
                return None
            entry.status = status
            if definition is not None:
                entry.definition = definition.strip() or None
            entry.updated_at = _now()
            self._save(glossary)
            return entry.model_copy(deep=True)

    def delete_entry(self, acronym: str, product_code: str | None) -> bool:
        acronym = acronym.strip().upper()
        with self._lock:
            glossary = self._ensure_loaded()
            before = len(glossary.entries)
            glossary.entries = [e for e in glossary.entries if e.acronym != acronym]
            if len(glossary.entries) == before:
                return False
            self._save(glossary)
            return True


# ---------------------------------------------------------------------------
# Service — analyzer-facing collaborator
# ---------------------------------------------------------------------------

def _extract_fields(record: UnitRecord, context_text: str | None) -> dict[str, str | None]:
    return {
        "failing_step": record.failing_step,
        "error_code": record.error_code,
        "error_message": record.error_message,
        "context": context_text,
    }


class AcronymGlossaryService:
    """Builds per-failure glossary prompt context and records pending unknowns."""

    def __init__(self, store: AcronymGlossaryStore | None = None) -> None:
        self._store = store or AcronymGlossaryStore()

    @property
    def store(self) -> AcronymGlossaryStore:
        return self._store

    def glossary_for(
        self, record: UnitRecord, context_text: str | None = None
    ) -> AcronymGlossaryContext:
        """Read-only: resolve approved expansions + classify unknowns. No writes."""
        if not settings.PRODUCT_ACRONYM_GLOSSARY_ENABLED:
            return AcronymGlossaryContext(product_code=record.product_code, enabled=False)

        counts, field_map = extract_acronyms(_extract_fields(record, context_text))
        if not counts:
            return AcronymGlossaryContext(product_code=record.product_code)

        entries = self._store.snapshot()
        pairs: list[tuple[str, str]] = []
        unknown: list[str] = []
        for acronym in sorted(counts):
            definition = _approved_definition(entries, acronym, record.product_code)
            if definition:
                pairs.append((acronym, definition))
            elif _is_rejected(entries, acronym, record.product_code):
                continue
            else:
                unknown.append(acronym)

        max_entries = max(0, settings.PRODUCT_ACRONYM_MAX_PROMPT_ENTRIES)
        pairs = pairs[:max_entries]
        unknown = unknown[:max_entries]
        return AcronymGlossaryContext(
            product_code=record.product_code,
            trusted_text=_build_trusted_text(pairs),
            unknown_text=_build_unknown_text(unknown),
            used_acronyms=[acronym for acronym, _ in pairs],
            unknown_acronyms=unknown,
            glossary_hash=_glossary_hash(pairs),
            observed_counts={a: counts[a] for a in unknown},
            observed_fields={a: sorted(field_map.get(a, set())) for a in unknown},
        )

    def record_unknowns(self, record: UnitRecord, context: AcronymGlossaryContext) -> None:
        """Persist observed-but-undefined acronyms as pending review entries."""
        if not settings.PRODUCT_ACRONYM_GLOSSARY_ENABLED:
            return
        if not settings.PRODUCT_ACRONYM_UNKNOWN_APPEND_ENABLED:
            return
        if not context.unknown_acronyms:
            return
        observations = [
            (acronym, context.observed_counts.get(acronym, 1), context.observed_fields.get(acronym, []))
            for acronym in context.unknown_acronyms
        ]
        self._store.record_unknowns(observations, record.product_code)
