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


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class StepRecord(BaseModel):
    name: str
    result: Result = "UNKNOWN"
    duration_s: float = 0.0


class EvidenceReference(BaseModel):
    kind: Literal["log_excerpt", "knowledge_section"]
    reference_id: str
    label: str
    source_type: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    section_id: Optional[str] = None
    product_code: Optional[str] = None
    heading: Optional[str] = None
    source_filename: Optional[str] = None


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
    debuglog_status: Optional[str] = None
    debuglog_message: Optional[str] = None
    debug_excerpt: Optional[str] = None
    ftrunner_snippet: Optional[str] = None

    # Engineer analysis (populated lazily for failed units only)
    signature: Optional[str] = None
    root_cause: Optional[str] = None
    suggested_solution: Optional[str] = None
    redacted_snippet: Optional[str] = None
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    analysis_source: Optional[str] = None  # "llm" | "stub" | "cached" | "local-cache" | "playbook"
    analysis_context_source: Optional[str] = None  # "debug_excerpt" | "ftrunner_snippet" | "error_message"
    analysis_cache_key: Optional[str] = None
    playbook_id: Optional[str] = None
    confidence: Optional[float] = None
    root_cause_category: Optional[str] = None
    evidence_summary: Optional[str] = None
    next_debug_action: Optional[str] = None
    likely_owner: Optional[str] = None
    safety_or_escape_risk: Optional[str] = None
    needs_more_evidence: Optional[bool] = None

    # Product-aware diagnosis metadata (populated during failure analysis)
    knowledge_used: bool = False
    knowledge_hash: Optional[str] = None
    knowledge_match_status: Optional[str] = None
    knowledge_section_ids: list[str] = Field(default_factory=list)
    knowledge_categories: list[str] = Field(default_factory=list)

    # Acronym-glossary metadata (populated during failure analysis)
    acronyms_used: list[str] = Field(default_factory=list)
    unknown_acronyms: list[str] = Field(default_factory=list)
    acronym_glossary_hash: Optional[str] = None


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
    playbook_hits: int = 0
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

    def record_playbook_hit(self) -> None:
        self.playbook_hits += 1
        self.calls_skipped_by_cache += 1

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
        self.playbook_hits += other.playbook_hits
        self.mini.merge(other.mini)
        self.reasoning.merge(other.reasoning)
        self._refresh_totals()

    def _refresh_totals(self) -> None:
        self.total_calls = self.mini.calls + self.reasoning.calls
        self.total_estimated_credits = round(
            self.mini.estimated_credits + self.reasoning.estimated_credits,
            4,
        )


class AnalysisResult(BaseModel):
    root_cause: str
    suggested_solution: str
    source: str
    playbook_id: Optional[str] = None
    confidence: Optional[float] = None
    root_cause_category: Optional[str] = None
    evidence_summary: Optional[str] = None
    next_debug_action: Optional[str] = None
    likely_owner: Optional[str] = None
    safety_or_escape_risk: Optional[str] = None
    needs_more_evidence: Optional[bool] = None

    def as_tuple(self) -> tuple[str, str, str]:
        return self.root_cause, self.suggested_solution, self.source


class LlmAnalysisResult(AnalysisResult):
    metrics: LlmUsageMetrics = Field(default_factory=LlmUsageMetrics)

    def without_metrics(self) -> AnalysisResult:
        return AnalysisResult(**self.model_dump(exclude={"metrics"}))


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
    stage: Optional[str] = None


class BatchMetadata(BaseModel):
    display_name: Optional[str] = None
    source_file_count: Optional[int] = None
    source_zip_count: Optional[int] = None
    discovered_run_count: Optional[int] = None
    included_run_count: Optional[int] = None
    parse_excluded_count: Optional[int] = None
    incomplete_folder_count: Optional[int] = None
    unknown_result_count: Optional[int] = None
    missing_debuglog_count: Optional[int] = None
    product_codes: list[str] = Field(default_factory=list)
    observed_start_time: Optional[str] = None
    observed_end_time: Optional[str] = None
    timestamp_timezone: Literal["offset", "unspecified", "mixed", "unavailable"] = "unavailable"
    batch_fingerprint: Optional[str] = None


class JobStatus(BaseModel):
    job_id: str
    status: JobState = "pending"
    progress: JobProgress = Field(default_factory=JobProgress)
    message: str = ""
    elapsed_s: float = 0.0
    unit_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    llm_metrics: LlmUsageMetrics = Field(default_factory=LlmUsageMetrics)
    batch: BatchMetadata = Field(default_factory=BatchMetadata)


class JobSummary(BaseModel):
    job_id: str
    display_name: str
    status: JobState
    progress: JobProgress = Field(default_factory=JobProgress)
    message: str = ""
    created_at: float
    completed_at: Optional[float] = None
    result_available: bool = False
    unit_count: int = 0
    batch: BatchMetadata = Field(default_factory=BatchMetadata)


class JobListResponse(BaseModel):
    items: list[JobSummary] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class FrontendLogRequest(BaseModel):
    level: str = "info"
    message: str
    context: dict = Field(default_factory=dict)


FeedbackAction = Literal["helpful", "not_helpful", "fixed_after_action", "not_root_cause"]


class FeedbackCreateRequest(BaseModel):
    unit_id: str
    action: FeedbackAction
    note: Optional[str] = Field(default=None, max_length=2000)


class FeedbackEntry(BaseModel):
    feedback_id: str
    job_id: str
    owner_id: str
    owner_login: str
    unit_id: str
    signature: Optional[str] = None
    cache_key: Optional[str] = None
    product_code: Optional[str] = None
    op_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    failing_step: Optional[str] = None
    analysis_source: Optional[str] = None
    action: FeedbackAction
    note: Optional[str] = None
    created_at: str
    expires_at: float


class AcronymUpsertRequest(BaseModel):
    """Create/update a glossary entry from the review UI."""

    acronym: str
    definition: Optional[str] = None
    product_code: Optional[str] = None
    status: Literal["approved", "needs_review", "rejected"] = "approved"
    notes: Optional[str] = None
