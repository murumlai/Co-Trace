"""LLM dispatch for failed-unit diagnosis.

Routes to the enterprise GitHub Copilot SDK provider (``copilot_sdk``) or the
deterministic local offline stub (``offline_stub``). The public GitHub Models
path has been removed; enterprise Copilot is the only sanctioned AI backend.
"""
from __future__ import annotations

from .config import settings
from .models import LlmAnalysisResult, LlmUsageMetrics


def _offline_stub(error_code: str | None, error_message: str | None) -> tuple[str, str, str]:
    code = error_code or "FAIL"
    root = (
        f"Offline heuristic: the run failed with '{code}'. "
        f"The reported condition was: {(error_message or 'unspecified')[:160]}."
    )
    solution = (
        "Verify the failing step's fixture/connection and DUT seating, re-run the "
        "unit, and if the same signature repeats, escalate to the station owner "
        "for calibration/config review."
    )
    return root, solution, "stub"


def analyze(error_code: str | None, error_message: str | None, snippet: str,
            knowledge_context: str | None = None) -> tuple[str, str, str]:
    return analyze_with_metrics(
        error_code, error_message, snippet, knowledge_context
    ).as_tuple()


def analyze_with_metrics(
    error_code: str | None,
    error_message: str | None,
    snippet: str,
    knowledge_context: str | None = None,
) -> LlmAnalysisResult:
    """Return (root_cause, suggested_solution, source).

    Dispatches to the configured provider (``settings.LLM_PROVIDER``):
    ``copilot_sdk`` uses the enterprise GitHub Copilot SDK and ``offline_stub``
    forces the deterministic local heuristic. ``knowledge_context`` (optional)
    carries curated, trusted product summaries presented separately from the
    untrusted log excerpt.
    """
    provider = (settings.LLM_PROVIDER or "copilot_sdk").lower()
    if provider == "offline_stub":
        root, solution, source = _offline_stub(error_code, error_message)
        return LlmAnalysisResult(
            root_cause=root,
            suggested_solution=solution,
            source=source,
            metrics=LlmUsageMetrics(provider="offline_stub"),
        )
    # Enterprise Copilot is the only remaining live AI provider.
    from . import copilot_client

    return copilot_client.analyze_with_metrics(
        error_code, error_message, snippet, knowledge_context
    )


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


class CopilotSdkProvider:
    """Enterprise GitHub Copilot SDK provider (requires ``copilot auth login``)."""

    def analyze(
        self,
        error_code: str | None,
        error_message: str | None,
        snippet: str,
    ) -> tuple[str, str, str]:
        from . import copilot_client  # noqa: PLC0415

        return copilot_client.analyze(error_code, error_message, snippet)
