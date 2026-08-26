from __future__ import annotations

from typing import Any

from app.analyzer import analyze_job
from app import copilot_client
from app.job_registry import Job
from app.models import LlmAnalysisResult, LlmUsageMetrics, UnitRecord


class NoopCache:
    def make_key(self, **kwargs: Any) -> str:
        return "cache-key"

    def get(self, cache_key: str) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    def put(self, cache_key: str, **kwargs: Any) -> None:  # noqa: ARG002
        return None


class HitCache(NoopCache):
    def get(self, cache_key: str) -> dict[str, Any] | None:  # noqa: ARG002
        return {"root_cause": "cached root", "suggested_solution": "cached solution"}


def _fail_rec(unit_id: str, error_code: str = "E001", error_message: str = "Voltage fault") -> UnitRecord:
    return UnitRecord(unit_id=unit_id, result="FAIL", error_code=error_code, error_message=error_message, run_folder=unit_id)


def _job(records: list[UnitRecord]) -> Job:
    job = Job(job_id="metrics-job", workdir="")
    job.records = records
    return job


def test_copilot_client_receives_configured_github_token(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeConfig:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class FakeClient:
        def __init__(self, config: FakeConfig) -> None:
            self.config = config

    monkeypatch.setattr(copilot_client, "SubprocessConfig", FakeConfig)
    monkeypatch.setattr(copilot_client, "CopilotClient", FakeClient)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_GITHUB_TOKEN", "test-token")

    copilot_client._create_client()

    assert captured["github_token"] == "test-token"
    assert captured["env"]["HTTP_PROXY"] == copilot_client.settings.COPILOT_PROXY


def test_live_llm_metrics_are_separated_by_model_role() -> None:
    def rich_analyze(error_code: str | None, error_message: str | None, snippet: str) -> LlmAnalysisResult:  # noqa: ARG001
        metrics = LlmUsageMetrics(provider="copilot_sdk")
        metrics.add_model_call(
            "mini",
            model="gpt-5.4-mini",
            input_chars=4000,
            output_chars=800,
            credit_tokens_per_credit=1000,
        )
        metrics.add_model_call(
            "reasoning",
            model="claude-sonnet-4.6",
            input_chars=2000,
            output_chars=400,
            credit_tokens_per_credit=1000,
        )
        return LlmAnalysisResult(
            root_cause="root",
            suggested_solution="solution",
            source="llm",
            metrics=metrics,
        )

    job = _job([_fail_rec("u1"), _fail_rec("u2")])
    analyze_job(job, analyze_failure=rich_analyze, cache=NoopCache())

    assert job.llm_metrics.provider == "copilot_sdk"
    assert job.llm_metrics.mini.model == "gpt-5.4-mini"
    assert job.llm_metrics.mini.calls == 1
    assert job.llm_metrics.reasoning.model == "claude-sonnet-4.6"
    assert job.llm_metrics.reasoning.calls == 1
    assert job.llm_metrics.total_calls == 2
    assert job.llm_metrics.cache_hits == 1
    assert job.llm_metrics.calls_skipped_by_cache == 1


def test_disk_cache_hit_records_skipped_llm_call() -> None:
    def should_not_call(error_code: str | None, error_message: str | None, snippet: str) -> LlmAnalysisResult:  # noqa: ARG001
        raise AssertionError("LLM should not be called on a disk cache hit")

    job = _job([_fail_rec("u1")])
    analyze_job(job, analyze_failure=should_not_call, cache=HitCache())

    assert job.llm_metrics.total_calls == 0
    assert job.llm_metrics.cache_hits == 1
    assert job.llm_metrics.disk_cache_hits == 1
    assert job.llm_metrics.calls_skipped_by_cache == 1


def test_copilot_auth_error_counts_mini_and_skips_reasoning(monkeypatch) -> None:
    attempted_models: list[str] = []

    async def fail_stream(prompt: str, model: str, system_prompt: str) -> str:  # noqa: ARG001
        attempted_models.append(model)
        raise RuntimeError("Execution failed: Error: Session was not created with authentication info or custom provider")

    monkeypatch.setattr(copilot_client, "_SDK_AVAILABLE", True)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_ENABLE_MINI_ENRICH", True)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_MINI_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(copilot_client.settings, "COPILOT_REASONING_MODEL", "claude-sonnet-4.6")
    monkeypatch.setattr(copilot_client, "_stream_once", fail_stream)

    result = copilot_client.analyze_with_metrics("E001", "Voltage fault", "Debug excerpt")

    assert result.source == "stub"
    assert "GITHUB_TOKEN" not in result.suggested_solution
    assert "authentication info" in result.suggested_solution
    assert result.metrics.provider == "copilot_sdk"
    assert result.metrics.mini.model == "gpt-5.4-mini"
    assert result.metrics.mini.calls == 1
    assert result.metrics.mini.errors == 1
    assert result.metrics.mini.input_chars > 0
    assert result.metrics.mini.output_chars == 0
    assert result.metrics.reasoning.calls == 0
    assert result.metrics.reasoning.errors == 0
    assert result.metrics.reasoning.input_chars == 0
    assert result.metrics.reasoning.output_chars == 0
    assert result.metrics.total_calls == 1
    assert attempted_models == ["gpt-5.4-mini"]


def test_copilot_mini_error_still_allows_reasoning_call(monkeypatch) -> None:
    async def stream_once(prompt: str, model: str, system_prompt: str) -> str:  # noqa: ARG001
        if model == "gpt-5.4-mini":
            raise RuntimeError("mini unavailable")
        return '{"root_cause":"reasoned root","suggested_solution":"reasoned solution"}'

    monkeypatch.setattr(copilot_client, "_SDK_AVAILABLE", True)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_ENABLE_MINI_ENRICH", True)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_MINI_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(copilot_client.settings, "COPILOT_REASONING_MODEL", "claude-sonnet-4.6")
    monkeypatch.setattr(copilot_client, "_stream_once", stream_once)

    result = copilot_client.analyze_with_metrics("E001", "Voltage fault", "Debug excerpt")

    assert result.source == "llm"
    assert result.root_cause == "reasoned root"
    assert result.suggested_solution == "reasoned solution"
    assert result.metrics.mini.calls == 1
    assert result.metrics.mini.errors == 1
    assert result.metrics.reasoning.calls == 1
    assert result.metrics.reasoning.errors == 0
    assert result.metrics.reasoning.output_chars > 0
    assert result.metrics.total_calls == 2
