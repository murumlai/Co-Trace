"""LLM client wrapping the GitHub Models chat API.

Falls back to a deterministic offline stub when no GITHUB_TOKEN is configured,
so the whole app runs without external calls or cost.
"""
from __future__ import annotations

import json

import httpx

from .config import settings

_SYSTEM_PROMPT = (
    "You are a manufacturing test-failure diagnostician. Given a redacted log "
    "snippet and structured error context from a failed hardware test run, "
    "identify the single most probable root cause and a concrete suggested "
    "solution. Be concise and specific. Respond ONLY as compact JSON with keys "
    '"root_cause" and "suggested_solution".'
)


def _build_user_prompt(error_code: str | None, error_message: str | None, snippet: str) -> str:
    return (
        f"error_code: {error_code or 'UNKNOWN'}\n"
        f"error_message: {error_message or 'N/A'}\n"
        f"redacted_log_snippet:\n{snippet}\n"
    )


def _offline_stub(error_code: str | None, error_message: str | None) -> tuple[str, str, str]:
    code = error_code or "FAIL"
    root = (
        f"Offline heuristic: the run failed with '{code}'. "
        f"The reported condition was: {(error_message or 'unspecified')[:160]}."
    )
    solution = (
        "Verify the failing step's fixture/connection and DUT seating, re-run the "
        "unit, and if the same signature repeats, escalate to the station owner "
        "for calibration/config review. (Set GITHUB_TOKEN to enable AI diagnosis.)"
    )
    return root, solution, "stub"


def analyze(error_code: str | None, error_message: str | None, snippet: str) -> tuple[str, str, str]:
    """Return (root_cause, suggested_solution, source)."""
    if not settings.GITHUB_TOKEN:
        return _offline_stub(error_code, error_message)

    payload = {
        "model": settings.LLM_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(error_code, error_message, snippet)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }

    last_err: Exception | None = None
    for _ in range(settings.LLM_MAX_RETRIES + 1):
        try:
            resp = httpx.post(
                settings.LLM_ENDPOINT, json=payload, headers=headers,
                timeout=settings.LLM_TIMEOUT_S,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            root, solution = _parse_json_content(content)
            return root, solution, "llm"
        except Exception as exc:  # noqa: BLE001 - degrade gracefully to stub
            last_err = exc
            continue

    root, solution, _ = _offline_stub(error_code, error_message)
    return root, f"{solution} (LLM error: {type(last_err).__name__})", "stub"


def _parse_json_content(content: str) -> tuple[str, str]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    try:
        data = json.loads(text)
        return (
            str(data.get("root_cause", "")).strip() or "No root cause returned.",
            str(data.get("suggested_solution", "")).strip() or "No solution returned.",
        )
    except (json.JSONDecodeError, ValueError):
        return content.strip(), "See root cause above."
