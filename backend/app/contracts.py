"""Narrow structural contracts for the Co_Trace backend.

Each protocol expresses only what a specific *client* needs from a
collaborator — no fat interfaces. Concrete implementations of these contracts
live in the existing modules and will be wired together in a composition root
(Phase 7). Nothing here changes runtime behavior.

Style: ``typing.Protocol`` (structural / duck-typed), matching the existing
``AuthProvider`` and ``Preprocessor`` conventions in auth.py and
preprocessor.py.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol

# Forward references avoid circular imports; callers import the concrete types.
from .models import LlmAnalysisResult, UnitRecord


# ---------------------------------------------------------------------------
# Type aliases re-exported for convenience
# ---------------------------------------------------------------------------

AnalysisProgress = Callable[[int, int, str], None]
"""(processed: int, total: int, message: str) → None"""

AnalyzeFailure = Callable[[str | None, str | None, str], tuple[str, str, str] | LlmAnalysisResult]
"""(error_code, error_message, snippet) → tuple or rich LLM analysis result."""


# ---------------------------------------------------------------------------
# Job lifecycle contracts
# ---------------------------------------------------------------------------

class JobRepository(Protocol):
    """What the orchestrator and API routes need from the job store.

    Intentionally narrow: only the operations used by current callers.
    """

    def get(self, job_id: str) -> Any | None:
        """Return the job for ``job_id``, or ``None`` if absent or expired."""
        ...

    def create(self, job_id: str, workdir: str) -> Any:
        """Create, persist, and return a new pending job."""
        ...

    def request_cancel(self, job_id: str) -> Any | None:
        """Mark a job for cancellation; return the job or ``None`` if not found."""
        ...

    def all(self) -> list[Any]:
        """Return all non-expired jobs currently tracked."""
        ...


class JobStateStore(Protocol):
    """Persistence seam used by ``Job`` and ``JobRegistry``.

    Separates disk I/O from in-memory job state so ``Job`` can be a pure
    data/domain object and tests can use in-memory stores.
    """

    def save(self, job: Any) -> None:
        """Atomically persist the current job state."""
        ...

    def load_all(self, work_dir: str) -> Iterable[Any]:
        """Scan ``work_dir`` and yield restored ``Job`` objects.

        Jobs that were ``running`` when the process died must be yielded with
        their status already promoted to ``"error"``. Expired entries must be
        silently deleted and not yielded.
        """
        ...

    def delete(self, job: Any) -> None:
        """Remove all persisted state for ``job`` (best-effort)."""
        ...


# ---------------------------------------------------------------------------
# Preprocessing contracts
# ---------------------------------------------------------------------------

class Preprocessor(Protocol):
    """Converts a batch upload root into normalised ``UnitRecord`` objects.

    (Mirrors the existing duck-typed ``Preprocessor`` protocol in
    ``preprocessor.py``; this copy lives at the contracts layer so downstream
    collaborators can depend on the interface without importing the concrete
    module.)
    """

    def iter_run_folders(self, root: str) -> Iterable[str]:
        """Yield paths to directories that each contain one unit test run."""
        ...

    def process_run_folder(self, folder: str, root: str) -> UnitRecord | None:
        """Parse one run folder and return a normalised record, or ``None``."""
        ...

    def process_folder(self, root: str) -> list[UnitRecord]:
        """Walk ``root`` and return one normalised record per run folder."""
        ...

    def find_incomplete_folders(self, root: str) -> list[str]:
        """Return relative paths of run folders that have no recognisable log files.

        Surfaced as UI warnings — not treated as errors.
        """
        ...


class ArtifactWriter(Protocol):
    """Writes the per-product preprocessed JSON artifacts for a completed job."""

    def write(
        self,
        records: list[UnitRecord],
        output_dir: str,
        warnings: list[str] | None = None,
    ) -> list[str]:
        """Group ``records`` by product code, write JSON files into ``output_dir``,
        and return the list of written file paths.
        """
        ...


# ---------------------------------------------------------------------------
# Analysis contracts
# ---------------------------------------------------------------------------

class LLMProvider(Protocol):
    """One LLM back-end that can analyse a single failure context."""

    def analyze(
        self,
        error_code: str | None,
        error_message: str | None,
        snippet: str,
    ) -> tuple[str, str, str]:
        """Return ``(root_cause, suggested_solution, source)``."""
        ...


class AnalysisCache(Protocol):
    """Persistent cache of LLM analysis results, keyed by redacted context."""

    def make_key(
        self,
        *,
        error_code: str | None,
        error_message: str | None,
        context: str,
        context_source: str,
        signature: str,
    ) -> str:
        """Derive a deterministic cache key from the analysis inputs."""
        ...

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """Return a cached entry, or ``None`` on a miss.

        Implementations may update ``last_used_at`` / ``hit_count`` as a
        side-effect.
        """
        ...

    def put(
        self,
        cache_key: str,
        *,
        root_cause: str,
        suggested_solution: str,
        source: str,
        metadata: dict[str, Any],
    ) -> None:
        """Store an analysis result (only for ``source == "llm"`` entries)."""
        ...


class FailureAnalyzer(Protocol):
    """Orchestrates per-job failure analysis using a cache and LLM provider."""

    def analyze_job(
        self,
        job: Any,
        progress_callback: AnalysisProgress | None = None,
    ) -> None:
        """Populate ``root_cause`` / ``suggested_solution`` on all FAIL records."""
        ...


# ---------------------------------------------------------------------------
# Cleanup contract
# ---------------------------------------------------------------------------

class PayloadCleaner(Protocol):
    """Removes per-job payload files after processing (when cleanup is enabled)."""

    def cleanup(self, workdir: str) -> list[str]:
        """Remove everything in ``workdir`` except ``job_state.json``.

        Returns the names of removed items. Must be a no-op when cleanup is
        disabled via configuration.
        """
        ...
