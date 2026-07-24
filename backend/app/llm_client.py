"""LLM client wrapping the GitHub Models chat API.

Falls back to a deterministic offline stub when no GITHUB_TOKEN is configured,
so the whole app runs without external calls or cost.
"""
from __future__ import annotations

import json

import httpx

from .config import settings
from .models import LlmAnalysisResult, LlmUsageMetrics

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
    return analyze_with_metrics(error_code, error_message, snippet).as_tuple()


def analyze_with_metrics(
    error_code: str | None, error_message: str | None, snippet: str
) -> LlmAnalysisResult:
    """Return (root_cause, suggested_solution, source).

    Dispatches to the configured provider (``settings.LLM_PROVIDER``):
    ``copilot_sdk`` uses the GitHub Copilot SDK, ``offline_stub`` forces the
    deterministic heuristic, and ``github_models`` (default) uses the GitHub
    Models chat API — itself falling back to the stub when no token is set.
    """
    provider = (settings.LLM_PROVIDER or "github_models").lower()
    if provider == "offline_stub":
        root, solution, source = _offline_stub(error_code, error_message)
        return LlmAnalysisResult(
            root_cause=root,
            suggested_solution=solution,
            source=source,
            metrics=LlmUsageMetrics(provider="offline_stub"),
        )
    if provider == "copilot_sdk":
        from . import copilot_client

        return copilot_client.analyze_with_metrics(error_code, error_message, snippet)
    return _analyze_github_models_with_metrics(error_code, error_message, snippet)


# ---------------------------------------------------------------------------
# LLMProvider implementations (concrete adapters for the LLMProvider contract)
# ---------------------------------------------------------------------------

class OfflineStubProvider:
    """Deterministic offline stub — no external calls, no token required."""

    def analyze(
        self,
        error_code: str | None,
        error_message: str | None,
        snippet: str,
    ) -> tuple[str, str, str]:
        return _offline_stub(error_code, error_message)


class GitHubModelsProvider:
    """GitHub Models chat-completions API; falls back to stub without a token."""

    def analyze(
        self,
        error_code: str | None,
        error_message: str | None,
        snippet: str,
    ) -> tuple[str, str, str]:
        return _analyze_github_models(error_code, error_message, snippet)


class CopilotSdkProvider:
    """GitHub Copilot SDK provider (requires ``copilot auth login``)."""

    def analyze(
        self,
        error_code: str | None,
        error_message: str | None,
        snippet: str,
    ) -> tuple[str, str, str]:
        from . import copilot_client  # noqa: PLC0415

        return copilot_client.analyze(error_code, error_message, snippet)


def _analyze_github_models(
    error_code: str | None, error_message: str | None, snippet: str
) -> tuple[str, str, str]:
    return _analyze_github_models_with_metrics(error_code, error_message, snippet).as_tuple()


def _analyze_github_models_with_metrics(
    error_code: str | None, error_message: str | None, snippet: str
) -> LlmAnalysisResult:
    """GitHub Models chat-completions path."""
    if not settings.GITHUB_TOKEN:
        root, solution, source = _offline_stub(error_code, error_message)
        return LlmAnalysisResult(
            root_cause=root,
            suggested_solution=solution,
            source=source,
            metrics=LlmUsageMetrics(provider="github_models"),
        )

    user_prompt = _build_user_prompt(error_code, error_message, snippet)

    payload = {
        "model": settings.LLM_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
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
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            root, solution = _parse_json_content(content)
            metrics = LlmUsageMetrics(provider="github_models")
            usage = data.get("usage") or {}
            prompt_tokens = _usage_int(usage, "prompt_tokens", "input_tokens")
            completion_tokens = _usage_int(usage, "completion_tokens", "output_tokens")
            metrics.add_model_call(
                "reasoning",
                model=settings.LLM_MODEL,
                input_chars=len(_SYSTEM_PROMPT) + len(user_prompt),
                output_chars=len(content),
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                token_counts_estimated=prompt_tokens is None or completion_tokens is None,
                credit_tokens_per_credit=settings.LLM_TOKEN_CREDIT_SIZE,
            )
            return LlmAnalysisResult(
                root_cause=root,
                suggested_solution=solution,
                source="llm",
                metrics=metrics,
            )
        except Exception as exc:  # noqa: BLE001 - degrade gracefully to stub
            last_err = exc
            continue

    root, solution, _ = _offline_stub(error_code, error_message)
    metrics = LlmUsageMetrics(provider="github_models")
    metrics.add_model_error("reasoning", model=settings.LLM_MODEL)
    return LlmAnalysisResult(
        root_cause=root,
        suggested_solution=f"{solution} (LLM error: {type(last_err).__name__})",
        source="stub",
        metrics=metrics,
    )


def _usage_int(usage: dict, *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


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
