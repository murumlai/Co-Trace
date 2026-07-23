## Plan: SOLID Backend Refactor

Refactor the Python backend toward SOLID architecture by introducing small dependency abstractions around jobs, preprocessing, artifacts, analysis cache, LLM providers, and cleanup, then moving `orchestrator.run_job` from a concrete module-driven workflow into an injected application service. The recommended approach is incremental: first lock behavior with focused tests, then add interfaces/adapters beside the current code, then switch the composition root and endpoints to injected services.

**Source Control Workflow**
- Before implementation, create and switch to a new branch named `solid_principles` from the current working branch, after checking for existing uncommitted user changes.
- Commit each significant completed change to `solid_principles` with a clear message after its focused verification passes.
- Suggested commit boundaries: safety-net tests; contracts/interfaces; job persistence separation; orchestrator service extraction; preprocessing split; analysis/cache/provider adapters; composition-root wiring; documentation cleanup.
- After full verification confirms the refactor did not break existing functionality, update `README.md`, commit the documentation update, then push `solid_principles` to the remote.
- Do not stage unrelated user changes. If the worktree is dirty, inspect changes first and stage only files belonging to the current refactor increment.

**Steps**
1. Phase 1 - Establish safety net. Add focused backend tests before changing structure. Cover FTRunner parsing, DebugLog excerpt fallback, product JSON construction, analyzer cache/dedup behavior, job registry persistence/restore, upload zip safety, and a minimal FastAPI upload/status route smoke path. Prefer `backend/tests/` and either add `pytest` as a dev/runtime dependency or use stdlib `unittest` if avoiding dependencies is required. This step blocks the refactor.
2. Phase 2 - Define narrow contracts. Add small interfaces/protocols for `JobRepository`, `JobStateStore`, `Preprocessor`, `ArtifactWriter`, `FailureAnalyzer`, `AnalysisCache`, `LLMProvider`, and `PayloadCleaner`. Reuse the existing `typing.Protocol` style from `AuthProvider` and `Preprocessor`. Keep interfaces tiny and client-specific. Depends on step 1.
3. Phase 3 - Separate job domain state from persistence. Move file I/O currently inside `Job.save()` into a disk-backed job state adapter. Keep `Job` as state/model behavior only, and make `JobRegistry` depend on an injected state store/cleaner rather than directly reading settings, JSON, and filesystem paths. Depends on step 2.
4. Phase 4 - Extract the orchestration application service. Replace the monolithic `orchestrator.run_job(job_id)` workflow with a `JobOrchestrator` service that receives repository, preprocessor, artifact writer, analyzer, cleaner, settings/progress policy, and logger dependencies. Keep a compatibility wrapper if needed for `BackgroundTasks`. Depends on step 3.
5. Phase 5 - Split preprocessing responsibilities. Keep `FtrunnerPreprocessor` focused on converting one run folder into `UnitRecord`. Move run-folder discovery, DebugLog zip discovery/extraction, DebugLog excerpt selection, incomplete-folder warning scan, and per-product JSON writing into separate collaborators. Preserve existing parser heuristics exactly; this is architectural extraction, not parsing redesign. Can proceed in parallel with step 3 after contracts exist, but final wiring depends on step 4.
6. Phase 6 - Introduce analysis/cache/provider abstractions. Convert `analysis_cache.py` module functions into a cache adapter behind `AnalysisCache`; convert `llm_client.analyze` provider routing into injected `LLMProvider` implementations for offline stub, GitHub Models, and Copilot SDK. Keep `analyzer.analyze_job` behavior but depend on `FailureAnalyzer`/`AnalysisCache` abstractions rather than module globals. Can proceed in parallel with step 5 after contracts exist.
7. Phase 7 - Add a composition root. Create a single backend service factory that builds concrete adapters from `settings` and wires them into FastAPI dependencies/background tasks. `main.py` should own HTTP concerns and call application services, not import concrete persistence/cache/provider modules directly. Depends on steps 4, 5, and 6.
8. Phase 8 - Preserve public API and runtime behavior. Keep existing endpoint paths, response shapes, environment variables, defaults, job state JSON compatibility, cleanup behavior, and LLM fallback behavior unchanged. Add migration/backward-compatibility handling for existing `job_state.json` files. Runs throughout steps 3-7.
9. Phase 9 - Documentation, final commit, and push. After automated and manual verification confirm the implemented refactor did not break existing functionality, update README/backend layout notes to describe the new boundaries and run/test commands. Commit the README update separately if practical, then push the completed `solid_principles` branch. Remove compatibility wrappers only after endpoints and tests no longer need them. Depends on successful verification.

**Relevant Files**
- `backend/app/main.py` - Keep FastAPI route definitions, auth dependencies, request logging, and static serving; move app service construction into a composition helper or dependency provider.
- `backend/app/orchestrator.py` - Primary refactor target; turn `run_job`, cancellation checks, progress updates, cleanup calls, preprocessing calls, artifact writing, and analyzer calls into an injected orchestration service.
- `backend/app/job_registry.py` - Separate `Job` state from disk persistence; introduce repository/state-store adapters and keep TTL/restore behavior behind abstractions.
- `backend/app/preprocessor.py` - Split parser, folder discovery, DebugLog zip extraction, warning scan, product JSON building, and product JSON writing into focused modules/classes while preserving existing FTRunner behavior.
- `backend/app/analyzer.py` - Keep signature deduplication and failure-analysis workflow; inject cache and LLM/failure-analysis provider dependencies instead of using module globals.
- `backend/app/analysis_cache.py` - Convert file-backed cache into an adapter implementing a narrow cache contract.
- `backend/app/llm_client.py` - Replace provider conditional routing with concrete provider implementations selected by the composition root.
- `backend/app/copilot_client.py` - Keep Copilot SDK provider logic as an adapter behind the LLM provider contract.
- `backend/app/upload_storage.py` - Keep upload persistence focused; expose cleanup through `PayloadCleaner` where orchestration needs it.
- `backend/app/aggregator.py` and `backend/app/record_views.py` - Preserve as examples of mostly pure computation.
- `backend/app/models.py` - Keep shared Pydantic models stable unless test coverage reveals a useful small type extraction.
- `backend/requirements.txt` - Add test tooling only if using pytest or FastAPI test extras not already covered.
- `README.md` - Update architecture and verification instructions after refactor.

**Verification**
1. Run the new backend test suite from `backend/`, covering parser behavior, registry restore/TTL behavior, cache behavior, analyzer dedup/reanalysis behavior, upload zip safety, and orchestration success/cancel/error paths.
2. Run a backend import/smoke check from `backend/`: start `python run_backend.py` and call `GET /api/health`; expected JSON remains `{"status":"ok","llm_provider":"copilot_sdk","debug":false}` unless environment overrides are set.
3. Run an upload/status manual smoke using a small known FTRunner sample or existing ignored sample logs: login, upload, poll job status to terminal state, confirm Engineer units and Manager view response shapes match pre-refactor output.
4. Verify job persistence compatibility: process a job, restart backend, confirm `registry.load_from_disk` equivalent behavior restores completed/error jobs and marks interrupted running jobs as error.
5. Verify cleanup compatibility with `CLEANUP_JOB_WORKDIR_AFTER_RUN=1` and `0` so uploaded payloads/artifacts are removed or retained as before.
6. Verify provider behavior with `LLM_PROVIDER=offline_stub`, `github_models` without token, and `copilot_sdk` unavailable/available paths so graceful fallback remains intact.
7. Run frontend build (`npm run build` from `frontend/`) only after backend response shapes are touched, to catch API contract regressions in the UI build.
8. After verification passes, review and update `README.md` for the new architecture, run/test commands, and any changed module layout before the final documentation commit and push.

**Decisions**
- Included: backend Python architecture only; no frontend redesign.
- Included: behavior-preserving refactor with public API, environment variables, model fields, and job-state compatibility maintained.
- Included: tests as the first step because this repo currently has no Python test files and the refactor touches shared behavior.
- Excluded: replacing FastAPI, changing authentication strategy beyond preserving the existing `AuthProvider` seam, changing the FTRunner parsing rules, changing LLM prompts/model policy, or changing cleanup defaults.
- Recommended abstraction style: `typing.Protocol` for lightweight structural contracts, matching current local style; use `abc.ABC` only where runtime registration or stronger inheritance semantics are genuinely useful.

**Further Considerations**
1. Test framework choice: recommend `pytest` for clear parametrized parser/cache tests; use stdlib `unittest` only if adding dependencies is undesirable.
2. Refactor size: recommend several small commits on `solid_principles`, grouped by verified behavior changes rather than by file count.
3. Compatibility window: keep legacy module-level wrappers such as `orchestrator.run_job` during transition so `main.py` and any scripts can migrate one call site at a time.
