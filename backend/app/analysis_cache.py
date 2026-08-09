"""Persistent local cache for LLM failure analysis results.

The cache is intentionally keyed by the redacted context, provider/model
identity, and prompt/cache version. It stores only the final diagnosis text and
small metadata, never the raw prompt or log excerpt.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .config import settings

log = logging.getLogger("cotrace.cache")

_CACHE_SCHEMA_VERSION = 1
# Bumped to v3 for the authoritative acronym glossary: keys now also fold in the
# approved-glossary hash used for the record, so diagnoses produced before a
# definition was approved/changed (and any old invented expansions) are not
# reused. v2 added the product code, knowledge hash, and matched section mix.
_CACHE_PROMPT_VERSION = "analysis-v3"
_lock = threading.Lock()


def make_key(
    *,
    error_code: str | None,
    error_message: str | None,
    context: str,
    context_source: str,
    signature: str,
    product_code: str | None = None,
    op_id: str | None = None,
    failing_step: str | None = None,
    knowledge_hash: str | None = None,
    knowledge_sections: str | None = None,
    knowledge_categories: str | None = None,
    acronym_glossary_hash: str | None = None,
) -> str:
    payload = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "prompt_version": _CACHE_PROMPT_VERSION,
        "provider": (settings.LLM_PROVIDER or "").lower(),
        "model_identity": _model_identity(),
        "signature": signature,
        "error_code": error_code or "",
        "error_message": error_message or "",
        "context_source": context_source,
        "context": context or "",
        "product_code": product_code or "",
        "op_id": op_id or "",
        "failing_step": failing_step or "",
        "knowledge_hash": knowledge_hash or "",
        "knowledge_sections": knowledge_sections or "",
        "knowledge_categories": knowledge_categories or "",
        "acronym_glossary_hash": acronym_glossary_hash or "",
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def get_entry(cache_key: str) -> dict[str, Any] | None:
    if not settings.ANALYSIS_CACHE_ENABLED:
        return None
    with _lock:
        data = _load()
        entry = data["entries"].get(cache_key)
        if not entry:
            return None
        entry["last_used_at"] = _now()
        entry["hit_count"] = int(entry.get("hit_count", 0)) + 1
        _save(data)
        return dict(entry)


def set_entry(
    cache_key: str,
    *,
    root_cause: str,
    suggested_solution: str,
    source: str,
    metadata: dict[str, Any],
) -> None:
    if not settings.ANALYSIS_CACHE_ENABLED:
        return
    if source != "llm":
        return
    now = _now()
    created_by = str(metadata.get("created_by") or "")[:120]
    created_by_login = str(metadata.get("created_by_login") or "")[:120]
    created_by_role = "admin" if str(metadata.get("created_by_role") or "").lower() == "admin" else "user"
    protected = bool(metadata.get("protected")) or created_by_role == "admin"
    with _lock:
        data = _load()
        existing = data["entries"].get(cache_key, {})
        data["entries"][cache_key] = {
            "cache_key": cache_key,
            "root_cause": root_cause,
            "suggested_solution": suggested_solution,
            "source": source,
            "provider": (settings.LLM_PROVIDER or "").lower(),
            "model_identity": _model_identity(),
            "prompt_version": _CACHE_PROMPT_VERSION,
            "created_at": existing.get("created_at", now),
            "created_by": existing.get("created_by", created_by),
            "created_by_login": existing.get("created_by_login", created_by_login),
            "created_by_role": existing.get("created_by_role", created_by_role),
            "is_admin_saved": bool(existing.get("is_admin_saved", protected)),
            "protected": bool(existing.get("protected", protected)),
            "updated_at": now,
            "last_used_at": now,
            "hit_count": int(existing.get("hit_count", 0)),
            "metadata": _safe_metadata(metadata),
        }
        _save(data)
    log.info("Saved analysis cache entry %s.", cache_key[:8])


def delete_entry(cache_key: str, *, actor_id: str | None = None, actor_is_admin: bool = False) -> bool:
    with _lock:
        data = _load()
        entry = data["entries"].get(cache_key)
        if not entry:
            return False
        allowed = actor_is_admin or (
            actor_id
            and entry.get("created_by") == actor_id
            and not entry.get("protected")
            and not entry.get("is_admin_saved")
        )
        if allowed:
            del data["entries"][cache_key]
            _save(data)
    if allowed:
        log.info("Deleted analysis cache entry %s.", cache_key[:8])
    return bool(allowed)


def list_entries(*, actor_is_admin: bool = False) -> list[dict[str, Any]]:
    with _lock:
        data = _load()
        entries = [_visible_entry(entry, actor_is_admin=actor_is_admin) for entry in data["entries"].values()]
    entries.sort(key=lambda item: item.get("last_used_at") or item.get("updated_at") or "", reverse=True)
    return entries


def _visible_entry(entry: dict[str, Any], *, actor_is_admin: bool) -> dict[str, Any]:
    visible = dict(entry)
    if actor_is_admin:
        return visible
    visible.pop("created_by", None)
    visible.pop("created_by_login", None)
    metadata = dict(visible.get("metadata") or {})
    metadata.pop("unit_id", None)
    visible["metadata"] = metadata
    return visible


def _model_identity() -> dict[str, Any]:
    provider = (settings.LLM_PROVIDER or "").lower()
    if provider == "copilot_sdk":
        return {
            "mini_model": settings.COPILOT_MINI_MODEL,
            "reasoning_model": settings.COPILOT_REASONING_MODEL,
            "mini_enrich": settings.COPILOT_ENABLE_MINI_ENRICH,
        }
    if provider == "github_models":
        return {"model": settings.LLM_MODEL, "endpoint": settings.LLM_ENDPOINT}
    return {"provider": provider}


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "signature",
        "error_code",
        "error_message",
        "context_source",
        "unit_id",
        "product_code",
        "failing_step",
        "op_id",
        "knowledge_hash",
        "knowledge_match_status",
        "knowledge_section_ids",
        "knowledge_categories",
        "acronym_glossary_hash",
        "acronyms_used",
        "unknown_acronyms",
    }
    out: dict[str, Any] = {}
    for key in allowed:
        value = metadata.get(key)
        if value is not None:
            out[key] = str(value)[:240]
    return out


def _load() -> dict[str, Any]:
    path = settings.ANALYSIS_CACHE_FILE
    if not os.path.exists(path):
        return {"schema_version": _CACHE_SCHEMA_VERSION, "entries": {}}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("schema_version") != _CACHE_SCHEMA_VERSION or not isinstance(data.get("entries"), dict):
            return {"schema_version": _CACHE_SCHEMA_VERSION, "entries": {}}
        return data
    except (OSError, json.JSONDecodeError):
        log.exception("Could not read analysis cache; starting with an empty cache.")
        return {"schema_version": _CACHE_SCHEMA_VERSION, "entries": {}}


def _save(data: dict[str, Any]) -> None:
    path = settings.ANALYSIS_CACHE_FILE
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    # Write to a unique temp file so concurrent writers (another thread, or a
    # second backend instance sharing this cache dir) never collide on the same
    # scratch file.
    fd, tmp = tempfile.mkstemp(prefix="analysis_cache.", suffix=".tmp", dir=directory)
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=True, separators=(",", ":"))
        _atomic_replace(tmp, path)
        replaced = True
    except OSError:
        # Persisting the cache is best-effort; a write failure (e.g. a transient
        # Windows lock from AV/indexer or a second instance) must never abort
        # log processing. Keep the in-memory copy and move on.
        log.exception("Could not persist analysis cache to %s; keeping in-memory copy only.", path)
    finally:
        if not replaced and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _atomic_replace(src: str, dst: str, *, attempts: int = 5, delay: float = 0.1) -> None:
    """``os.replace`` with retry.

    On Windows the replace raises ``PermissionError`` (WinError 5/32) when
    another process momentarily holds the destination open — antivirus, the
    search indexer, or a concurrent backend instance. Retry briefly before
    giving up.
    """
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# DiskAnalysisCache — concrete adapter for the AnalysisCache contract
# ---------------------------------------------------------------------------

class DiskAnalysisCache:
    """Wraps module-level cache functions as an ``AnalysisCache`` implementation.

    Method names match the ``AnalysisCache`` protocol (``get`` / ``put`` /
    ``make_key``). Implementations delegate to the module-level functions so
    tests that monkeypatch ``get_entry`` / ``set_entry`` continue to work.
    """

    def make_key(
        self,
        *,
        error_code: str | None,
        error_message: str | None,
        context: str,
        context_source: str,
        signature: str,
        product_code: str | None = None,
        op_id: str | None = None,
        failing_step: str | None = None,
        knowledge_hash: str | None = None,
        knowledge_sections: str | None = None,
        knowledge_categories: str | None = None,
        acronym_glossary_hash: str | None = None,
    ) -> str:
        return make_key(
            error_code=error_code,
            error_message=error_message,
            context=context,
            context_source=context_source,
            signature=signature,
            product_code=product_code,
            op_id=op_id,
            failing_step=failing_step,
            knowledge_hash=knowledge_hash,
            knowledge_sections=knowledge_sections,
            knowledge_categories=knowledge_categories,
            acronym_glossary_hash=acronym_glossary_hash,
        )

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """Return a cached entry or ``None`` on a miss."""
        return get_entry(cache_key)

    def put(
        self,
        cache_key: str,
        *,
        root_cause: str,
        suggested_solution: str,
        source: str,
        metadata: dict[str, Any],
    ) -> None:
        """Store an analysis result (only persisted when source == "llm")."""
        set_entry(
            cache_key,
            root_cause=root_cause,
            suggested_solution=suggested_solution,
            source=source,
            metadata=metadata,
        )

    # --- Administrative helpers (not in the core AnalysisCache protocol) ---

    def list_entries(self, *, actor_is_admin: bool = False) -> list[dict[str, Any]]:
        """Return all cache entries, most-recently-used first."""
        return list_entries(actor_is_admin=actor_is_admin)

    def delete_entry(self, cache_key: str, *, actor_id: str | None = None, actor_is_admin: bool = False) -> bool:
        """Delete a specific cache entry; return True if it existed."""
        return delete_entry(cache_key, actor_id=actor_id, actor_is_admin=actor_is_admin)


# Module-level default instance used when no cache is explicitly injected.
_default_cache = DiskAnalysisCache()
