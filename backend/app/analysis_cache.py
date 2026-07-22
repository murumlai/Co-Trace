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
import threading
from datetime import datetime, timezone
from typing import Any

from .config import settings

log = logging.getLogger("cotrace.cache")

_CACHE_SCHEMA_VERSION = 1
_CACHE_PROMPT_VERSION = "analysis-v1"
_lock = threading.Lock()


def make_key(
    *,
    error_code: str | None,
    error_message: str | None,
    context: str,
    context_source: str,
    signature: str,
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
            "updated_at": now,
            "last_used_at": now,
            "hit_count": int(existing.get("hit_count", 0)),
            "metadata": _safe_metadata(metadata),
        }
        _save(data)
    log.info("Saved analysis cache entry %s.", cache_key[:8])


def delete_entry(cache_key: str) -> bool:
    with _lock:
        data = _load()
        existed = cache_key in data["entries"]
        if existed:
            del data["entries"][cache_key]
            _save(data)
    if existed:
        log.info("Deleted analysis cache entry %s.", cache_key[:8])
    return existed


def list_entries() -> list[dict[str, Any]]:
    with _lock:
        data = _load()
        entries = [dict(entry) for entry in data["entries"].values()]
    entries.sort(key=lambda item: item.get("last_used_at") or item.get("updated_at") or "", reverse=True)
    return entries


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
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=True, separators=(",", ":"))
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
