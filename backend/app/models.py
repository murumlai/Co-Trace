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
