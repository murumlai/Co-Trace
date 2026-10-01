"""HTTPS Copilot transport: auth modes, refresh, retries, allowlist, TLS, redaction.

Every test uses ``httpx.MockTransport``; nothing contacts GitHub or needs a real PAT.
"""
from __future__ import annotations

import json
import logging
import ssl
import subprocess
import sys
import threading
import time

import httpx
import pytest

from app import analysis_cache, analyzer
from app import copilot_client as cc
from app.config import normalize_llm_provider, settings
from app.models import UnitRecord

PAT = "github_pat_TESTONLY0123456789abcdef"
EXCHANGED = "tid=exchanged0123;exp=1999999999;sku=enterprise"
TOKEN_PATH = "/copilot_internal/v2/token"
CHAT_PATH = "/chat/completions"
TOKEN_URL = f"https://api.copilot.test{TOKEN_PATH}"
API_BASE = "https://copilot-api.copilot.test"
ALLOWED = ["api.copilot.test", "copilot-api.copilot.test"]


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Recorder:
    """MockTransport handler replaying queued responses per path; the last item repeats."""

    def __init__(self, routes: dict[str, list]) -> None:
        self.routes = {path: list(items) for path, items in routes.items()}
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
            queue = self.routes[request.url.path]
            item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, httpx.Response):
            return item
        return item(request)

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


def _completion(content: str = '{"root_cause":"r","suggested_solution":"s"}', usage: dict | None = None) -> httpx.Response:
    body: dict = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def _exchange(token: str = EXCHANGED, refresh_in: int | None = 1500, api: str | None = API_BASE) -> httpx.Response:
    body: dict = {"token": token}
    if refresh_in is not None:
        body["refresh_in"] = refresh_in
    if api is not None:
        body["endpoints"] = {"api": api}
    return httpx.Response(200, json=body)


def _client(recorder: Recorder, follow_redirects: bool = False) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(recorder), follow_redirects=follow_redirects)


def _exchange_provider(client: httpx.Client, clock: Clock, **overrides) -> cc.ExchangeTokenProvider:
    kwargs = dict(
        pat=PAT,
        token_url=TOKEN_URL,
        api_base_override="",
        allowed_hosts=ALLOWED,
        refresh_skew_s=120,
        max_response_bytes=65536,
        headers={"User-Agent": "test"},
        clock=clock,
    )
    kwargs.update(overrides)
    return cc.ExchangeTokenProvider(client, **kwargs)


def _http(client: httpx.Client, tokens, clock: Clock, timeout_s: float = 30.0, **kwargs) -> cc.CopilotHttpClient:
    return cc.CopilotHttpClient(client, tokens, timeout_s=timeout_s, max_response_bytes=65536, clock=clock, **kwargs)


@pytest.fixture()
def configured(monkeypatch):
    values = {
        "LLM_PROVIDER": "copilot_http",
        "COPILOT_GITHUB_TOKEN": PAT,
        "COPILOT_AUTH_MODE": "pat_bearer",
        "COPILOT_TOKEN_URL": "",
        "COPILOT_API_BASE_URL": API_BASE,
        "COPILOT_ALLOWED_HOSTS": list(ALLOWED),
        "COPILOT_INTEGRATION_ID": "",
        "COPILOT_GH_HOST": "intel-foundry.ghe.com",
        "COPILOT_PROXY": "http://proxy.test:912",
        "COPILOT_TLS_TRUST": "system",
        "COPILOT_CA_BUNDLE": "",
        "COPILOT_TIMEOUT_S": 30.0,
        "COPILOT_TOKEN_REFRESH_SKEW": 120.0,
        "COPILOT_MAX_RESPONSE_BYTES": 65536,
        "COPILOT_MAX_TOKENS": 0,
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(cc, "_transport", None)
    monkeypatch.setattr(cc, "_http_client", None)
    return settings


def _wire_mock(monkeypatch, recorder: Recorder) -> None:
    monkeypatch.setattr(cc, "_build_http_client", lambda: _client(recorder))


# ---------------------------------------------------------------------------
# Authentication modes
# ---------------------------------------------------------------------------

def test_pat_bearer_sends_pat_only_to_inference_with_prompt_separation():
    rec = Recorder({CHAT_PATH: [_completion("hello")]})
    http = _http(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), Clock())

    result = http.complete("SYSTEM PROMPT", "USER PROMPT", "gpt-5.4-mini")

    assert result.text == "hello"
    (request,) = rec.requests
    assert str(request.url) == f"{API_BASE}{CHAT_PATH}"
    assert request.method == "POST"
    assert request.headers["authorization"] == f"Bearer {PAT}"
    assert json.loads(request.content) == {
        "model": "gpt-5.4-mini",
        "messages": [
            {"role": "system", "content": "SYSTEM PROMPT"},
            {"role": "user", "content": "USER PROMPT"},
        ],
        "stream": False,
    }


def test_max_tokens_is_sent_only_when_configured():
    rec = Recorder({CHAT_PATH: [_completion()]})
    http = _http(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), Clock(), max_tokens=800)

    http.complete("s", "u", "m")

    assert json.loads(rec.requests[0].content)["max_tokens"] == 800


def test_exchange_sends_pat_only_to_token_endpoint():
    rec = Recorder({TOKEN_PATH: [_exchange()], CHAT_PATH: [_completion()]})
    client = _client(rec)
    http = _http(client, _exchange_provider(client, Clock()), Clock())

    http.complete("s", "u", "claude-sonnet-5")

    token_request, chat_request = rec.requests
    assert token_request.method == "GET"
    assert token_request.headers["authorization"] == f"Bearer {PAT}"
    assert chat_request.headers["authorization"] == f"Bearer {EXCHANGED}"
    assert PAT not in str(chat_request.headers)
    assert PAT.encode() not in chat_request.content
    assert str(chat_request.url) == f"{API_BASE}{CHAT_PATH}"


def test_exchange_prefers_returned_endpoint_over_override():
    rec = Recorder({TOKEN_PATH: [_exchange(api=API_BASE)], CHAT_PATH: [_completion()]})
    client = _client(rec)
    tokens = _exchange_provider(client, Clock(), api_base_override="https://api.copilot.test")

    assert tokens.get(5.0).api_base_url == API_BASE


def test_exchange_uses_override_when_endpoint_missing():
    rec = Recorder({TOKEN_PATH: [_exchange(api=None)]})
    client = _client(rec)
    tokens = _exchange_provider(client, Clock(), api_base_override="https://api.copilot.test")

    assert tokens.get(5.0).api_base_url == "https://api.copilot.test"


@pytest.mark.parametrize("api", ["https://api.githubcopilot.com", "http://copilot-api.copilot.test"])
def test_exchange_rejects_unapproved_returned_endpoint(api):
    rec = Recorder({TOKEN_PATH: [_exchange(api=api)], CHAT_PATH: [_completion()]})
    client = _client(rec)
    http = _http(client, _exchange_provider(client, Clock()), Clock())

    with pytest.raises(cc.CopilotConfigError):
        http.complete("s", "u", "m")
    assert rec.paths() == [TOKEN_PATH]


def test_exchange_lifetime_falls_back_to_expires_at():
    rec = Recorder({TOKEN_PATH: [httpx.Response(200, json={"token": EXCHANGED, "expires_at": 10_000, "endpoints": {"api": API_BASE}})]})
    clock = Clock()
    tokens = _exchange_provider(_client(rec), clock, wall_clock=lambda: 8_000.0)

    tokens.get(5.0)
    clock.advance(1879)
    tokens.get(5.0)
    assert rec.paths() == [TOKEN_PATH]
    clock.advance(2)
    tokens.get(5.0)
    assert rec.paths() == [TOKEN_PATH, TOKEN_PATH]


def test_exchange_without_lifetime_fails_safely():
    rec = Recorder({TOKEN_PATH: [_exchange(refresh_in=None)]})

    with pytest.raises(cc.CopilotResponseError):
        _exchange_provider(_client(rec), Clock()).get(5.0)


# ---------------------------------------------------------------------------
# Token caching and refresh
# ---------------------------------------------------------------------------

def test_cached_token_is_reused_until_refresh_boundary():
    rec = Recorder({TOKEN_PATH: [_exchange(refresh_in=1500)]})
    clock = Clock()
    tokens = _exchange_provider(_client(rec), clock)

    tokens.get(5.0)
    clock.advance(1379)
    tokens.get(5.0)
    assert rec.paths() == [TOKEN_PATH]

    clock.advance(2)
    tokens.get(5.0)
    assert rec.paths() == [TOKEN_PATH, TOKEN_PATH]


def test_expiring_token_refreshes_once_under_concurrent_callers():
    def slow_exchange(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        time.sleep(0.05)
        return _exchange()

    rec = Recorder({TOKEN_PATH: [slow_exchange]})
    clock = Clock()
    tokens = _exchange_provider(_client(rec), clock)
    tokens.get(5.0)
    clock.advance(5000)

    results: list[str] = []
    threads = [threading.Thread(target=lambda: results.append(tokens.get(5.0).token)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert rec.paths() == [TOKEN_PATH, TOKEN_PATH]
    assert results == [EXCHANGED] * 8


def test_inference_401_refreshes_once_and_retries_once():
    rec = Recorder({
        TOKEN_PATH: [_exchange(token="tid=first-token-value"), _exchange(token="tid=second-token-value")],
        CHAT_PATH: [httpx.Response(401), _completion("ok")],
    })
    client = _client(rec)
    http = _http(client, _exchange_provider(client, Clock()), Clock())

    assert http.complete("s", "u", "m").text == "ok"
    assert rec.paths() == [TOKEN_PATH, CHAT_PATH, TOKEN_PATH, CHAT_PATH]
    assert rec.requests[3].headers["authorization"] == "Bearer tid=second-token-value"


def test_repeated_inference_401_raises_auth_error_without_looping():
    rec = Recorder({TOKEN_PATH: [_exchange()], CHAT_PATH: [httpx.Response(401)]})
    client = _client(rec)
    http = _http(client, _exchange_provider(client, Clock()), Clock())

    with pytest.raises(cc.CopilotAuthError):
        http.complete("s", "u", "m")
    assert rec.paths() == [TOKEN_PATH, CHAT_PATH, TOKEN_PATH, CHAT_PATH]


def test_pat_bearer_401_is_not_retried():
    rec = Recorder({CHAT_PATH: [httpx.Response(401)]})
    http = _http(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), Clock())

    with pytest.raises(cc.CopilotAuthError):
        http.complete("s", "u", "m")
    assert rec.paths() == [CHAT_PATH]


def test_entitlement_403_is_not_retried():
    rec = Recorder({TOKEN_PATH: [_exchange()], CHAT_PATH: [httpx.Response(403)]})
    client = _client(rec)
    http = _http(client, _exchange_provider(client, Clock()), Clock())

    with pytest.raises(cc.CopilotAuthError):
        http.complete("s", "u", "m")
    assert rec.paths() == [TOKEN_PATH, CHAT_PATH]


def test_token_exchange_rejection_raises_auth_error():
    rec = Recorder({TOKEN_PATH: [httpx.Response(403)]})
    client = _client(rec)
    http = _http(client, _exchange_provider(client, Clock()), Clock())

    with pytest.raises(cc.CopilotAuthError):
        http.complete("s", "u", "m")
    assert rec.paths() == [TOKEN_PATH]


# ---------------------------------------------------------------------------
# Retry, deadline, TLS, redirects
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [408, 429, 502, 503, 504])
def test_transient_status_retries_once_then_succeeds(status):
    rec = Recorder({CHAT_PATH: [httpx.Response(status), _completion("ok")]})
    http = _http(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), Clock())

    assert http.complete("s", "u", "m").text == "ok"
    assert rec.paths() == [CHAT_PATH, CHAT_PATH]


def test_persistent_transient_status_raises_after_one_retry():
    rec = Recorder({CHAT_PATH: [httpx.Response(503)]})
    http = _http(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), Clock())

    with pytest.raises(cc.CopilotTransientError):
        http.complete("s", "u", "m")
    assert rec.paths() == [CHAT_PATH, CHAT_PATH]


def test_network_error_retries_once():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    rec = Recorder({CHAT_PATH: [refuse, _completion("ok")]})
    http = _http(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), Clock())

    assert http.complete("s", "u", "m").text == "ok"
    assert rec.paths() == [CHAT_PATH, CHAT_PATH]


def test_other_4xx_is_not_retried():
    rec = Recorder({CHAT_PATH: [httpx.Response(400, json={"error": "bad model"})]})
    http = _http(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), Clock())

    with pytest.raises(cc.CopilotConfigError) as excinfo:
        http.complete("s", "u", "m")
    assert rec.paths() == [CHAT_PATH]
    assert "bad model" not in str(excinfo.value)


def test_retry_never_exceeds_the_call_deadline():
    clock = Clock()

    def slow_failure(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        clock.advance(31)
        return httpx.Response(503)

    rec = Recorder({CHAT_PATH: [slow_failure, _completion("late")]})
    http = _http(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), clock, timeout_s=30.0)

    with pytest.raises(cc.CopilotTransientError, match="deadline"):
        http.complete("s", "u", "m")
    assert rec.paths() == [CHAT_PATH]
    assert all(value <= 30.0 for value in rec.requests[0].extensions["timeout"].values())


def test_tls_failure_fails_closed_without_retry():
    def bad_certificate(request: httpx.Request) -> httpx.Response:
        try:
            raise ssl.SSLCertVerificationError("certificate verify failed")
        except ssl.SSLError as exc:
            raise httpx.ConnectError("TLS handshake failed", request=request) from exc

    rec = Recorder({CHAT_PATH: [bad_certificate]})
    http = _http(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), Clock())

    with pytest.raises(cc.CopilotConfigError, match="TLS"):
        http.complete("s", "u", "m")
    assert rec.paths() == [CHAT_PATH]


def test_redirects_are_never_followed():
    rec = Recorder({CHAT_PATH: [httpx.Response(302, headers={"location": "https://attacker.test/steal"})]})
    http = _http(_client(rec, follow_redirects=True), cc.StaticTokenProvider(PAT, API_BASE), Clock())

    with pytest.raises(cc.CopilotConfigError, match="redirected"):
        http.complete("s", "u", "m")
    assert [str(r.url) for r in rec.requests] == [f"{API_BASE}{CHAT_PATH}"]


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def test_usage_fields_are_returned_exactly():
    rec = Recorder({CHAT_PATH: [_completion("ok", usage={"prompt_tokens": 123, "completion_tokens": 45})]})
    http = _http(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), Clock())

    result = http.complete("s", "u", "m")

    assert (result.input_tokens, result.output_tokens) == (123, 45)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
    ],
)
def test_empty_or_malformed_responses_fail_safely(response):
    rec = Recorder({CHAT_PATH: [response]})
    http = _http(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), Clock())

    with pytest.raises(cc.CopilotResponseError):
        http.complete("s", "u", "m")
    assert rec.paths() == [CHAT_PATH]


def test_oversized_declared_response_is_rejected():
    rec = Recorder({CHAT_PATH: [httpx.Response(200, content=b"x" * 200)]})
    http = cc.CopilotHttpClient(_client(rec), cc.StaticTokenProvider(PAT, API_BASE), timeout_s=30, max_response_bytes=100, clock=Clock())

    with pytest.raises(cc.CopilotResponseError, match="COPILOT_MAX_RESPONSE_BYTES"):
        http.complete("s", "u", "m")


def test_oversized_streamed_response_is_rejected():
    response = httpx.Response(200, stream=httpx.ByteStream(b"x" * 200))

    with pytest.raises(cc.CopilotResponseError, match="COPILOT_MAX_RESPONSE_BYTES"):
        cc._read_capped(response, 100)


# ---------------------------------------------------------------------------
# HTTP client construction
# ---------------------------------------------------------------------------

def test_http_client_ignores_ambient_environment_and_redirects(configured, monkeypatch):
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setenv("HTTPS_PROXY", "http://ambient-proxy.test:1")
    monkeypatch.setenv("SSL_CERT_FILE", "ambient.pem")
    monkeypatch.setattr(cc.httpx, "Client", FakeClient)

    cc._build_http_client()

    assert captured["proxy"] == "http://proxy.test:912"
    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False
    assert captured["timeout"] == 30.0
    assert isinstance(captured["verify"], ssl.SSLContext)
    assert captured["verify"].verify_mode == ssl.CERT_REQUIRED


def test_ca_bundle_and_certifi_trust_build_verifying_contexts(configured, monkeypatch):
    import certifi

    monkeypatch.setattr(settings, "COPILOT_CA_BUNDLE", certifi.where())
    assert cc._ssl_context().verify_mode == ssl.CERT_REQUIRED

    monkeypatch.setattr(settings, "COPILOT_CA_BUNDLE", "")
    monkeypatch.setattr(settings, "COPILOT_TLS_TRUST", "certifi")
    context = cc._ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_ca_bundle_adds_to_system_trust(configured, monkeypatch):
    import certifi

    calls = []
    real = ssl.create_default_context
    monkeypatch.setattr(cc.ssl, "create_default_context", lambda **kw: calls.append(kw) or real(**kw))
    monkeypatch.setattr(settings, "COPILOT_CA_BUNDLE", certifi.where())

    with_bundle = cc._ssl_context().cert_store_stats()["x509_ca"]
    assert calls == [{}]
    assert with_bundle >= real(cafile=certifi.where()).cert_store_stats()["x509_ca"]


def test_api_base_on_web_host_is_rejected_with_hint(configured, monkeypatch):
    monkeypatch.setattr(settings, "COPILOT_API_BASE_URL", "https://intel-foundry.ghe.com")
    monkeypatch.setattr(settings, "COPILOT_ALLOWED_HOSTS", ["intel-foundry.ghe.com"])

    with pytest.raises(RuntimeError, match="copilot-api.intel-foundry.ghe.com"):
        configured.validate_enterprise_only()


def test_integration_id_header_is_sent_only_when_configured(configured, monkeypatch):
    rec = Recorder({CHAT_PATH: [_completion()]})
    _wire_mock(monkeypatch, rec)

    cc.complete("s", "u", "m")
    assert "copilot-integration-id" not in rec.requests[0].headers

    cc.close()
    monkeypatch.setattr(settings, "COPILOT_INTEGRATION_ID", "co-trace-registered")
    cc.complete("s", "u", "m")
    assert rec.requests[1].headers["copilot-integration-id"] == "co-trace-registered"
    assert rec.requests[1].headers["user-agent"].startswith("Co-Trace/")


# ---------------------------------------------------------------------------
# Configuration validation and provider normalization
# ---------------------------------------------------------------------------

def test_valid_configuration_passes(configured):
    configured.validate_enterprise_only()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("COPILOT_GITHUB_TOKEN", ""),
        ("COPILOT_AUTH_MODE", "cli_login"),
        ("COPILOT_ALLOWED_HOSTS", []),
        ("COPILOT_API_BASE_URL", ""),
        ("COPILOT_API_BASE_URL", "http://copilot-api.copilot.test"),
        ("COPILOT_API_BASE_URL", "https://api.githubcopilot.com"),
        ("COPILOT_API_BASE_URL", "https://user:pw@copilot-api.copilot.test"),
        ("COPILOT_PROXY", "socks5://proxy.test:1080"),
        ("COPILOT_TIMEOUT_S", 0),
        ("COPILOT_TOKEN_REFRESH_SKEW", -1),
        ("COPILOT_MAX_RESPONSE_BYTES", 0),
        ("COPILOT_MAX_TOKENS", -1),
        ("COPILOT_TLS_TRUST", "insecure"),
        ("COPILOT_CA_BUNDLE", "does-not-exist.pem"),
        ("COPILOT_GH_HOST", "github.com"),
    ],
)
def test_invalid_configuration_is_rejected_without_leaking_the_pat(configured, monkeypatch, name, value):
    monkeypatch.setattr(settings, name, value)

    with pytest.raises(RuntimeError) as excinfo:
        configured.validate_enterprise_only()
    assert PAT not in str(excinfo.value)
    assert cc.is_available() is False


def test_exchange_mode_requires_token_url(configured, monkeypatch):
    monkeypatch.setattr(settings, "COPILOT_AUTH_MODE", "exchange")
    with pytest.raises(RuntimeError, match="COPILOT_TOKEN_URL"):
        configured.validate_enterprise_only()

    monkeypatch.setattr(settings, "COPILOT_TOKEN_URL", TOKEN_URL)
    monkeypatch.setattr(settings, "COPILOT_API_BASE_URL", "")
    configured.validate_enterprise_only()


def test_offline_stub_skips_transport_validation(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "offline_stub")
    monkeypatch.setattr(settings, "COPILOT_GITHUB_TOKEN", "")

    settings.validate_enterprise_only()
    assert cc.is_available() is False


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "github_models")

    with pytest.raises(RuntimeError, match="not permitted"):
        settings.validate_enterprise_only()


def test_deprecated_sdk_alias_normalizes_to_http_with_warning(configured, monkeypatch, caplog):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "copilot_sdk")

    with caplog.at_level(logging.WARNING, logger="cotrace.config"):
        settings.validate_enterprise_only()

    assert settings.LLM_PROVIDER == "copilot_http"
    assert "deprecated" in caplog.text
    assert normalize_llm_provider(" Copilot_SDK ") == "copilot_http"


def test_cache_identity_is_transport_neutral(monkeypatch):
    monkeypatch.setattr(settings, "COPILOT_MINI_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(settings, "COPILOT_REASONING_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(settings, "COPILOT_ENABLE_MINI_ENRICH", True)
    key_args = dict(error_code="E1", error_message="m", context="ctx", context_source="debug_excerpt", signature="sig")

    monkeypatch.setattr(settings, "LLM_PROVIDER", "copilot_http")
    http_key = analysis_cache.make_key(**key_args)
    assert analysis_cache._cache_provider() == "copilot_sdk"
    assert analysis_cache._model_identity() == {
        "mini_model": "gpt-5.4-mini",
        "reasoning_model": "claude-sonnet-5",
        "mini_enrich": True,
    }

    monkeypatch.setattr(settings, "LLM_PROVIDER", "copilot_sdk")
    assert analysis_cache.make_key(**key_args) == http_key

    monkeypatch.setattr(settings, "COPILOT_REASONING_MODEL", "other-model")
    assert analysis_cache.make_key(**key_args) != http_key


# ---------------------------------------------------------------------------
# Module wiring, availability, redaction, fallback contract
# ---------------------------------------------------------------------------

def test_is_available_reflects_configuration_without_network(configured, monkeypatch):
    assert cc.is_available() is True
    assert cc._transport is None

    monkeypatch.setattr(settings, "COPILOT_GITHUB_TOKEN", "")
    assert cc.is_available() is False


def test_complete_refuses_to_run_when_unconfigured(configured, monkeypatch):
    monkeypatch.setattr(settings, "COPILOT_AUTH_MODE", "")

    with pytest.raises(cc.CopilotConfigError):
        cc.complete("s", "u", "m")
    assert cc._transport is None


def test_analysis_records_exact_usage_and_runs_without_subprocess(configured, monkeypatch):
    rec = Recorder({CHAT_PATH: [_completion(
        '{"root_cause":"fixture contact","suggested_solution":"reseat"}',
        usage={"prompt_tokens": 321, "completion_tokens": 12},
    )]})
    _wire_mock(monkeypatch, rec)
    monkeypatch.setattr(settings, "COPILOT_ENABLE_MINI_ENRICH", False)

    def no_subprocess(*args, **kwargs):
        raise AssertionError("Copilot path must not start a subprocess")

    monkeypatch.setattr(subprocess, "Popen", no_subprocess)

    result = cc.analyze_with_metrics("E001", "Voltage fault", "short excerpt")

    assert result.source == "llm"
    assert result.root_cause == "fixture contact"
    assert result.metrics.provider == "copilot_http"
    assert result.metrics.reasoning.input_tokens == 321
    assert result.metrics.reasoning.output_tokens == 12
    assert result.metrics.reasoning.token_counts_estimated is False
    assert "copilot" not in sys.modules


def test_close_releases_the_pooled_client(configured, monkeypatch):
    rec = Recorder({CHAT_PATH: [_completion()]})
    _wire_mock(monkeypatch, rec)

    cc.complete("s", "u", "m")
    assert cc._transport is not None

    cc.close()
    assert cc._transport is None
    assert cc._http_client is None


def test_error_suffix_and_logs_redact_secrets_by_value(configured, monkeypatch, caplog):
    rec = Recorder({TOKEN_PATH: [_exchange()]})
    client = _client(rec)
    tokens = _exchange_provider(client, Clock())
    tokens.get(5.0)
    monkeypatch.setattr(cc, "_transport", _http(client, tokens, Clock()))
    assert cc._SECRET_TOKEN_RE.search(EXCHANGED) is None

    suffix = cc._copilot_error_suffix(RuntimeError(f"boom {PAT} then {EXCHANGED}"))
    assert PAT not in suffix
    assert EXCHANGED not in suffix
    assert "[REDACTED]" in suffix

    with caplog.at_level(logging.WARNING, logger="cotrace.copilot"):
        cc.log.warning("leaked %s", EXCHANGED)
        try:
            raise RuntimeError(f"traceback carries {EXCHANGED} and {PAT}")
        except RuntimeError:
            cc.log.exception("Copilot analysis failed")

    assert EXCHANGED not in caplog.text
    assert PAT not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_typed_error_suffix_keeps_knowledge_fallback_contract():
    suffix = cc._copilot_error_suffix(cc.CopilotAuthError("inference request rejected", 401))
    record = UnitRecord(unit_id="u1", result="FAIL", error_code="E1", error_message="m", run_folder="u1")

    assert suffix == " (Copilot error: CopilotAuthError: inference request rejected, HTTP 401)"
    assert analyzer._analysis_needs_knowledge_fallback(record, "fixture contact", f"reseat{suffix}")
