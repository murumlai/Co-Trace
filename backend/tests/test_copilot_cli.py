"""Tests for the local GitHub Copilot CLI gateway configuration and transport."""
from __future__ import annotations

import os
import stat

import pytest

from app.config import COPILOT_ENTERPRISE_HOST, resolve_copilot_cli_executable, settings


@pytest.fixture
def fake_cli_executable(tmp_path):
    exe = tmp_path / ("copilot.exe" if os.name == "nt" else "copilot")
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    if os.name != "nt":
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


@pytest.fixture
def cli_configured(monkeypatch, fake_cli_executable):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "copilot_cli")
    monkeypatch.setattr(settings, "COPILOT_GH_HOST", COPILOT_ENTERPRISE_HOST)
    monkeypatch.setattr(settings, "COPILOT_CLI_PATH", fake_cli_executable)
    monkeypatch.setattr(settings, "COPILOT_CLI_TIMEOUT_S", 90.0)
    monkeypatch.setattr(settings, "COPILOT_CLI_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(settings, "COPILOT_CLI_CLEANUP_SESSION", True)
    monkeypatch.setattr(settings, "COPILOT_CLI_REASONING_EFFORT", "")
    monkeypatch.setattr(settings, "COPILOT_MAX_RESPONSE_BYTES", 1024 * 1024)
    monkeypatch.setattr(settings, "COPILOT_PROXY", "")
    monkeypatch.setattr(settings, "COPILOT_CA_BUNDLE", "")
    # No PAT or HTTP auth mode is required for copilot_cli.
    monkeypatch.setattr(settings, "COPILOT_GITHUB_TOKEN", "")
    monkeypatch.setattr(settings, "COPILOT_AUTH_MODE", "")
    return settings


def test_copilot_cli_validates_without_pat(cli_configured):
    cli_configured.validate_enterprise_only()
    assert cli_configured.LLM_PROVIDER == "copilot_cli"


def test_copilot_cli_rejects_public_github_host(cli_configured, monkeypatch):
    for host in ("", "github.com", "api.github.com", "www.github.com"):
        monkeypatch.setattr(settings, "COPILOT_GH_HOST", host)
        with pytest.raises(RuntimeError, match="public GitHub host"):
            cli_configured.validate_enterprise_only()


def test_copilot_cli_rejects_missing_executable(cli_configured, monkeypatch, tmp_path):
    missing = str(tmp_path / "does-not-exist.exe")
    monkeypatch.setattr(settings, "COPILOT_CLI_PATH", missing)
    with pytest.raises(RuntimeError, match="existing file"):
        cli_configured.validate_enterprise_only()


def test_copilot_cli_resolves_command_via_path(monkeypatch, fake_cli_executable):
    monkeypatch.setattr("app.config.shutil.which", lambda name: fake_cli_executable if name == "copilot" else None)
    assert resolve_copilot_cli_executable("copilot") == os.path.abspath(fake_cli_executable)

    with pytest.raises(ValueError, match="not found on PATH"):
        resolve_copilot_cli_executable("missing-cli")


def test_copilot_cli_validates_numeric_and_effort_bounds(cli_configured, monkeypatch):
    monkeypatch.setattr(settings, "COPILOT_CLI_TIMEOUT_S", 0)
    with pytest.raises(RuntimeError, match="COPILOT_CLI_TIMEOUT_S"):
        cli_configured.validate_enterprise_only()

    monkeypatch.setattr(settings, "COPILOT_CLI_TIMEOUT_S", 30.0)
    monkeypatch.setattr(settings, "COPILOT_CLI_MAX_CONCURRENCY", 0)
    with pytest.raises(RuntimeError, match="COPILOT_CLI_MAX_CONCURRENCY"):
        cli_configured.validate_enterprise_only()

    monkeypatch.setattr(settings, "COPILOT_CLI_MAX_CONCURRENCY", 2)
    monkeypatch.setattr(settings, "COPILOT_CLI_REASONING_EFFORT", "turbo")
    with pytest.raises(RuntimeError, match="COPILOT_CLI_REASONING_EFFORT"):
        cli_configured.validate_enterprise_only()

    monkeypatch.setattr(settings, "COPILOT_CLI_REASONING_EFFORT", "medium")
    cli_configured.validate_enterprise_only()


def test_copilot_cli_validates_proxy_and_ca_bundle(cli_configured, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "COPILOT_PROXY", "socks5://proxy.local:1080")
    with pytest.raises(RuntimeError, match="COPILOT_PROXY"):
        cli_configured.validate_enterprise_only()

    monkeypatch.setattr(settings, "COPILOT_PROXY", "http://proxy-us.intel.com:912")
    monkeypatch.setattr(settings, "COPILOT_CA_BUNDLE", str(tmp_path / "missing.pem"))
    with pytest.raises(RuntimeError, match="COPILOT_CA_BUNDLE"):
        cli_configured.validate_enterprise_only()

    ca_file = tmp_path / "corp.pem"
    ca_file.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    monkeypatch.setattr(settings, "COPILOT_CA_BUNDLE", str(ca_file))
    cli_configured.validate_enterprise_only()


# ---------------------------------------------------------------------------
# Commit 2: Locked-down CLI transport tests (mocked subprocess)
# ---------------------------------------------------------------------------

def test_cli_transport_builds_locked_down_command_and_stdin(tmp_path, monkeypatch, fake_cli_executable):
    from app import copilot_cli_client as cli

    copilot_home = tmp_path / "copilot_home"
    monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
    monkeypatch.setenv("COPILOT_ALLOW_ALL", "true")
    monkeypatch.setenv("COPILOT_ASSISTED_APPROVAL", "1")

    captured: dict = {}

    def fake_runner(cmd, stdin_bytes, cwd, env, timeout_s):
        captured["cmd"] = cmd
        captured["stdin"] = stdin_bytes.decode("utf-8")
        captured["cwd"] = cwd
        captured["env"] = env
        captured["timeout_s"] = timeout_s

        # Simulate CLI writing usage JSON and a session directory.
        usage_path = cmd[cmd.index("--usage-output-file") + 1]
        session_id = cmd[cmd.index("--session-id") + 1]
        captured["session_dir"] = copilot_home / "session-state" / session_id
        captured["session_dir"].mkdir(parents=True, exist_ok=True)
        (captured["session_dir"] / "events.jsonl").write_text("{}\n", encoding="utf-8")

        with open(usage_path, "w", encoding="utf-8") as fh:
            fh.write(
                '{"modelMetrics":{"claude-sonnet-5":{"usage":{"inputTokens":321,"outputTokens":45}}},'
                '"lastCallInputTokens":321,"lastCallOutputTokens":45}'
            )
        return cli.CliProcessResult(returncode=0, stdout=b'{"root_cause":"ok"}\n', stderr=b"")

    transport = cli.CopilotCliTransport(
        executable=fake_cli_executable,
        timeout_s=45.0,
        reasoning_effort="low",
        proxy="http://proxy-us.intel.com:912",
        ca_bundle=str(tmp_path / "corp.pem"),
        runner=fake_runner,
    )
    completion = transport.complete("SYSTEM RULE", "USER DATA", "claude-sonnet-5")

    assert completion.text == '{"root_cause":"ok"}'
    assert completion.input_tokens == 321
    assert completion.output_tokens == 45

    cmd = captured["cmd"]
    assert cmd[0] == fake_cli_executable
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "claude-sonnet-5"
    assert "--silent" in cmd
    assert "--no-color" in cmd
    assert "--no-ask-user" in cmd
    assert "--disable-builtin-mcps" in cmd
    assert "--no-custom-instructions" in cmd
    assert "--disallow-temp-dir" in cmd
    assert "--no-auto-update" in cmd
    assert "--disable-client-telemetry" in cmd
    assert "--sync-session=off" in cmd
    assert cmd[cmd.index("--available-tools") + 1] == ""
    assert cmd[cmd.index("--reasoning-effort") + 1] == "low"
    # Prompt must travel via stdin, never in CLI arguments.
    assert "SYSTEM RULE" not in " ".join(cmd)
    assert "USER DATA" not in " ".join(cmd)
    assert "SYSTEM RULE" in captured["stdin"]
    assert "USER DATA" in captured["stdin"]
    # Ambient tool-approval env vars must be stripped.
    assert "COPILOT_ALLOW_ALL" not in captured["env"]
    assert "COPILOT_ASSISTED_APPROVAL" not in captured["env"]
    assert captured["env"]["COPILOT_AUTO_UPDATE"] == "false"
    assert captured["env"]["HTTPS_PROXY"] == "http://proxy-us.intel.com:912"
    assert captured["env"]["NODE_EXTRA_CA_CERTS"] == str(tmp_path / "corp.pem")
    assert captured["timeout_s"] == 45.0
    # Ephemeral session directory and scratch cwd must be cleaned up.
    assert not captured["session_dir"].exists()
    assert not os.path.exists(captured["cwd"])


def test_cli_transport_rejects_option_like_model_name(fake_cli_executable):
    from app import copilot_cli_client as cli
    from app.copilot_client import CopilotConfigError

    transport = cli.CopilotCliTransport(executable=fake_cli_executable)
    with pytest.raises(CopilotConfigError, match="model name"):
        transport.complete("s", "u", "--allow-all")


def test_cli_transport_classifies_auth_config_and_transient_errors(fake_cli_executable):
    from app import copilot_cli_client as cli
    from app.copilot_client import CopilotAuthError, CopilotConfigError, CopilotTransientError

    cases = [
        (b"Error: not logged in. Run copilot login.", CopilotAuthError),
        (b'Execution failed: Model "gpt-5.4-mini" is not available.', CopilotConfigError),
        (b"503 Service Unavailable upstream", CopilotTransientError),
    ]
    for stderr_bytes, expected_exc in cases:
        transport = cli.CopilotCliTransport(
            executable=fake_cli_executable,
            runner=lambda *_a, _err=stderr_bytes: cli.CliProcessResult(1, b"", _err),
        )
        with pytest.raises(expected_exc):
            transport.complete("sys", "usr", "claude-sonnet-5")


def test_cli_transport_redacts_tokens_from_error_stderr(fake_cli_executable):
    from app import copilot_cli_client as cli
    from app.copilot_client import CopilotAuthError

    secret = "github_pat_11ABCDEF1234567890_SECRET"
    transport = cli.CopilotCliTransport(
        executable=fake_cli_executable,
        runner=lambda *_a: cli.CliProcessResult(1, b"", f"Unauthorized token={secret}".encode()),
    )
    with pytest.raises(CopilotAuthError) as exc_info:
        transport.complete("sys", "usr", "claude-sonnet-5")
    assert secret not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


def test_cli_transport_enforces_response_size_and_non_empty_output(fake_cli_executable):
    from app import copilot_cli_client as cli
    from app.copilot_client import CopilotResponseError

    oversized = cli.CopilotCliTransport(
        executable=fake_cli_executable,
        max_response_bytes=16,
        runner=lambda *_a: cli.CliProcessResult(0, b"x" * 32, b""),
    )
    with pytest.raises(CopilotResponseError, match="exceeded"):
        oversized.complete("sys", "usr", "claude-sonnet-5")

    empty = cli.CopilotCliTransport(
        executable=fake_cli_executable,
        runner=lambda *_a: cli.CliProcessResult(0, b"   \n", b""),
    )
    with pytest.raises(CopilotResponseError, match="empty"):
        empty.complete("sys", "usr", "claude-sonnet-5")


def test_cli_transport_falls_back_to_last_call_tokens_and_none(fake_cli_executable):
    from app import copilot_cli_client as cli

    def runner_last_call(cmd, *_a):
        usage_path = cmd[cmd.index("--usage-output-file") + 1]
        with open(usage_path, "w", encoding="utf-8") as fh:
            fh.write('{"modelMetrics":{},"lastCallInputTokens":111,"lastCallOutputTokens":22}')
        return cli.CliProcessResult(0, b'{"ok":true}', b"")

    t1 = cli.CopilotCliTransport(executable=fake_cli_executable, runner=runner_last_call)
    c1 = t1.complete("s", "u", "auto")
    assert (c1.input_tokens, c1.output_tokens) == (111, 22)

    t2 = cli.CopilotCliTransport(
        executable=fake_cli_executable,
        runner=lambda *_a: cli.CliProcessResult(0, b'{"ok":true}', b""),
    )
    c2 = t2.complete("s", "u", "auto")
    assert (c2.input_tokens, c2.output_tokens) == (None, None)


def test_cli_transport_limits_concurrency(fake_cli_executable):
    import threading
    import time

    from app import copilot_cli_client as cli

    active = 0
    peak = 0
    lock = threading.Lock()

    def slow_runner(*_a):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return cli.CliProcessResult(0, b'{"ok":true}', b"")

    transport = cli.CopilotCliTransport(
        executable=fake_cli_executable,
        max_concurrency=1,
        runner=slow_runner,
    )
    threads = [threading.Thread(target=transport.complete, args=("s", "u", "auto")) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1


def test_cli_module_is_available_without_spawning(cli_configured, monkeypatch):
    from app import copilot_cli_client as cli

    cli.close()
    assert cli.is_available() is True
    assert cli._transport is None

    monkeypatch.setattr(settings, "LLM_PROVIDER", "offline_stub")
    assert cli.is_available() is False


# ---------------------------------------------------------------------------
# Commit 3: Shared diagnosis, cache, progress, and summarizer wiring
# ---------------------------------------------------------------------------

def test_copilot_client_dispatches_to_cli_and_records_metrics(cli_configured, monkeypatch):
    from app import copilot_cli_client as cli
    from app import copilot_client as cc
    from app import llm_client

    monkeypatch.setattr(settings, "COPILOT_MINI_MODEL", "auto")
    monkeypatch.setattr(settings, "COPILOT_REASONING_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(settings, "COPILOT_ENABLE_MINI_ENRICH", True)
    monkeypatch.setattr(settings, "COPILOT_MINI_MIN_CONTEXT_CHARS", 10)

    calls: list[str] = []

    def fake_cli_complete(system_prompt, user_prompt, model):
        calls.append(model)
        if model == "auto":
            return cc.CopilotCompletion(
                '{"summary":"rail drop","category":"power","observed_signals":["VDD=0V"],"hints":["check VR"],"confidence":"high"}',
                input_tokens=120,
                output_tokens=30,
            )
        return cc.CopilotCompletion(
            '{"root_cause":"Power rail collapsed","suggested_solution":"Inspect VR module","confidence":0.85}',
            input_tokens=450,
            output_tokens=60,
        )

    monkeypatch.setattr(cli, "complete", fake_cli_complete)

    assert cc.is_available() is True
    assert cc.is_cli_available() is True
    assert cc.is_http_available() is False

    result = llm_client.analyze_with_metrics("E_PWR", "Voltage rail 0V", "VDD dropped to 0.00V on step 4")
    assert calls == ["auto", "claude-sonnet-5"]
    assert result.source == "llm"
    assert result.root_cause == "Power rail collapsed"
    assert result.suggested_solution == "Inspect VR module"
    assert result.confidence == 0.85
    assert result.metrics.provider == "copilot_cli"
    assert result.metrics.mini.input_tokens == 120
    assert result.metrics.mini.output_tokens == 30
    assert result.metrics.mini.token_counts_estimated is False
    assert result.metrics.reasoning.input_tokens == 450
    assert result.metrics.reasoning.output_tokens == 60
    assert result.metrics.reasoning.token_counts_estimated is False


def test_analysis_cache_key_is_shared_between_http_and_cli(monkeypatch):
    from app import analysis_cache

    monkeypatch.setattr(settings, "COPILOT_MINI_MODEL", "auto")
    monkeypatch.setattr(settings, "COPILOT_REASONING_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(settings, "COPILOT_ENABLE_MINI_ENRICH", True)
    key_args = dict(
        error_code="E1",
        error_message="msg",
        context="ctx",
        context_source="debug_excerpt",
        signature="sig",
    )

    monkeypatch.setattr(settings, "LLM_PROVIDER", "copilot_http")
    http_key = analysis_cache.make_key(**key_args)

    monkeypatch.setattr(settings, "LLM_PROVIDER", "copilot_cli")
    cli_key = analysis_cache.make_key(**key_args)

    assert cli_key == http_key
    assert analysis_cache._cache_provider() == "copilot_sdk"


def test_orchestrator_progress_uses_cli_timeout_hint(cli_configured, monkeypatch):
    from app import orchestrator

    class DummyJob:
        cancel_requested = False
        processed = 0
        total = 1
        stage = ""
        message = ""

        def save(self):
            pass

    monkeypatch.setattr(settings, "COPILOT_ENABLE_MINI_ENRICH", False)
    monkeypatch.setattr(settings, "COPILOT_CLI_TIMEOUT_S", 75.0)
    job = DummyJob()
    updater = orchestrator._analysis_progress_updater(job)
    updater(0, 3, "Analyzing failures")
    assert "1 Copilot call" in job.message
    assert "up to 75s per uncached signature" in job.message


def test_knowledge_summarizer_uses_copilot_cli_when_configured(cli_configured, monkeypatch):
    from app import copilot_cli_client as cli
    from app import copilot_client as cc
    from app.knowledge import summarizer

    monkeypatch.setattr(settings, "PRODUCT_KNOWLEDGE_SUMMARY_MODEL", "auto")
    monkeypatch.setattr(
        cli,
        "complete",
        lambda sys_p, usr_p, model: cc.CopilotCompletion(f'{{"summary":"via {model}"}}'),
    )
    assert summarizer.is_llm_backend_available() is True
    assert summarizer._default_chat("sys", "usr") == '{"summary":"via auto"}'


# ---------------------------------------------------------------------------
# Commit 4: Health endpoint and local-only startup warning
# ---------------------------------------------------------------------------

def test_health_endpoint_reports_copilot_cli_readiness(cli_configured):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_provider"] == "copilot_cli"
    assert body["llm_auth"] == {
        "copilot_http_configured": False,
        "copilot_cli_configured": True,
        "copilot_token_configured": False,
    }


def test_run_backend_warns_only_for_non_loopback_copilot_cli():
    import importlib.util
    from pathlib import Path

    script_path = Path(__file__).resolve().parents[1] / "run_backend.py"
    spec = importlib.util.spec_from_file_location("cotrace_run_backend_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    assert mod._non_loopback_cli_warning("127.0.0.1", "copilot_cli") is None
    assert mod._non_loopback_cli_warning("localhost", "copilot_cli") is None
    assert mod._non_loopback_cli_warning("0.0.0.0", "copilot_http") is None
    warning = mod._non_loopback_cli_warning("0.0.0.0", "copilot_cli")
    assert warning is not None and "loopback" in warning



