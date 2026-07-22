# LLM and Preprocessed JSON Optimization Plan

## Scope

The generated preprocessing artifact is currently built by `build_product_json()` in `backend/app/preprocessor.py` and written by `write_product_jsons()` to `.cotrace_work/<job_id>/preprocessed/<product_code>.json`.

Passing units are already fairly compact. Failed units are the main size drivers because they carry fields such as `steps`, `ftrunner_snippet`, `debug_excerpt`, and empty diagnosis placeholders.

The current API/UI reads `job.records` from the job registry, not the per-product JSON directly. That means the preprocessed JSON schema can be optimized as an artifact contract, as long as external/reporting expectations are explicit.

## Steps

1. Baseline the current size before changing schema.

   Add or run a small measurement script against representative products to report total JSON bytes, pretty-print overhead, units count, fail count, and per-field byte contribution for `steps`, `debug_excerpt`, `ftrunner_snippet`, warnings, and repeated metadata. This should drive prioritization.

2. Apply low-risk writer reductions first.

   In `write_product_jsons()`, use compact JSON separators instead of `indent=2`. Optionally keep a `PREPROCESSED_JSON_PRETTY=1` developer override. This is usually the cheapest reduction and preserves schema.

3. Omit empty/default fields.

   In `build_product_json()`, do not emit `root_cause` / `suggested_solution` placeholders until populated. Omit `None` values. Avoid fields like `end_time` only if `duration_s` plus `start_time` is sufficient for the chosen reporting contract.

4. Preserve deterministic DebugLog extraction for failed units.

   Keep the static path as the source of truth: FTRunner detects `FAIL`, `find_debuglog()` locates a reachable `DebugLog.txt`, and `extract_debug_excerpt()` anchors on `error_code`, `error_message`, or `failing_step` before falling back to generic failure markers/tail. This should remain script-based because it is reproducible, cheap, testable, redaction-friendly, and avoids sending entire DebugLogs to any model.

5. Route the DebugLog excerpt into future LLM context.

   The JSON already emits `debug_excerpt`, but the current analyzer prompt uses `record.redacted_snippet`, which is initialized from `ftrunner_snippet`. Add an explicit context builder that prefers `debug_excerpt` when present, then `ftrunner_snippet`, then `error_message`. Persist both the selected context and its source so later LLM processing is auditable.

6. Use an LLM only after deterministic extraction, not for raw log search.

   Optional LLM usage should be limited to summarizing/classifying the bounded, redacted excerpt already selected by the static script. Do not let a model scan multi-MB raw DebugLogs during preprocessing unless there is a measured quality gap the static anchors cannot cover.

7. Tighten failure excerpts.

   Add explicit config for `FTRUNNER_SNIPPET_CHAR_BUDGET` and consider lowering `DEBUG_EXCERPT_CHAR_BUDGET`, or storing only the matched window plus a hash/source marker. This is high impact for failure-heavy batches.

8. Reduce `steps` payload.

   If downstream only needs `failing_step`, do not include all steps in the preprocessed JSON. If steps are still needed, store them as compact tuples or reference a per-product step-name dictionary instead of repeated objects with long keys.

9. Add signature-level deduplication.

   Group repeated failure data into a `signatures` table keyed by the existing analyzer signature idea: `error_code`, normalized `error_message`, `failing_step`, shared snippet/excerpt, root cause/solution when available. Units then store `signature_id` instead of duplicating repeated failure text.

10. Add repeated-string dictionaries for metadata.

    For `station_id`, `host`, `lot_id`, `op_id`, and common step names, store a dictionary/table once and use short integer references from each unit. This helps large batches with many repeated station/lot values.

11. Consider a split artifact format if humans need a small top-level file.

    Keep `<product_code>.json` as a compact summary/index with per-unit core fields, and place verbose failure details under a sibling details folder or separate detail JSON files. This preserves quick loading while retaining full diagnostics.

12. Consider compressed output.

    If consumers can read it, write `<product_code>.json.gz` alongside or instead of raw `.json`. Compression is often the largest reduction for repeated JSON/text logs, especially snippets. Keep raw JSON only when human inspection is required.

13. Version the schema before breaking changes.

    Add `schema_version` and, if needed, `PREPROCESSED_JSON_FORMAT=legacy|compact` so existing consumers can keep using the current shape while compact mode is validated.

## Relevant Files

- `backend/app/preprocessor.py`: `build_product_json()` controls the emitted schema; `write_product_jsons()` controls serialization and file output.
- `backend/app/config.py`: add size-related settings such as snippet budgets, pretty/compact mode, schema format, gzip toggle, or Copilot model settings.
- `backend/app/orchestrator.py`: continues to call `write_product_jsons()`; should remain mostly unchanged unless output format returns multiple paths.
- `backend/app/analyzer.py`: reuse failure signature grouping concepts if signature-level deduplication is adopted; add an explicit LLM-context builder that prefers `debug_excerpt` over `ftrunner_snippet`.
- `backend/app/job_registry.py`: separate concern: `job_state.json` may also be large because it persists full `UnitRecord` data. Optimize separately if total disk use, not just preprocessed JSON size, is the concern.
- `backend/app/copilot_client.py`: new provider module to adapt the AI_WG Copilot SDK pattern into Co_Trace, isolating async/session lifecycle, model discovery, timeout handling, and JSON parsing.
- `backend/requirements.txt`: add `github-copilot-sdk==0.2.0` if adopting the Copilot SDK provider.
- `README.md`: update output schema/storage documentation after choosing the final format.

## Verification

1. Run the measurement script before and after each phase on at least one pass-heavy product and one failure/debug-heavy product.
2. Compare record counts and summary totals: total, pass, fail, unknown, FPY, and warnings must match the legacy artifact.
3. If timestamps or steps are removed, verify manager requirements still hold: first-pass yield, trend, station breakdown, lot comparison, and failure Pareto.
4. Validate generated JSON parses cleanly with `json.load()` and includes `schema_version` once compact/breaking changes are introduced.
5. For gzip/split artifacts, validate the expected files are generated under `.cotrace_work/<job_id>/preprocessed/` and survive app shutdown until the job TTL cleanup.
6. For failure extraction, test three cases: failed unit with matching DebugLog anchor uses `debug_excerpt`; failed unit with DebugLog but no exact anchor uses generic-marker/tail fallback; failed unit without DebugLog falls back to FTRunner snippet/error message without failing the job.
7. For Copilot SDK provider, verify `copilot auth login` has been completed on the host machine, `_init_copilot`-equivalent connectivity succeeds, `gpt-5.4-mini` appears in model discovery or falls back cleanly, and a bounded excerpt returns parseable JSON.
8. Verify the two-tier call policy: mini enrichment runs at most once per deterministic failure signature, and the larger reasoning model runs only for final root-cause/solution generation when not already cached.

## Decisions

- Keep the folder path unchanged: `.cotrace_work/<job_id>/preprocessed/`.
- Recommended order: minify + omit empty/default fields first, then cap/externalize snippets, then add signature/string dictionaries if the measured size is still too high.
- Do not remove timestamps blindly. `start_time` is used by manager trend/first-attempt logic in runtime records; for the preprocessed artifact it can be reduced only if the artifact does not need to reproduce those analytics independently.
- Keep raw `.json` unless external consumers can accept `.json.gz`; gzip can be additive to avoid breaking human inspection.
- Use static script extraction, not an LLM, for locating the relevant DebugLog region.
- If using the Copilot SDK / Copilot CLI auth bridge instead of a local model, route LLM calls through a configurable provider adapter. Use a mini model for bounded `debug_excerpt` summarization, classification, and human-readable signature/hint generation; use a larger model only for final root-cause and solution suggestions, grouped by deterministic failure signature to minimize cost and latency.

## Copilot SDK Reuse From AI_WG

Reference implementation lives in external repo:

```text
C:\Users\lloganat\source\repos\AI_WG\devops-log-analyzer-main
```

That project uses `github-copilot-sdk==0.2.0` and imports:

- `CopilotClient`
- `PermissionHandler`
- `SubprocessConfig`, when available
- fallback `CopilotClientOptions`, when `SubprocessConfig` is unavailable

Reusable details:

1. Client factory pattern

   Clone `os.environ`, set `HTTP_PROXY` / `HTTPS_PROXY` defaults when needed, instantiate `CopilotClient(SubprocessConfig(env=env))` when available, otherwise `CopilotClientOptions(env=env)`, and always `start()` / `stop()` around calls.

2. Model discovery

   Use `get_auth_status()` for connectivity and `list_models()` for available models. Fall back to raw client `models.list` when SDK model parsing fails with the known missing `vision` field issue. Default/fallback model in that app is `gpt-5.4-mini`.

3. Streaming request shape

   Create sessions with:

   ```python
   await client.create_session(
       on_permission_request=PermissionHandler.approve_all,
       model=model,
       available_tools=[],
       system_message={"mode": "replace", "content": system_prompt},
       infinite_sessions={"enabled": False},
       streaming=True,
   )
   ```

   Listen for:

   - `assistant.message_delta`
   - `assistant.message`
   - `session.idle`

   Then call `session.send(prompt)`, collect streamed chunks, disconnect the session, and stop the client in `finally`.

4. Co_Trace provider shape

   Wrap this into a backend provider module rather than Streamlit session state. Provide synchronous functions such as `summarize_failure_context(...)` and `diagnose_failure(...)` that internally run the async Copilot SDK calls with timeout and structured JSON parsing.

5. Model settings

   Keep two model settings:

   - `COPILOT_MINI_MODEL=gpt-5.4-mini` for summary/classification/hints
   - `COPILOT_REASONING_MODEL=<larger-model-name>` for root-cause/solution

   Keep `LLM_PROVIDER=copilot_sdk|github_models|offline_stub` so the existing GitHub Models path can remain as fallback.

6. Caching

   Reuse cache-key ideas from AI_WG: hash kind + model + system prompt + normalized prompt. Co_Trace can use `job.signature_cache` / persisted `job_state.json` instead of Streamlit cache files, so mini enrichment and reasoning calls are one-per-signature.

7. Compact-context ideas

   Reuse compact-context ideas from `logs_preprocess.py`:

   - repeated-line compression
   - suspicious-line extraction
   - string tables
   - column layout
   - line-table encoding for repeated multiline excerpts

   These are directly relevant to shrinking Co_Trace preprocessed JSON.

## Further Considerations

1. Decide the artifact purpose: human-readable archive, compact machine cache, or external integration payload. Recommended default: compact machine-readable JSON with optional pretty mode for debugging.
2. Define a target size reduction or max file size. Without a target, implement the safe phases and measure before introducing a more complex reference-table schema.
3. If overall storage is the real concern, include `job_state.json` in the optimization pass because it currently persists full records separately from the preprocessed product JSON.
