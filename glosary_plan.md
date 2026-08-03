## Plan: Authoritative Acronym Glossary

Create a repo-local acronym glossary that the analyzer injects into every LLM diagnosis prompt, and record unknown acronyms deterministically as pending review instead of letting the LLM invent full forms. The recommended approach is to add a dedicated glossary store beside product knowledge, merge approved definitions into `KnowledgeContext.context_text`, and append missing acronyms as `needs_review` entries with no definition until a human approves them.

**Steps**
1. Define the glossary file contract. Add a new repo-root JSON file target such as `product_acronyms.json`, plus a committed example/schema such as `product_acronyms.example.json`. Use entries with product scope, acronym, definition, status (`approved`, `needs_review`, `rejected`), source, timestamps, and counters. Product-specific approved definitions should override global definitions. Pending entries must never be used as authoritative LLM context.
2. Add configuration and gitignore coverage. Extend `backend/app/config.py` with `PRODUCT_ACRONYM_GLOSSARY_FILE`, `PRODUCT_ACRONYM_UNKNOWN_APPEND_ENABLED`, `PRODUCT_ACRONYM_MAX_PROMPT_ENTRIES`, and optional stopword settings. Update `.gitignore` for the real glossary if it may contain proprietary definitions; keep only the example/schema committed.
3. Implement a backend glossary store. Add `backend/app/knowledge/acronym_glossary.py` with atomic read/write behavior similar to `KnowledgeStore`, a thread lock, schema validation/coercion, product/global lookup, approved-definition selection, and `record_unknowns(...)` that appends or updates `needs_review` entries without storing raw log text.
4. Implement deterministic acronym extraction. Extract candidates from `UnitRecord.failing_step`, `error_code`, `error_message`, and the selected redacted LLM context. Use conservative regex/filters to avoid product codes, pure numbers, timestamps, hex IDs, common PASS/FAIL/result words, file extensions, and long noise tokens. Normalize case and count observations.
5. Merge glossary context into failure analysis. Update `backend/app/analyzer.py` / `AnalyzerService` to accept an injected acronym glossary service in addition to the product-knowledge retriever. During `_analyze_unit`, extract acronyms, append unknowns, build a `trusted_acronym_glossary` block from approved matches, and prepend/append it to `knowledge_prompt` even when no product knowledge matched. Include an `unknown_acronyms_observed` block that says these acronyms are not defined and must not be expanded.
6. Fix the existing normal-upload wiring while adding the glossary dependency. `backend/app/dependencies.py` already builds a knowledge-aware `AnalyzerService`, but `backend/app/orchestrator.py` currently constructs its default analyzer as `AnalyzerService()` without the knowledge retriever. Wire the singleton analyzer from the composition root into the default orchestrator or construct the default orchestrator with both the knowledge retriever and the new acronym glossary service so normal uploads and reanalysis behave consistently.
7. Update LLM prompts to obey the glossary. In `backend/app/llm_client.py` and `backend/app/copilot_client.py`, add explicit instructions: expand acronyms only when present in `trusted_acronym_glossary` or trusted product knowledge; if absent, keep the acronym literal and state that the expansion is unknown. Keep the existing prompt-injection guardrails.
8. Update cache invalidation. Extend `backend/app/analysis_cache.py` keys to include a glossary hash or sorted approved glossary entries used for the record. Bump `_CACHE_PROMPT_VERSION` so old diagnoses with invented acronym expansions are not reused.
9. Add API endpoints for review and maintenance. In `backend/app/main.py`, add authenticated endpoints under `/api/knowledge/acronyms` to list entries, update/approve definitions, reject entries, and optionally delete entries. Keep write validation strict and preserve atomic file writes.
10. Add UI review support. In `frontend/src/api.js` and `frontend/src/pages/Knowledge.jsx`, add an Acronyms section/table that shows approved and needs-review entries, lets the user add/edit definitions, approve pending acronyms, and filter by product/status. The UI should not present pending definitions as active.
11. Update diagnosis metadata as needed. Optionally extend `UnitRecord` in `backend/app/models.py` with `acronyms_used`, `unknown_acronyms`, and `acronym_glossary_hash` so the Engineer view/API can prove whether glossary definitions were included for a root-cause answer.
12. Add focused backend tests. Add new tests for extraction/filtering, glossary read/write/upsert behavior, approved vs pending lookup, analyzer prompt composition when product knowledge is absent, cache-key changes when definitions change, and prompt rules that prevent expansion of unknown acronyms.
13. Add frontend/UI tests only if the repo already has a frontend test harness; otherwise verify with `npm run build` and manual browser checks.

**Relevant files**
- `backend/app/knowledge/models.py` - reuse `AcronymDefinition` concepts; optionally add glossary-specific models if Pydantic schemas belong here.
- `backend/app/knowledge/retriever.py` - currently formats section-level acronyms from product knowledge; keep this behavior and do not make it the only glossary source.
- `backend/app/knowledge/storage.py` - copy the atomic write/read pattern for the new glossary store.
- `backend/app/analyzer.py` - main integration point for extracting acronyms, appending unknowns, composing LLM context, and storing metadata.
- `backend/app/analysis_cache.py` - include glossary state in cache keys and prompt version.
- `backend/app/llm_client.py` - GitHub Models prompt must treat the glossary as authoritative and unknown acronyms as unknown.
- `backend/app/copilot_client.py` - Copilot mini/reasoning prompts need the same acronym guardrails.
- `backend/app/dependencies.py` - instantiate and inject the glossary service.
- `backend/app/orchestrator.py` - ensure the normal upload pipeline uses the knowledge/glossary-aware analyzer, not a bare `AnalyzerService()`.
- `backend/app/main.py` - add glossary maintenance endpoints.
- `frontend/src/api.js` - add API client functions for glossary endpoints.
- `frontend/src/pages/Knowledge.jsx` - add glossary review/approval UI.
- `.gitignore` - ignore the real glossary if it can contain proprietary content; keep an example/schema committed.
- `backend/tests/test_knowledge_retriever.py`, `backend/tests/test_knowledge_analyzer.py`, `backend/tests/test_llm_prompt_guardrails.py` - extend nearby tests, and add new `backend/tests/test_acronym_glossary.py`.

**Verification**
1. Run focused backend tests: `cd backend; .\.venv\Scripts\python.exe -m pytest tests\test_acronym_glossary.py tests\test_knowledge_analyzer.py tests\test_llm_prompt_guardrails.py -q`.
2. Run full backend tests: `cd backend; .\.venv\Scripts\python.exe -m pytest tests\ -q`.
3. Run frontend build: `cd frontend; npm run build`.
4. Manual backend check: create a test glossary entry for a known acronym, upload a log containing that acronym, and confirm `/api/jobs/{job_id}/units` reports glossary metadata and the LLM prompt context would include the approved definition.
5. Manual unknown check: upload a log with a new acronym not in the glossary, confirm `product_acronyms.json` receives a `needs_review` entry with no definition, and confirm the LLM prompt tells the model not to expand it.
6. Cache check: change an approved acronym definition, reanalyze the same failed unit, and confirm the analysis cache key changes.
7. UI check: use the Knowledge tab Acronyms section to approve a pending acronym, rerun/reanalyze, and confirm the approved definition is used.

**Decisions**
- Unknown acronyms should be appended as pending entries, not with model-guessed definitions. This directly addresses the hallucination failure mode.
- Approved glossary definitions are authoritative; pending entries are visible for review but excluded from authoritative prompt context.
- The glossary should work even when no product-knowledge document exists for the product code.
- Product-specific glossary definitions override global definitions.
- Real glossary content should probably be gitignored because it may contain proprietary product terminology; commit an example/schema instead.

**Further Considerations**
1. File format: JSON is the safest fit because the backend already uses Pydantic/JSON artifacts. YAML is friendlier to hand-edit but would add parsing dependency or extra surface area.
2. Auto-append storage: append only metadata such as acronym, product code, count, timestamps, and redacted source fields. Avoid storing raw log snippets in the glossary.
3. Optional model assistance: if desired later, the LLM can propose candidate expansions into a separate `candidate_definition` field, but diagnosis prompts must not treat those as authoritative until approved.
