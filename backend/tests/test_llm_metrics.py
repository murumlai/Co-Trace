from __future__ import annotations

from typing import Any

from app.analyzer import analyze_job
from app import copilot_client, orchestrator
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


def test_copilot_client_supports_sdk_1_keyword_options(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(copilot_client, "SubprocessConfig", None)
    monkeypatch.setattr(copilot_client, "CopilotClientOptions", None)
    monkeypatch.setattr(copilot_client, "CopilotClient", FakeClient)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_GITHUB_TOKEN", "")
    monkeypatch.setattr(copilot_client.settings, "COPILOT_GH_HOST", "intel-foundry.ghe.com")

    copilot_client._create_client()

    assert captured["env"]["COPILOT_GH_HOST"] == "intel-foundry.ghe.com"
    assert captured["github_token"] is None
    assert captured["use_logged_in_user"] is True


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
            model="claude-sonnet-5",
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
    assert job.llm_metrics.reasoning.model == "claude-sonnet-5"
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


def test_copilot_progress_message_accounts_for_conditional_mini(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator.settings, "LLM_PROVIDER", "copilot_sdk")
    monkeypatch.setattr(orchestrator.settings, "COPILOT_ENABLE_MINI_ENRICH", True)
    monkeypatch.setattr(orchestrator.settings, "COPILOT_MINI_MIN_CONTEXT_CHARS", 500)
    monkeypatch.setattr(orchestrator.settings, "COPILOT_TIMEOUT_S", 60)

    job = _job([])
    update = orchestrator._analysis_progress_updater(job)
    update(0, 3, "Analyzing uncached failure signature 1/3")

    assert "1-2 Copilot calls" in job.message
    assert "mini skips contexts below 500 chars" in job.message
    assert "up to 120s per uncached signature" in job.message

    monkeypatch.setattr(orchestrator.settings, "COPILOT_ENABLE_MINI_ENRICH", False)
    update(0, 3, "Analyzing uncached failure signature 1/3")

    assert "1 Copilot call" in job.message
    assert "up to 60s per uncached signature" in job.message


def test_copilot_auth_error_counts_mini_and_skips_reasoning(monkeypatch) -> None:
    attempted_models: list[str] = []

    async def fail_stream(prompt: str, model: str, system_prompt: str) -> str:  # noqa: ARG001
        attempted_models.append(model)
        raise RuntimeError("Execution failed: Error: Session was not created with authentication info or custom provider")

    monkeypatch.setattr(copilot_client, "_SDK_AVAILABLE", True)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_ENABLE_MINI_ENRICH", True)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_MINI_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(copilot_client.settings, "COPILOT_REASONING_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(copilot_client.settings, "COPILOT_MINI_MIN_CONTEXT_CHARS", 1)
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
    monkeypatch.setattr(copilot_client.settings, "COPILOT_REASONING_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(copilot_client.settings, "COPILOT_MINI_MIN_CONTEXT_CHARS", 1)
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


def test_copilot_short_context_skips_mini_and_calls_reasoning(monkeypatch) -> None:
    attempted: list[tuple[str, str, str]] = []

    async def stream_once(prompt: str, model: str, system_prompt: str) -> str:  # noqa: ARG001
        attempted.append((model, prompt, system_prompt))
        return '{"root_cause":"reasoned root","suggested_solution":"reasoned solution"}'

    monkeypatch.setattr(copilot_client, "_SDK_AVAILABLE", True)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_ENABLE_MINI_ENRICH", True)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_MINI_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(copilot_client.settings, "COPILOT_REASONING_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(copilot_client.settings, "COPILOT_MINI_MIN_CONTEXT_CHARS", 500)
    monkeypatch.setattr(copilot_client, "_stream_once", stream_once)

    result = copilot_client.analyze_with_metrics("E001", "Voltage fault", "short context")

    assert result.source == "llm"
    assert result.metrics.mini.calls == 0
    assert result.metrics.reasoning.calls == 1
    assert result.metrics.total_calls == 1
    assert [model for model, _, _ in attempted] == ["claude-sonnet-5"]
    assert attempted[0][2] == copilot_client._COMPACT_DIAGNOSE_SYSTEM_PROMPT
    assert len(attempted[0][2]) < len(copilot_client._DIAGNOSE_SYSTEM_PROMPT)


def test_copilot_long_context_runs_mini_then_reasoning(monkeypatch) -> None:
    attempted: list[tuple[str, str]] = []

    async def stream_once(prompt: str, model: str, system_prompt: str) -> str:  # noqa: ARG001
        attempted.append((model, system_prompt))
        if model == "gpt-5.4-mini":
            return '{"summary":"observed failure","category":"other","observed_signals":[],"hints":[],"confidence":"low"}'
        return '{"root_cause":"reasoned root","suggested_solution":"reasoned solution"}'

    monkeypatch.setattr(copilot_client, "_SDK_AVAILABLE", True)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_ENABLE_MINI_ENRICH", True)
    monkeypatch.setattr(copilot_client.settings, "COPILOT_MINI_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(copilot_client.settings, "COPILOT_REASONING_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(copilot_client.settings, "COPILOT_MINI_MIN_CONTEXT_CHARS", 500)
    monkeypatch.setattr(copilot_client, "_stream_once", stream_once)

    result = copilot_client.analyze_with_metrics("E001", "Voltage fault", "x" * 500)

    assert result.source == "llm"
    assert result.metrics.mini.calls == 1
    assert result.metrics.reasoning.calls == 1
    assert result.metrics.total_calls == 2
    assert [model for model, _ in attempted] == ["gpt-5.4-mini", "claude-sonnet-5"]
    assert attempted[1][1] == copilot_client._DIAGNOSE_SYSTEM_PROMPT
