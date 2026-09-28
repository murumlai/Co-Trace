# Pure Python GitHub Copilot Deployment Plan

## Goal

Replace the `github-copilot-sdk` and its bundled `copilot.exe` runtime with direct HTTPS calls from `backend/app/copilot_client.py` using Python and `httpx`.

The production credential will be a fine-grained GitHub PAT supplied through an environment variable. Phase 0 determines how it is used: either sent directly as the bearer credential to the approved Copilot API (`pat_bearer`), or exchanged for a short-lived Copilot API token that is cached in process memory (`exchange`). No credential is sent to the browser or persisted by the application.

## Confirmed Decisions

- Keep enterprise Copilot as the only live AI backend; `offline_stub` remains the failure fallback.
- Use `COPILOT_GITHUB_TOKEN` for the fine-grained PAT so existing secret injection does not need an immediate rename.
- The authentication mode (`pat_bearer` or `exchange`) is a Phase 0 outcome, not a pre-decision. Implement only the mode Phase 0 proves; do not build token-exchange, caching, locking, and refresh machinery if the direct PAT is accepted.
- In `exchange` mode, prefer the Copilot API endpoint returned by the exchange response instead of constructing a public endpoint.
- Keep the existing prompts, redaction boundary, two-model policy, response parsing, metrics, and public `analyze`/`analyze_with_metrics` contracts.
- Expose one public completion interface used by both failure diagnosis and product-knowledge summarization; no module may call private transport helpers.
- Use non-streaming chat completions initially. Streaming adds parsing and lifecycle complexity without improving the current synchronous analyzer contract.
- Do not retain the SDK as a hidden fallback. A successful deployment must have no `copilot.exe`, subprocess, SDK import, SDK cache, or interactive `copilot auth login` dependency.

## Important Authentication Constraint

A fine-grained PAT is not automatically a Copilot inference credential. The implementation may proceed only after Phase 0 proves all of the following in the target enterprise environment:

1. An approved enterprise endpoint for `intel-foundry.ghe.com` accepts the fine-grained PAT, either directly for inference (`pat_bearer`) or through an approved token exchange (`exchange`).
2. The PAT owner has an active Copilot entitlement and enterprise policy permits this server-side use.
3. In `exchange` mode, the response contains a short-lived token, a lifetime or expiry, and an approved Copilot API endpoint, or the platform team supplies the approved inference base URL separately.
4. The approved inference endpoint supports the required model IDs and either the chat-completions request/response schema or a documented equivalent.
5. The platform owner approves, in writing, direct server-side use of the endpoint and headers. The SDK is the supported client; the raw HTTP endpoints and headers are not a versioned public contract and may change without notice.
6. Any required integration identifier (for example `Copilot-Integration-Id`) is registered for this application. Never reuse another product's identifier, such as VS Code's.

Repository permissions on a fine-grained PAT do not by themselves grant Copilot access. Confirm whether the enterprise exposes a Copilot-specific fine-grained PAT permission (such as "Copilot Requests") and which permission is required. If the enterprise endpoint rejects fine-grained PATs, stop the migration and obtain an approved credential type or internal gateway; do not bypass the approved flow or fall back to a public GitHub host.

## Phase 0: Prove the Enterprise Contract

Run a minimal, non-secret connectivity probe from the production network using the same proxy and TLS trust source that the service will use.

1. Use the current SDK deployment as the reference client. With the same PAT supplied through `COPILOT_GITHUB_TOKEN`, capture the hostnames and paths it contacts from proxy logs (never headers or bodies). These hosts seed `COPILOT_ALLOWED_HOSTS` and show which authentication flow the supported client uses.
2. Obtain the approved endpoints and required headers from the enterprise GitHub/platform owner. Keep URLs configurable; do not guess them from `COPILOT_GH_HOST` in production.
3. Test both authentication modes, sending the PAT only in the approved authorization header over HTTPS:
   - `pat_bearer`: one minimal inference request with the PAT as the bearer credential;
   - `exchange`: the approved token-exchange request.
   Select the simplest mode that works and is approved, and record it as `COPILOT_AUTH_MODE`.
4. In `exchange` mode, validate the response fields and types. At minimum, identify:
   - short-lived Copilot token;
   - refresh interval or lifetime (preferred) and absolute expiry;
   - Copilot API base URL, preferably the response's `endpoints.api` value;
   - any required client/integration headers.
5. Validate that every configured or returned endpoint is HTTPS and belongs to the explicit enterprise-approved host allowlist.
6. Confirm the TLS trust source. `httpx` trusts the `certifi` bundle by default, not the Windows certificate store, so an enterprise-issued chain may fail. Choose `COPILOT_TLS_TRUST=system` (stdlib `ssl.create_default_context()`, which loads the Windows certificate store), `certifi`, or a `COPILOT_CA_BUNDLE` file.
7. Send one minimal, non-sensitive request to the approved completion endpoint for each configured model:
   - `gpt-5.4-mini`;
   - `claude-sonnet-5`.
8. Confirm the contract per model: `/chat/completions` or another approved contract such as `/responses`, and whether `max_tokens` and `usage` are supported. This plan assumes chat completions; isolate payload mapping so a confirmed alternative changes only the transport adapter.
9. Record only status codes, safe response headers, endpoint hostnames, and response shape. Never print or persist either token.

Exit criteria: the selected authentication mode and one inference request work from the deployment network with the fine-grained PAT, proxy, chosen TLS trust source, registered integration headers, and both configured models.

## Phase 1: Configuration and Validation

Update `backend/app/config.py` with explicit transport settings:

- `COPILOT_GITHUB_TOKEN`: required PAT for the live provider.
- `COPILOT_AUTH_MODE`: `pat_bearer` or `exchange`, as proven in Phase 0.
- `COPILOT_TOKEN_URL`: approved token-exchange URL; required only in `exchange` mode.
- `COPILOT_API_BASE_URL`: approved inference base URL; required in `pat_bearer` mode, and an override in `exchange` mode only when the exchange does not return an endpoint.
- `COPILOT_ALLOWED_HOSTS`: comma-separated exact hostnames from Phase 0. This positive allowlist is the primary host control; the existing `_PUBLIC_COPILOT_HOSTS` denylist is not sufficient because it only covers `github.com` variants and omits public Copilot API hosts.
- `COPILOT_PROXY`: passed explicitly to `httpx` as `proxy=`.
- `COPILOT_TLS_TRUST` (`system` default, or `certifi`) and optional `COPILOT_CA_BUNDLE`, which overrides both, per the Phase 0 TLS decision; TLS verification must never be disabled. The stdlib OS-store option needs no extra dependency.
- `COPILOT_TIMEOUT_S`: keep its current meaning as the overall per-call deadline. Retries, token refresh, and backoff all fit inside it, so the `up to Ns per uncached signature` estimate in `orchestrator.py` stays accurate. Derive per-attempt timeouts from the remaining budget.
- `COPILOT_TOKEN_REFRESH_SKEW`: `exchange` mode only; refresh shortly before expiry, initially 120 seconds.
- `COPILOT_MAX_RESPONSE_BYTES`: cap on the response body read from the provider.
- `COPILOT_GH_HOST`: deprecated; retained for display in logs and health only and never used to derive request URLs.

Construct the `httpx.Client` with `trust_env=False` so ambient `HTTPS_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, and `.netrc` cannot redirect traffic or change trust, and with `follow_redirects=False` so a redirect cannot carry credentials to another host. This intentionally replaces the current `env.setdefault` behavior, where ambient proxy variables win.

Normalize `LLM_PROVIDER` once in `Settings`: accept `copilot_sdk` as a deprecated alias that logs a warning, map it to canonical `copilot_http`, and expose only the canonical value. Replace the scattered `== "copilot_sdk"` comparisons in `analysis_cache.py`, `orchestrator.py`, and `llm_client.py` with the normalized value. Remove the alias after deployment configuration has migrated.

Extend startup validation to reject:

- a missing PAT, or a missing mode-specific URL, when the live provider is selected;
- an empty `COPILOT_ALLOWED_HOSTS` when the live provider is selected;
- non-HTTPS URLs, or configured URL hosts not in `COPILOT_ALLOWED_HOSTS`;
- invalid auth-mode, timeout, refresh-skew, or response-size values;
- a missing or unreadable configured CA bundle.

Use `secrets.compare_digest` only where token equality must be checked; never expose token values in validation errors.

## Phase 2: Replace SDK Plumbing in `copilot_client.py`

Keep prompt construction, `_parse_json_content`, offline fallback, model-role metrics, and `analyze_with_metrics` behavior intact. Replace `_create_client`, `_stream_once`, and `_run` with a public completion interface backed by a token provider and an HTTP client.

### Public Completion Interface

- Add `complete(system_prompt, user_prompt, model) -> CopilotCompletion`, where `CopilotCompletion` carries the assistant text and optional provider usage.
- Use it from `analyze_with_metrics` and from `_default_chat` in `knowledge/summarizer.py`, which currently calls the private `_run(_stream_once(...))` helpers.
- Redefine `is_available()` to mean "the live provider is selected, configured, and passed startup validation" instead of "the SDK is importable". It must not perform a network call. `summarizer.is_llm_backend_available()` and ingestion keep their current contract through it.
- Update the summarizer's unavailable-backend message to name the missing configuration instead of `copilot auth login`.

### Token Provider

Implement only the mode selected in Phase 0:

- `pat_bearer`: a static provider that returns the PAT; no cache, lock, or refresh logic.
- `exchange`: `ExchangeTokenProvider`, which must:
  - accept an injected `httpx.Client`, PAT, token URL, optional API-base override, and monotonic clock function;
  - exchange the PAT for a Copilot token on first use;
  - parse and validate token, lifetime, and API endpoint fields defensively, and validate the returned endpoint against `COPILOT_ALLOWED_HOSTS` on every exchange, not only at startup;
  - compute the local refresh deadline from the response's refresh interval or lifetime using `time.monotonic()`, so host/server clock skew cannot cause early or late refresh;
  - cache the short-lived token and endpoint in process memory only;
  - protect refresh with a `threading.Lock`, because analyses run in FastAPI background threads and concurrent jobs must not create a refresh burst;
  - refresh before expiry using `COPILOT_TOKEN_REFRESH_SKEW`;
  - clear and refresh once after an inference `401`, never looping indefinitely.

In both modes, never log request authorization headers, raw exchange bodies, or token values.

### `CopilotHttpClient`

- Accept an injected `httpx.Client` and token provider for deterministic tests.
- Build a non-streaming request with the existing system prompt and user prompt as separate messages.
- Send the configured model, `stream: false`, and `max_tokens` when Phase 0 confirms support, to the validated enterprise endpoint.
- Supply only headers proven necessary in Phase 0: authorization, JSON content negotiation, user agent, and the registered integration/version headers.
- Enforce `COPILOT_MAX_RESPONSE_BYTES` while reading the body and reject oversized responses.
- Parse assistant content from the confirmed response schema and reject empty or malformed responses.
- Pass provider usage to the existing `add_model_call(input_tokens=..., output_tokens=..., token_counts_estimated=False)` parameters; `LlmUsageMetrics` needs no model change. Without usage, retain the existing character-based estimate.
- Map failures to the typed exceptions defined in Phase 3.

### Secret Redaction

- The existing `_SECRET_TOKEN_RE` matches GitHub token prefixes such as `ghp_` and `github_pat_` but not short-lived Copilot tokens. Redact by value: the sanitizer replaces the configured PAT and the currently cached Copilot token wherever they appear in exception text and logs, in addition to the regex.
- Pin the `httpx` and `httpcore` loggers to `WARNING` even when `APP_DEBUG` is enabled.

Use a process-scoped, lazily constructed `httpx.Client` so connections are pooled. Close it in the FastAPI lifespan shutdown path. Keep all public analyzer calls synchronous; removing `asyncio.run` avoids creating an event loop for each model call.

## Phase 3: Failure and Retry Policy

Replace the text-marker matching in `_is_auth_or_session_config_error` with typed exceptions raised by the HTTP layer:

- `CopilotAuthError`: token-exchange or inference `401`/`403` after the allowed refresh, including entitlement or policy rejection.
- `CopilotConfigError`: other non-retryable `4xx`, allowlist violations, and TLS/hostname validation failures.
- `CopilotTransientError`: timeouts, connect/reset errors, and `408`, `429`, `502`, `503`, `504` after the allowed retry.
- `CopilotResponseError`: non-JSON HTTP bodies, missing assistant content, and oversized responses.

Exception messages carry only a category and status code, never response bodies, headers, or token values.

Classify failures before applying the existing offline fallback:

| Failure | Behavior |
| --- | --- |
| Token exchange `401`/`403` | Raise `CopilotAuthError`; fail the current analysis to the offline stub. |
| Inference `401` (`exchange` mode) | Invalidate the short-lived token, exchange once, and retry once; then raise `CopilotAuthError`. |
| Inference `401`/`403` (`pat_bearer` mode) | Raise `CopilotAuthError` without retry. |
| `408`, `429`, `502`, `503`, `504`, connect/reset errors | Retry once within the remaining `COPILOT_TIMEOUT_S` budget; then raise `CopilotTransientError`. |
| Other `4xx` | Do not retry; raise `CopilotConfigError`. |
| Non-JSON HTTP body or missing assistant content | Do not retry; raise `CopilotResponseError`. |
| Assistant text that is not the expected JSON | Use the existing `_parse_json_content` safe path. |
| TLS or hostname validation failure | Fail closed with `CopilotConfigError`; never disable certificate verification. |

The initial retry policy is deliberately minimal because the SDK path has no application-level retries today. Add exponential backoff, jitter, and bounded `Retry-After` handling only if canary or production metrics show recurring `429`/`5xx` responses.

The mini-pass rule remains unchanged: a mini-model failure other than `CopilotAuthError`/`CopilotConfigError` may continue to the reasoning model with raw redacted context, while authentication/configuration failures skip the reasoning call.

Keep the user-visible stub suffix format `(Copilot error: <Category>: <status>)`. `_analysis_needs_knowledge_fallback` in `analyzer.py` detects the `copilot error:` substring to trigger curated-knowledge fallback, so that prefix is a contract.

## Phase 4: Remove Runtime Dependencies

1. Remove all imports and availability guards for `CopilotClient`, `PermissionHandler`, `SubprocessConfig`, and `CopilotClientOptions`.
2. Remove `github-copilot-sdk==1.0.14` from `backend/requirements.txt`; `httpx` is already a direct dependency. Remove `pytest-asyncio` once the SDK streaming test is retired; no other test uses asyncio.
3. Remove the SDK wheel from `wheelhouse/` and any offline-install manifest, and verify no deployment step populates `%LOCALAPPDATA%/github-copilot-sdk` or invokes `copilot.exe`.
4. Remove the logged-in-user fallback (`use_logged_in_user=True` when no PAT is set). Local development then requires a developer's own PAT in the environment or `LLM_PROVIDER=offline_stub`; document both in `README.md`.
5. Remove `copilot auth login` from `README.md` and deployment instructions.
6. Update `backend/scripts/build_product_knowledge.py`, module docstrings, architecture documents, and operational messages that still describe SDK/CLI authentication.
7. Rename health data from `copilot_sdk_available` to a transport-neutral readiness signal such as `copilot_http_configured`. Keep `copilot_token_configured` as a boolean only.
8. Keep `_model_identity()` in `analysis_cache.py` keyed on the mini model, reasoning model, and mini-enrich flag for the canonical provider. Models and prompts are unchanged, so SDK-era cache entries remain valid; the transport must not appear in the cache identity. Without this, the renamed provider would fall through to `{"provider": ...}` and model changes would stop invalidating cached results.
9. Record `provider="copilot_http"` in `LlmUsageMetrics` for new jobs; persisted jobs labelled `copilot_sdk` must still load and display.

Provider alias handling is defined in Phase 1.

## Phase 5: Tests

Use `httpx.MockTransport`; tests must never contact GitHub or require a real PAT.

Add focused tests for:

- `pat_bearer` mode sends the PAT only to the inference endpoint; `exchange` mode sends the PAT only to the exchange endpoint and never in the inference request.
- Exchange response token, lifetime, and `endpoints.api` are parsed correctly.
- Cached tokens are reused before the refresh boundary, using an injected monotonic clock.
- Expiring tokens refresh once under concurrent callers.
- Inference `401` forces one refresh and one retry in `exchange` mode and no retry in `pat_bearer` mode.
- `403` entitlement errors do not retry and fall back safely.
- Transient `408`/`429`/`5xx` and network failures retry once, and total elapsed time never exceeds `COPILOT_TIMEOUT_S`.
- Proxy, timeout, and TLS trust settings reach `httpx` correctly; ambient `HTTPS_PROXY` and `SSL_CERT_FILE` are ignored; redirects are not followed.
- Non-HTTPS or non-allowlisted configured and exchange-returned endpoints are rejected.
- Chat request messages preserve the current system/user prompt separation and model selection.
- Successful response content and exact usage fields feed the existing parser and metrics with `token_counts_estimated=False`.
- Empty, malformed, and oversized (`COPILOT_MAX_RESPONSE_BYTES`) responses fail safely.
- Error text and logs redact the PAT and Copilot token by value, even when their format does not match `_SECRET_TOKEN_RE`, plus authorization headers and secret-like response content.
- Typed exceptions drive the mini-pass rule; the stub suffix starts with `(Copilot error:`, contains no response body, and still triggers the analyzer's knowledge fallback.
- `LLM_PROVIDER=copilot_sdk` normalizes to `copilot_http`; cache identity includes model IDs under both values, changes when a model changes, and matches the SDK-era identity for unchanged models.
- The summarizer uses the public `complete()` interface; `is_available()` reflects configuration, not importability, and performs no network call.
- Mini failure, authentication failure, short-context, long-context, and offline-stub behavior remain unchanged.
- Health output exposes booleans only and never performs a network call.
- A subprocess-spawn guard proves the Copilot path does not execute an external binary.

Retire SDK-specific tests: the `_create_client` tests in `test_llm_metrics.py` and the fake streaming-client test in `test_llm_response_parsing.py`. Replace `_SDK_AVAILABLE`/`_stream_once` monkeypatches with `complete()` fakes or `httpx.MockTransport`.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_llm_metrics.py backend\tests\test_llm_response_parsing.py backend\tests\test_llm_prompt_guardrails.py backend\tests\test_knowledge_summarizer.py backend\tests\test_api_smoke.py -q
.\.venv\Scripts\python.exe -m pytest backend\tests\ -q
```

## Phase 6: Deployment

1. Store the fine-grained PAT in the production secret manager and inject it as `COPILOT_GITHUB_TOKEN`; never place it in a file, image, command line, log, or repository setting visible to clients.
2. Configure `COPILOT_AUTH_MODE`, the mode-specific URL, `COPILOT_ALLOWED_HOSTS`, proxy, TLS trust source, model IDs, and canonical `LLM_PROVIDER=copilot_http`.
3. Ensure the PAT owner is a dedicated service identity where enterprise policy permits it, has an active Copilot seat, and is subject to documented rotation/revocation ownership.
4. Build a clean Python environment from `backend/requirements.txt` without the SDK package.
5. Verify the deployed image/host contains no `copilot.exe` and does not create a GitHub Copilot SDK runtime cache at startup.
6. Start one canary instance and check `/api/health` for non-secret configuration state.
7. Run one redacted synthetic diagnosis through each model and confirm success, latency, retry counts, token refresh behavior (`exchange` mode), and provider usage metrics. Validate the response shape strictly so contract drift fails loudly.
8. Roll out gradually while monitoring categorized authentication, entitlement, configuration, rate-limit, timeout, and response errors.
9. Rotate the PAT once in staging and restart the process to prove the documented rotation procedure.
10. Re-run the synthetic canary after enterprise Copilot platform changes and on a regular schedule, because the raw endpoint contract is not a versioned public API.

Rollback does not reinstall the CLI. Set `LLM_PROVIDER=offline_stub` or deploy the previous application release while the credential/API issue is corrected.

## Acceptance Criteria

- A clean production machine needs Python dependencies and environment configuration only.
- No code imports `copilot`, locates/downloads an SDK runtime, starts a subprocess, reads CLI login state, or requires `copilot auth login`.
- The fine-grained PAT is sent only to the approved enterprise endpoint for the selected authentication mode.
- Inference uses an approved HTTPS endpoint in `COPILOT_ALLOWED_HOSTS`; in `exchange` mode it uses a validated short-lived Copilot token.
- In `exchange` mode, token refresh is concurrency-safe, uses a monotonic clock, and occurs before expiry or once after `401`.
- Total time per model call never exceeds `COPILOT_TIMEOUT_S`.
- Ambient proxy/TLS environment variables and HTTP redirects cannot change where credentials are sent.
- Existing two-tier analysis, prompt guardrails, JSON parsing, metrics, cache identity, knowledge-fallback detection, and offline fallback remain functionally equivalent.
- Diagnosis and product-knowledge summarization share the public `complete()` interface; no private transport helpers are called across modules.
- Unit tests cover success, refresh, retries, endpoint validation, malformed responses, and secret redaction without live network access.
- A production-network canary proves both configured models and records no credentials in logs.

## Files Expected to Change During Implementation

- `backend/app/copilot_client.py`
- `backend/app/config.py`
- `backend/app/main.py`
- `backend/app/analysis_cache.py`
- `backend/app/llm_client.py`
- `backend/app/orchestrator.py`
- `backend/app/knowledge/summarizer.py`
- `backend/app/analyzer.py` (verify only: `copilot error:` suffix contract)
- `backend/scripts/build_product_knowledge.py`
- `backend/requirements.txt`
- `backend/tests/test_llm_metrics.py`
- `backend/tests/test_llm_response_parsing.py`
- `backend/tests/test_knowledge_summarizer.py`
- `backend/tests/test_api_smoke.py`
- New focused HTTP transport/authentication tests under `backend/tests/`
- `wheelhouse/` (remove the SDK wheel)
- `README.md`
- `architecture.md` and `architecture_v2.md`

## Implementation Gate

Do not start the production migration until the platform owner confirms the authentication mode, exact enterprise endpoints, per-model inference contract, required and registered headers, endpoint allowlist, TLS trust source, written approval for direct server-side use, and fine-grained PAT compatibility. Those values are deliberately configuration, not assumptions embedded in code.