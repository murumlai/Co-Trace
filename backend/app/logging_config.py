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
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
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
        "Logging started (%s). Files: %s, %s.",
        _debug_label(debug_enabled),
        os.path.basename(settings.BACKEND_LOG_FILE),
        os.path.basename(settings.FRONTEND_LOG_FILE),
    )


def reset_frontend_log(debug: bool | None = None) -> None:
    """Rewrite the frontend log for a new app run."""
    debug_enabled = settings.APP_DEBUG if debug is None else debug
    os.makedirs(os.path.dirname(settings.FRONTEND_LOG_FILE) or ".", exist_ok=True)
    with open(settings.FRONTEND_LOG_FILE, "w", encoding="utf-8") as fh:
        fh.write(_format_frontend_line("info", f"Frontend log started ({_debug_label(debug_enabled)}).") + "\n")


def write_frontend_log(level: str, message: str, context: dict[str, Any] | None = None) -> None:
    """Append one browser/frontend log line as concise readable text."""
    normalized = _normalize_level(level)
    if normalized == "debug" and not settings.APP_DEBUG:
        return
    line = _format_frontend_line(
        normalized,
        _human_message(message),
        _trim_context(_scrub_context(context or {})),
    )
    try:
        with open(settings.FRONTEND_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        logging.getLogger(BACKEND_LOGGER_NAME).exception("Could not write the frontend log.")


def _normalize_level(level: str) -> str:
    lowered = str(level or "info").lower()
    return lowered if lowered in {"debug", "info", "warning", "error"} else "info"


def _trim_context(context: dict[str, Any]) -> dict[str, Any]:
    max_chars = settings.FRONTEND_LOG_MAX_CONTEXT_CHARS if settings.APP_DEBUG else 1000
    text = json.dumps(context, default=str, ensure_ascii=True, separators=(",", ":"))
    if len(text) <= max_chars:
        return context
    return {"details": text[:max_chars] + "..."}


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


def _format_frontend_line(level: str, message: str, context: dict[str, Any] | None = None) -> str:
    details = _format_context(context or {})
    suffix = f" ({details})" if details else ""
    return f"{_utc_now()} | {level.upper():<7} | {message}{suffix}"


def _format_context(context: dict[str, Any]) -> str:
    flattened = list(_flatten_context(context))
    limit = 12 if settings.APP_DEBUG else 6
    parts = [f"{key}={_short_value(value)}" for key, value in flattened[:limit]]
    if len(flattened) > limit:
        parts.append(f"+{len(flattened) - limit} more")
    return ", ".join(parts)


def _flatten_context(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            next_key = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten_context(item, next_key)
    elif isinstance(value, list):
        yield prefix or "items", f"[{len(value)} items]"
    elif prefix:
        yield prefix, value


def _short_value(value: Any) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ")
    return text[:117] + "..." if len(text) > 120 else text


def _human_message(message: Any) -> str:
    text = str(message or "Frontend event").replace("_", " ").strip()
    return text[:1].upper() + text[1:500]


def _debug_label(debug_enabled: bool) -> str:
    return "debug on" if debug_enabled else "debug off"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")