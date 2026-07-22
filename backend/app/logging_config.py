"""Run-scoped file logging for backend and browser frontend events."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from .config import settings

BACKEND_LOGGER_NAME = "cotrace"
FRONTEND_LOGGER_NAME = "cotrace.frontend"

_BACKEND_HANDLER_TAG = "_cotrace_backend_file"


def setup_backend_logging(debug: bool | None = None) -> None:
    """Configure backend logging for this process.

    The backend log is opened with ``mode='w'`` so every process start creates
    a fresh file. Existing Co_Trace file handlers are removed first to avoid
    duplicate lines in reload/test scenarios.
    """
    debug_enabled = settings.APP_DEBUG if debug is None else debug
    level = logging.DEBUG if debug_enabled else logging.INFO
    os.makedirs(os.path.dirname(settings.BACKEND_LOG_FILE) or ".", exist_ok=True)

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _BACKEND_HANDLER_TAG, False):
            root.removeHandler(handler)
            handler.close()

    handler = logging.FileHandler(settings.BACKEND_LOG_FILE, mode="w", encoding="utf-8")
    setattr(handler, _BACKEND_HANDLER_TAG, True)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(min(root.level, level) if root.level else level)

    logging.captureWarnings(True)
    logging.getLogger(BACKEND_LOGGER_NAME).setLevel(level)
    logging.getLogger("app").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.DEBUG if debug_enabled else logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.DEBUG if debug_enabled else logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.DEBUG if debug_enabled else logging.WARNING)

    reset_frontend_log(debug_enabled)
    logging.getLogger(BACKEND_LOGGER_NAME).info(
        "backend logging initialized debug=%s backend_log=%s frontend_log=%s",
        debug_enabled,
        settings.BACKEND_LOG_FILE,
        settings.FRONTEND_LOG_FILE,
    )


def reset_frontend_log(debug: bool | None = None) -> None:
    """Rewrite the frontend log for a new app run."""
    debug_enabled = settings.APP_DEBUG if debug is None else debug
    os.makedirs(os.path.dirname(settings.FRONTEND_LOG_FILE) or ".", exist_ok=True)
    payload = {
        "ts": _utc_now(),
        "level": "info",
        "source": "backend",
        "message": "frontend log initialized",
        "debug": debug_enabled,
    }
    with open(settings.FRONTEND_LOG_FILE, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, separators=(",", ":")) + "\n")


def write_frontend_log(level: str, message: str, context: dict[str, Any] | None = None) -> None:
    """Append one browser/frontend log line as compact JSONL."""
    normalized = _normalize_level(level)
    if normalized == "debug" and not settings.APP_DEBUG:
        return
    payload = {
        "ts": _utc_now(),
        "level": normalized,
        "source": "frontend",
        "message": str(message)[:500],
        "context": _trim_context(_scrub_context(context or {})),
    }
    try:
        with open(settings.FRONTEND_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    except OSError:
        logging.getLogger(BACKEND_LOGGER_NAME).exception("failed to write frontend log")


def _normalize_level(level: str) -> str:
    lowered = str(level or "info").lower()
    return lowered if lowered in {"debug", "info", "warning", "error"} else "info"


def _trim_context(context: dict[str, Any]) -> dict[str, Any]:
    max_chars = settings.FRONTEND_LOG_MAX_CONTEXT_CHARS if settings.APP_DEBUG else 1000
    text = json.dumps(context, default=str, ensure_ascii=True, separators=(",", ":"))
    if len(text) <= max_chars:
        return context
    return {"truncated": True, "preview": text[:max_chars]}


def _scrub_context(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "[MAX_DEPTH]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_secret_key(key_text):
                out[key_text] = "[REDACTED]"
            else:
                out[key_text] = _scrub_context(item, depth + 1)
        return out
    if isinstance(value, list):
        return [_scrub_context(item, depth + 1) for item in value[:50]]
    return value


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("token", "password", "passwd", "authorization", "secret", "apikey", "api_key"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()