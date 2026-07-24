"""Pydantic schemas shared across the API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Result = Literal["PASS", "FAIL", "UNKNOWN"]
JobState = Literal["pending", "running", "done", "error", "cancelled"]
DeviceClass = Literal["pan", "aic", "unknown"]

# Per-serial outcome across all of a unit's test attempts:
#   first_pass  - passed on the first attempt, never failed (no LLM needed)
#   retry_pass  - failed one or more times, then passed on the last attempt
#   fail        - the latest attempt is still failing
#   unknown     - the latest attempt result is UNKNOWN
Classification = Literal["first_pass", "retry_pass", "fail", "unknown"]
LlmModelRole = Literal["mini", "reasoning"]


class StepRecord(BaseModel):
    name: str
    result: Result = "UNKNOWN"
    duration_s: float = 0.0


class UnitRecord(BaseModel):
    """Normalized per-unit record emitted by the preprocessor."""

    unit_id: str                       # stable id for a single test run
    serial_number: Optional[str] = None
    product_code: Optional[str] = None
    lot_id: Optional[str] = None
    op_id: Optional[str] = None
    station_id: Optional[str] = None
    host: Optional[str] = None
    start_time: Optional[str] = None   # ISO-8601
    end_time: Optional[str] = None     # ISO-8601
    duration_s: float = 0.0
    result: Result = "UNKNOWN"
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    failing_step: Optional[str] = None
    steps: list[StepRecord] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    run_folder: str = ""

    # FTRunner-primary metadata (Phase 4)
    tp_name: Optional[str] = None
    tp_version: Optional[str] = None
    test_mode: Optional[str] = None
    device_class: DeviceClass = "unknown"
    has_debuglog: bool = False
    debug_excerpt: Optional[str] = None
    ftrunner_snippet: Optional[str] = None

    # Engineer analysis (populated lazily for failed units only)
    signature: Optional[str] = None
    root_cause: Optional[str] = None
    suggested_solution: Optional[str] = None
    redacted_snippet: Optional[str] = None
    analysis_source: Optional[str] = None  # "llm" | "stub" | "cached" | "local-cache"
    analysis_context_source: Optional[str] = None  # "debug_excerpt" | "ftrunner_snippet" | "error_message"
    analysis_cache_key: Optional[str] = None


class LlmModelMetrics(BaseModel):
    model: Optional[str] = None
    calls: int = 0
    errors: int = 0
    input_chars: int = 0
    output_chars: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    token_counts_estimated: bool = False
    estimated_credits: float = 0.0

    def add_call(
        self,
        *,
        model: str | None,
        input_chars: int,
        output_chars: int,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        token_counts_estimated: bool = True,
        credit_tokens_per_credit: int = 1000,
    ) -> None:
        if model:
            self.model = model
        self.calls += 1
        self.input_chars += max(0, input_chars)
        self.output_chars += max(0, output_chars)
        if input_tokens is None:
            input_tokens = _estimate_tokens(input_chars)
            token_counts_estimated = True
        if output_tokens is None:
            output_tokens = _estimate_tokens(output_chars)
            token_counts_estimated = True
        self.input_tokens += max(0, input_tokens)
        self.output_tokens += max(0, output_tokens)
        self.token_counts_estimated = self.token_counts_estimated or token_counts_estimated
        self.estimated_credits = round(
            self.estimated_credits
            + ((max(0, input_tokens) + max(0, output_tokens)) / max(1, credit_tokens_per_credit)),
            4,
        )

    def add_error(self, *, model: str | None = None) -> None:
        if model:
            self.model = model
        self.errors += 1

    def merge(self, other: "LlmModelMetrics") -> None:
        if other.model:
            self.model = other.model
        self.calls += other.calls
        self.errors += other.errors
        self.input_chars += other.input_chars
        self.output_chars += other.output_chars
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.token_counts_estimated = self.token_counts_estimated or other.token_counts_estimated
        self.estimated_credits = round(self.estimated_credits + other.estimated_credits, 4)


class LlmUsageMetrics(BaseModel):
    provider: str = ""
    credit_basis: str = "Estimated token credits; default 1 credit per 1,000 tokens."
    cache_hits: int = 0
    local_cache_hits: int = 0
    disk_cache_hits: int = 0
    calls_skipped_by_cache: int = 0
    mini: LlmModelMetrics = Field(default_factory=LlmModelMetrics)
    reasoning: LlmModelMetrics = Field(default_factory=LlmModelMetrics)
    total_calls: int = 0
    total_estimated_credits: float = 0.0

    def record_cache_hit(self, source: str) -> None:
        self.cache_hits += 1
        self.calls_skipped_by_cache += 1
        if source == "local-cache":
            self.disk_cache_hits += 1
        else:
            self.local_cache_hits += 1

    def add_model_call(
        self,
        role: LlmModelRole,
        *,
        model: str | None,
        input_chars: int,
        output_chars: int,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        token_counts_estimated: bool = True,
        credit_tokens_per_credit: int = 1000,
    ) -> None:
        target = self.mini if role == "mini" else self.reasoning
        target.add_call(
            model=model,
            input_chars=input_chars,
            output_chars=output_chars,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            token_counts_estimated=token_counts_estimated,
            credit_tokens_per_credit=credit_tokens_per_credit,
        )
        self._refresh_totals()

    def add_model_error(self, role: LlmModelRole, *, model: str | None = None) -> None:
        target = self.mini if role == "mini" else self.reasoning
        target.add_error(model=model)

    def merge(self, other: "LlmUsageMetrics") -> None:
        if other.provider:
            self.provider = other.provider
        self.cache_hits += other.cache_hits
        self.local_cache_hits += other.local_cache_hits
        self.disk_cache_hits += other.disk_cache_hits
        self.calls_skipped_by_cache += other.calls_skipped_by_cache
        self.mini.merge(other.mini)
        self.reasoning.merge(other.reasoning)
        self._refresh_totals()

    def _refresh_totals(self) -> None:
        self.total_calls = self.mini.calls + self.reasoning.calls
        self.total_estimated_credits = round(
            self.mini.estimated_credits + self.reasoning.estimated_credits,
            4,
        )


class LlmAnalysisResult(BaseModel):
    root_cause: str
    suggested_solution: str
    source: str
    metrics: LlmUsageMetrics = Field(default_factory=LlmUsageMetrics)

    def as_tuple(self) -> tuple[str, str, str]:
        return self.root_cause, self.suggested_solution, self.source


def _estimate_tokens(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, round(char_count / 4))


class SerialUnitGroup(BaseModel):
    """One physical unit (serial number) with all of its test attempts grouped.

    The Engineer view shows one of these per serial so first-test-pass,
    retry-pass, and consistently-failing units can be told apart. ``failures``
    holds the failing attempts (chronological) carrying the LLM root-cause /
    solution; ``final`` is the latest attempt used for the headline result and
    identity metadata.
    """

    serial_number: Optional[str] = None
    unit_id: str                        # final attempt's unit_id (stable key)
    classification: Classification
    result: Result                      # result of the final attempt
    attempt_count: int
    failure_count: int
    final: UnitRecord
    failures: list["UnitRecord"] = Field(default_factory=list)


class JobProgress(BaseModel):
    processed: int = 0
    total: int = 0


class JobStatus(BaseModel):
    job_id: str
    status: JobState = "pending"
    progress: JobProgress = Field(default_factory=JobProgress)
    message: str = ""
    unit_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    llm_metrics: LlmUsageMetrics = Field(default_factory=LlmUsageMetrics)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class FrontendLogRequest(BaseModel):
    level: str = "info"
    message: str
    context: dict = Field(default_factory=dict)
