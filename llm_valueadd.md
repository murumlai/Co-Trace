## Plan: LLM Value-Add and Deterministic RFC Matching

Create `llm_valueadd.md` as a design and implementation plan that makes deterministic RFC/error matching the primary source of truth, and positions LLMs as optional value-add around messy logs, ambiguous evidence, explanation, and ingestion enrichment. The recommended approach is to keep exact/high-confidence RFC matches fully deterministic, then layer LLM features behind explicit confidence gates and feature flags so known failures never regress to generic model output.

**Steps**

1. Define the document scope and principles.
   - State that direct RFC/error matching does not require an LLM.
   - Establish precedence: curated exact RFC match > curated high-confidence known-failure match > deterministic fuzzy candidate ranking > LLM enrichment > generic fallback.
   - Explicitly exclude LLMs from being the authoritative lookup engine for known RFC rows.

2. Document deterministic RFC/error matching as the baseline path.
   - Describe input fields: `UnitRecord.product_code`, `error_code`, `error_message`, `failing_step`, `debug_excerpt`, and `ftrunner_snippet`.
   - Reuse `backend/app/analyzer.py` functions: `signature_for`, `_retrieve_knowledge`, `_apply_exact_knowledge_fallback`, `_best_exact_known_failure`, `_field_matches_query`.
   - Reuse `backend/app/knowledge/retriever.py`: `LexicalKnowledgeRetriever.retrieve`, `_score`, `_format_match`, product-family fallback via `_family_code_for`.
   - Define match levels: exact message match, exact failing-step match, combined step+message match, product-family match, fuzzy/token match.
   - Define output policy: high-confidence deterministic match sets `root_cause` and `suggested_solution` directly from curated `KnownFailureEntry.corrective_action` and `RfcReference.notes`.

3. Add a deterministic matching improvement phase.
   - Add a `match_confidence` concept with values such as `exact`, `strong`, `partial`, `ambiguous`, `none`.
   - Add normalized variants for punctuation, casing, extra prefixes like `INFO -`, repeated spaces, and stable numeric normalization.
   - Add candidate scoring that weighs product exactness, family fallback, error-message overlap, failing-step overlap, category priority, and RFC note presence.
   - Add ambiguity handling: if multiple RFC rows are close, return deterministic top candidates and require either LLM ranking or user-facing ambiguity rather than guessing.
   - Keep exact known-failure/RFC fallback active for fresh LLM output, disk cache hits, and in-job signature cache hits.

4. Plan LLM value-add: summarize noisy logs.
   - Use LLM only after deterministic excerpt selection in `backend/app/analyzer.py::build_llm_context` and preprocessing extraction in `backend/app/preprocessor.py`.
   - Goal: compress noisy `debug_excerpt` or long `ftrunner_snippet` into a concise factual signal list.
   - Output: observed signals, relevant measurements, failing line(s), confidence, and unknowns.
   - Guardrails: input remains redacted and fenced; never use LLM summary as the only source when deterministic RFC match is exact.
   - Verification: tests using fake LLM responses that assert prompt includes only redacted bounded excerpts and output is not used to override exact RFC matches.

5. Plan LLM value-add: explain RFC relevance.
   - Add optional explanation text that answers why a matched RFC applies to the observed failure.
   - Input: deterministic match fields, RFC section summary, `KnownFailureEntry`, and `RfcReference` rows.
   - Output: one or two sentences for the Engineer view, for example: `This RFC matches because the log message exactly contains Disaster : Reading 20V failed! and the RFC row is for 20V Test.`
   - Implementation surface: extend `RetrievalMatch` or an analysis metadata model only if UI needs to display the explanation persistently.
   - Verification: fake LLM test that explanation cites the matched RFC fields and does not invent a new fix.

6. Plan LLM value-add: combine multiple evidence sources.
   - Enhance `_compose_knowledge_prompt` in `backend/app/analyzer.py` to label provenance: structured error fields, FTRunner snippet, DebugLog excerpt, matched RFC rows, debug-learning sections, and acronym glossary.
   - Add optional LLM synthesis that compares evidence sources and reports agreement, conflict, or insufficient evidence.
   - Preserve existing grounding boundaries: trusted product knowledge is separate from untrusted log excerpts.
   - Verification: tests assert provenance labels are present and source conflicts are surfaced without suppressing deterministic RFC actions.

7. Plan LLM value-add: rank ambiguous candidates.
   - Trigger only when deterministic retrieval returns multiple plausible candidates below exact confidence.
   - Use LLM to rank existing `RetrievalMatch` candidates by relevance, not to create new candidates.
   - Require output as ranked section IDs plus short reasons.
   - Add fallback: if LLM ranking fails or is malformed, keep deterministic order from `LexicalKnowledgeRetriever._score`.
   - Verification: tests for stable deterministic fallback and LLM ranking with fake ranked IDs.

8. Plan LLM value-add: technician-friendly corrective steps.
   - Convert terse RFC notes into structured actions only after deterministic match selects the RFC row.
   - Proposed model: `TechnicianStep` with `action`, `expected_result`, `if_failed`, `tool_or_equipment`, and `safety_note`.
   - Keep original RFC notes visible or traceable so generated steps are explainable.
   - Verification: fake LLM test that steps remain grounded in `corrective_action` / `RfcReference.notes` and do not introduce unsourced measurements or part numbers.

9. Plan LLM value-add: identify missing evidence.
   - Add optional output when no exact/high-confidence RFC match exists or when candidates are ambiguous.
   - Output: missing log section, measurement, station state, fixture state, or product metadata needed to disambiguate.
   - Avoid generic `review logs`; use source-aware requests like `need DebugLog lines around 20V read measurement` when context supports it.
   - Verification: tests with insufficient snippets assert missing evidence is specific and does not replace known RFC guidance.

10. Plan LLM value-add: normalize language variants.
    - Use deterministic normalization first in `_normalize_msg` and retrieval tokenization.
    - Use LLM only for proposing synonym/canonical forms during ingestion or offline curation, such as `20V read failure`, `Reading 20V failed`, and `20V Test Failed`.
    - Store approved canonical aliases in curated knowledge, not transient model memory.
    - Verification: parser/summarizer tests for alias extraction; retriever tests showing aliases improve matching without LLM at runtime.

11. Plan LLM value-add: engineer-facing explanations.
    - Generate concise root-cause narratives when deterministic evidence is partial or when multiple sources need synthesis.
    - Include evidence provenance and confidence language.
    - Keep `suggested_solution` deterministic when exact RFC match exists; LLM can add why this likely applies, not change the prescribed action.
    - Verification: tests assert exact RFC solution remains unchanged while explanation is added separately.

12. Plan LLM value-add: extract structured knowledge from unstructured docs.
    - Continue using `backend/app/knowledge/summarizer.py::LlmSectionSummarizer` for PDFs/DOCX and messy RFC rows.
    - Use deterministic XLSX parsing where rows are structured; use LLM only to extract fields from prose/table-like sections that are not already clean.
    - Add ingestion-time validation to detect empty summaries, missing RFC references, and conflicting guidance.
    - Verification: summarizer tests with fake JSON output and fallback behavior for empty model responses.

13. Update tests alongside implementation.
    - Extend `backend/tests/test_knowledge_analyzer.py` for exact/strong/ambiguous deterministic matching and cache repair paths.
    - Extend `backend/tests/test_knowledge_retriever.py` for scoring, confidence, family fallback, and ambiguous candidate handling.
    - Extend `backend/tests/test_knowledge_summarizer.py` for LLM value-add structured outputs and grounding constraints.
    - Extend `backend/tests/test_llm_response_parsing.py` for malformed LLM output and fallback preservation.
    - Add UI/API tests only if this plan introduces new persisted fields or endpoint output.

14. Rollout and configuration.
    - Gate expensive LLM value-add features with settings such as `LLM_VALUEADD_ENABLED`, `LLM_RFC_RERANK_ENABLED`, and `LLM_TECH_STEPS_ENABLED`.
    - Keep deterministic RFC matching always available when product knowledge is enabled.
    - Cache value-add outputs by failure signature, knowledge hash, matched section IDs, model identity, and prompt version.
    - Log when deterministic knowledge overrides LLM or cache output, including matched section IDs.

**Relevant Files**

- `backend/app/analyzer.py` - deterministic signature, retrieval integration, exact RFC fallback, cache-hit repair, LLM prompt composition.
- `backend/app/knowledge/retriever.py` - lexical retrieval, RFC category boost, product-family fallback, formatted knowledge context.
- `backend/app/knowledge/models.py` - `KnownFailureEntry`, `RfcReference`, `KnowledgeContext`, `RetrievalMatch`, possible future `match_confidence` or `TechnicianStep` models.
- `backend/app/knowledge/summarizer.py` - ingestion-time LLM extraction and deterministic structured RFC fallback.
- `backend/app/llm_client.py` - GitHub Models prompt, trusted product knowledge injection, response parsing.
- `backend/app/copilot_client.py` - Copilot SDK prompt, stream handling, error fallback behavior.
- `backend/app/analysis_cache.py` - cache key versioning and model/knowledge hash invalidation.
- `backend/tests/test_knowledge_analyzer.py` - exact RFC fallback and cache path coverage.
- `backend/tests/test_knowledge_retriever.py` - retrieval ranking and product-family fallback coverage.
- `backend/tests/test_knowledge_summarizer.py` - RFC extraction and LLM/fallback behavior coverage.
- `backend/tests/test_llm_response_parsing.py` - malformed LLM output handling coverage.

**Verification**

1. Deterministic matching unit tests:
   - Exact error message `Disaster : Reading 20V failed!` matches RFC `20V Test` for `N32828-201`.
   - Cached insufficient diagnoses are repaired from exact RFC knowledge.
   - Multiple ambiguous RFC matches do not silently choose a low-confidence candidate.

2. Retrieval tests:
   - Revisioned products retrieve exact product-code RFCs first and family-level RFCs second.
   - RFC category boost ranks direct RFC rows above generic HLD/product-overview context.
   - Token and normalized-string variants still retrieve the expected row.

3. LLM value-add tests with fake LLM clients:
   - Log summarization returns factual observed signals only.
   - RFC relevance explanation cites matched RFC fields.
   - Candidate reranking can reorder ambiguous matches but cannot introduce new section IDs.
   - Technician steps are grounded in original RFC notes.
   - Missing evidence output is specific and does not override exact RFC actions.

4. End-to-end runtime checks:
   - Build product knowledge from `Product_Docs/N32828-201_RFC_.xlsx`.
   - Analyze a failing `N32828-201` record with `INFO  - Disaster : Reading 20V failed!`.
   - Confirm `knowledge_used=true`, matched section includes `20de193411b1-s005` or the current 20V RFC section, and `suggested_solution` is RFC-derived.
   - Force malformed/empty LLM output and confirm deterministic RFC solution still wins.

5. Regression commands:
   - `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_knowledge_analyzer.py tests/test_knowledge_retriever.py tests/test_knowledge_summarizer.py tests/test_llm_response_parsing.py -q`
   - `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/ -q`

**Decisions**

- Deterministic RFC/error matching is mandatory and primary for known failure rows.
- LLM value-add is optional and must never override exact curated RFC guidance unless a human-approved workflow is added later.
- LLM-generated explanations, rankings, and technician steps must cite or derive from existing matched sections; they must not create new RFC facts.
- Cache keys for any LLM value-add must include knowledge hash, matched section IDs, model identity, and prompt version.
- `llm_valueadd.md` is a planning/design document only; implementation can be split into separate PR-sized phases.

**Further Considerations**

1. Decide whether value-add outputs should be persisted on `UnitRecord` or generated on demand in the Engineer view. Recommendation: start on demand or metadata-only to avoid schema churn.
2. Decide whether LLM ranking should be enabled by default. Recommendation: default off until deterministic confidence metrics are visible and tested.
3. Decide whether technician steps are part of diagnosis output or a separate expandable UI panel. Recommendation: separate panel so original RFC solution remains clearly authoritative.
