# Pure Python GitHub Copilot Deployment Plan

## Goal

Replace the `github-copilot-sdk` and its bundled `copilot.exe` runtime with direct HTTPS calls from `backend/app/copilot_client.py` using Python and `httpx`.

The production credential will be a fine-grained GitHub PAT supplied through an environment variable. The PAT is a bootstrap credential: Python exchanges it for a short-lived Copilot API token, caches that token in memory, and uses the short-lived token for chat-completion requests. No credential is sent to the browser or persisted by the application.

## Confirmed Decisions

- Keep enterprise Copilot as the only live AI backend; `offline_stub` remains the failure fallback.
- Use `COPILOT_GITHUB_TOKEN` for the fine-grained PAT so existing secret injection does not need an immediate rename.
- Use an HTTPS token-exchange flow before inference. Do not assume that the PAT itself is accepted by the chat-completions endpoint.
- Use the Copilot API endpoint returned by the token-exchange response when available instead of constructing a public endpoint.
- Keep the existing prompts, redaction boundary, two-model policy, response parsing, metrics, and public `analyze`/`analyze_with_metrics` contracts.
- Use non-streaming chat completions initially. Streaming adds parsing and lifecycle complexity without improving the current synchronous analyzer contract.
- Do not retain the SDK as a hidden fallback. A successful deployment must have no `copilot.exe`, subprocess, SDK import, SDK cache, or interactive `copilot auth login` dependency.

## Important Authentication Constraint

A fine-grained PAT is not automatically a Copilot inference token. The implementation may proceed only after Phase 0 proves all of the following in the target enterprise environment:

1. The approved token-exchange URL for `intel-foundry.ghe.com` accepts the fine-grained PAT.
2. The PAT owner has an active Copilot entitlement and enterprise policy permits this server-side use.
3. The exchange response contains a short-lived token, an expiry, and an approved Copilot API endpoint, or the platform team supplies the approved inference base URL separately.
4. The approved inference endpoint supports the required model IDs and either the chat-completions request/response schema or a documented equivalent.

Repository permissions on a fine-grained PAT do not by themselves grant Copilot access. If the enterprise endpoint rejects fine-grained PATs, stop the migration and obtain an approved credential type or internal gateway; do not bypass the exchange or fall back to a public GitHub host.

## Phase 0: Prove the Enterprise Contract

Run a minimal, non-secret connectivity probe from the production network using the same proxy and CA trust that the service will use.

1. Obtain the token-exchange URL and required headers from the enterprise GitHub/platform owner. Keep the URL configurable as `COPILOT_TOKEN_URL`; do not guess it from `COPILOT_GH_HOST` in production.
2. Send the PAT only in the approved authorization header over HTTPS.
3. Validate the exchange response fields and types. At minimum, identify:
   - short-lived Copilot token;
   - absolute expiry or lifetime;
   - Copilot API base URL, preferably the response's `endpoints.api` value;
   - any required client/integration headers.
4. Validate that every returned endpoint is HTTPS and belongs to an explicit enterprise-approved host allowlist.
5. Send one minimal, non-sensitive request to the approved completion endpoint for each configured model:
   - `gpt-5.4-mini`;
   - `claude-sonnet-5`.
6. Record only status codes, safe response headers, endpoint hostnames, and response shape. Never print or persist either token.
7. Confirm whether the endpoint is `/chat/completions` or another approved contract such as `/responses`. This plan assumes chat completions; isolate payload mapping so a confirmed alternative changes only the transport adapter.

Exit criteria: token exchange and one inference request work from the deployment network with the fine-grained PAT, proxy, enterprise CA chain, and both configured models.

## Phase 1: Configuration and Validation

Update `backend/app/config.py` with explicit transport settings:

- `COPILOT_GITHUB_TOKEN`: required bootstrap PAT for the live provider.
- `COPILOT_TOKEN_URL`: required approved enterprise token-exchange URL.
- `COPILOT_API_BASE_URL`: optional approved override only when the exchange does not return an API endpoint.
- `COPILOT_PROXY`: retain current proxy support.
- `COPILOT_CA_BUNDLE`: optional path to the enterprise CA bundle; TLS verification must never be disabled.
- `COPILOT_TIMEOUT_S`: retain as the response/read timeout and add bounded connect/write/pool timeout defaults if operationally useful.
- `COPILOT_TOKEN_REFRESH_SKEW`: refresh shortly before expiry, initially 120 seconds.
- Optional bounded retry settings for transient transport failures and `429`/`5xx` responses.

Extend startup validation to reject:

- a missing PAT or token URL when the live provider is selected;
- non-HTTPS token or inference URLs;
- public GitHub/Copilot hosts not approved by enterprise policy;
- invalid timeout, refresh-skew, or retry values;
- a missing or unreadable configured CA bundle.

Use `secrets.compare_digest` only where token equality must be checked; never expose token values in validation errors.

## Phase 2: Replace SDK Plumbing in `copilot_client.py`

Keep prompt construction, `_parse_json_content`, offline fallback, model-role metrics, and `analyze_with_metrics` behavior intact. Replace `_create_client`, `_stream_once`, and `_run` with two focused internal components:

### `CopilotTokenProvider`

- Accept an injected `httpx.Client`, PAT, token URL, optional API-base override, and clock function.
- Exchange the PAT for a Copilot token on first use.
- Parse and validate token, expiry, and API endpoint fields defensively.
- Cache the short-lived token and endpoint in process memory only.
- Protect refresh with a lock so concurrent analyses do not create a refresh burst.
- Refresh before expiry using `COPILOT_TOKEN_REFRESH_SKEW`.
- Clear and refresh once after an inference `401`; never loop indefinitely.
- Never log request authorization headers, raw exchange bodies, or token values.

### `CopilotHttpClient`

- Accept an injected `httpx.Client` and `CopilotTokenProvider` for deterministic tests.
- Build a non-streaming request with the existing system prompt and user prompt as separate messages.
- Send the configured model and `stream: false` to the validated enterprise endpoint.
- Supply only headers proven necessary in Phase 0: authorization, JSON content negotiation, user agent, and approved Copilot integration/version headers.
- Parse assistant content from the confirmed response schema and reject empty or malformed responses.
- Capture exact provider token usage when returned; otherwise retain the existing character-based estimate.
- Map failures into sanitized exceptions that the current outer fallback can report without leaking secrets or response bodies.

Use a process-scoped, lazily constructed `httpx.Client` so connections are pooled. Close it in the FastAPI lifespan shutdown path. Keep all public analyzer calls synchronous; removing `asyncio.run` avoids creating an event loop for each model call.

## Phase 3: Failure and Retry Policy

Classify failures before applying the existing offline fallback:

| Failure | Behavior |
| --- | --- |
| Token exchange `401`/`403` | Fail the current analysis to the offline stub; log a sanitized authentication/entitlement category. |
| Inference `401` | Invalidate the short-lived token, exchange once, and retry once. |
| `408`, `429`, `502`, `503`, `504`, connect/reset errors | Retry a small bounded number of times with exponential backoff and jitter; honor bounded `Retry-After`. |
| Other `4xx` | Do not retry; report a sanitized configuration/request failure and use the stub. |
| Invalid JSON or missing assistant content | Do not retry by default; use the existing safe parser/fallback path. |
| TLS or hostname validation failure | Fail closed; never disable certificate verification. |

The mini-pass rule remains unchanged: a non-authentication mini-model failure may continue to the reasoning model with raw redacted context, while authentication/configuration failures skip the reasoning call.

## Phase 4: Remove Runtime Dependencies

1. Remove all imports and availability guards for `CopilotClient`, `PermissionHandler`, `SubprocessConfig`, and `CopilotClientOptions`.
2. Remove `github-copilot-sdk==1.0.14` from `backend/requirements.txt`; `httpx` is already a direct dependency.
3. Remove the SDK wheel/runtime from production packaging and verify no deployment step populates `%LOCALAPPDATA%/github-copilot-sdk` or invokes `copilot.exe`.
4. Remove `copilot auth login` from `README.md` and deployment instructions.
5. Update `backend/scripts/build_product_knowledge.py`, module docstrings, architecture documents, and operational messages that still describe SDK/CLI authentication.
6. Rename health data from `copilot_sdk_available` to a transport-neutral readiness signal such as `copilot_http_configured`. Keep `copilot_token_configured` as a boolean only.

For compatibility, either keep `LLM_PROVIDER=copilot_sdk` as a deprecated alias for one release or migrate to `copilot_http` in the same release. The recommended approach is to accept both temporarily, normalize both to the HTTP implementation, document `copilot_http` as canonical, and remove the alias after deployment configuration has migrated.

## Phase 5: Tests

Use `httpx.MockTransport`; tests must never contact GitHub or require a real PAT.

Add focused tests for:

- PAT appears in the token-exchange request and never in the inference request.
- Exchange response token, expiry, and `endpoints.api` are parsed correctly.
- Cached tokens are reused before the refresh boundary.
- Expiring tokens refresh once under concurrent callers.
- Inference `401` forces one refresh and one retry.
- `403` entitlement errors do not retry and fall back safely.
- `429` honors bounded `Retry-After`; transient `5xx` and network failures use bounded retries.
- Proxy, timeout, and CA-bundle settings reach `httpx` correctly.
- Non-HTTPS or non-allowlisted response endpoints are rejected.
- Chat request messages preserve the current system/user prompt separation and model selection.
- Successful response content and exact usage fields feed the existing parser and metrics.
- Empty, malformed, and oversized responses fail safely.
- Error text and logs redact PATs, Copilot tokens, authorization headers, and secret-like response content.
- Mini failure, authentication failure, short-context, long-context, and offline-stub behavior remain unchanged.
- Health output exposes booleans only and never performs a network call.
- A subprocess-spawn guard proves the Copilot path does not execute an external binary.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_llm_metrics.py backend\tests\test_llm_response_parsing.py backend\tests\test_llm_prompt_guardrails.py backend\tests\test_api_smoke.py -q
.\.venv\Scripts\python.exe -m pytest backend\tests\ -q
```

## Phase 6: Deployment

1. Store the fine-grained PAT in the production secret manager and inject it as `COPILOT_GITHUB_TOKEN`; never place it in a file, image, command line, log, or repository setting visible to clients.
2. Configure the approved `COPILOT_TOKEN_URL`, proxy, CA bundle, model IDs, and canonical `LLM_PROVIDER` value.
3. Ensure the PAT owner is a dedicated service identity where enterprise policy permits it, has an active Copilot seat, and is subject to documented rotation/revocation ownership.
4. Build a clean Python environment from `backend/requirements.txt` without the SDK package.
5. Verify the deployed image/host contains no `copilot.exe` and does not create a GitHub Copilot SDK runtime cache at startup.
6. Start one canary instance and check `/api/health` for non-secret configuration state.
7. Run one redacted synthetic diagnosis through each model and confirm success, latency, retry counts, token refresh behavior, and provider usage metrics.
8. Roll out gradually while monitoring categorized token-exchange, entitlement, rate-limit, timeout, and inference errors.
9. Rotate the PAT once in staging and restart the process to prove the documented rotation procedure.

Rollback does not reinstall the CLI. Set `LLM_PROVIDER=offline_stub` or deploy the previous application release while the credential/API issue is corrected.

## Acceptance Criteria

- A clean production machine needs Python dependencies and environment configuration only.
- No code imports `copilot`, locates/downloads an SDK runtime, starts a subprocess, reads CLI login state, or requires `copilot auth login`.
- The fine-grained PAT is used only against the approved enterprise token-exchange endpoint.
- Inference uses a validated short-lived Copilot token and approved HTTPS endpoint.
- Token refresh is concurrency-safe and occurs before expiry or once after `401`.
- Existing two-tier analysis, prompt guardrails, JSON parsing, metrics, cache behavior, and offline fallback remain functionally equivalent.
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
- `backend/scripts/build_product_knowledge.py`
- `backend/requirements.txt`
- `backend/tests/test_llm_metrics.py`
- `backend/tests/test_api_smoke.py`
- New focused HTTP transport/authentication tests under `backend/tests/`
- `README.md`
- `architecture.md` and `architecture_v2.md`

## Implementation Gate

Do not start the production migration until the platform owner confirms the exact enterprise token-exchange URL, inference contract, required headers, endpoint allowlist, and fine-grained PAT compatibility. Those values are deliberately configuration, not assumptions embedded in code.