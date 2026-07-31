**Plan: Product-Aware Diagnosis**

The app should become aware of proprietary card/product context by preprocessing supporting product documents into a repo-root knowledge pack. Runtime diagnosis should never load or send whole documents. It should match a failed log record to product knowledge by `PRODUCTCODE`, retrieve only a few relevant curated summaries, and send those summaries alongside the bounded redacted failure excerpt.

Current source examples found under `Log_Files_Folder`:

- `M79060-001_Debug Support Document Key Learning.pdf`: debug-learning document with common failures and fixes.
- `M13983-700_Sedona USB Test Card.pdf`: general product/card information.
- `N32828-201_MPDU_20V_PDB1_HLD_Rev05.docx`: HLD document.

**Recommended Architecture**

Use repo-root generated artifacts:

- `product_knowledge.json`: manifest, schema version, generated timestamp, product list, source document metadata, category counts, warnings, and global/product knowledge hashes.
- `product_knowledge_index.json`: local retrieval index partitioned by product code, document category, token weights, section priority, and JSONL byte offsets.
- `product_knowledge_sections.jsonl`: one curated section-summary record per line, byte-offset addressable so runtime can read only matched sections.
- `product_docs/`: optional curated source-doc folder for product docs outside sample log batches.

Scan supporting source documents from both locations:

- `Log_Files_Folder/`: convenient for ad hoc support docs placed beside sample logs.
- `product_docs/`: cleaner long-term source folder for maintained product docs.

Do not store raw extracted document text in generated repo-root artifacts. Store curated summaries, section metadata, source references, category, extracted acronyms, limits/specs, known-failure entries, warnings, and hashes.

**Document Categories**

Categorize documents by filename keywords first, using the product code from the start of the filename when present and a regex fallback anywhere in the name.

- `hld`: HLD/design docs, usually `.docx`; extract architecture, subsystem roles, interfaces, test-relevant blocks, acronyms, and limits/specs.
- `debug_learning`: debug support/key-learning docs; extract known symptoms, failing steps, log signatures, likely root causes, corrective actions, station/fixture checks, and escalation notes. These sections should receive the highest retrieval priority for failure diagnosis.
- `product_overview`: general product/card PDFs; extract card purpose, major components, connectors/interfaces, power/thermal/firmware context, glossary terms, and product aliases.
- `uncategorized`: any supported document without clear keywords; still index summaries but give it lower retrieval priority until reviewed.

V1 should implement PDF and DOCX extraction. The design should keep parser adapters open for PPTX/XLSX and legacy Office formats later, but those should not block the first implementation.

**Steps**

1. Add product-knowledge configuration in [backend/app/config.py](backend/app/config.py): enable flag, repo-root artifact paths, source folders, top-k, max context chars, upload limits, document scan globs, and `PRODUCT_KNOWLEDGE_SUMMARY_MODEL=gpt-5.4-mini`.

2. Add parsing dependencies in [backend/requirements.txt](backend/requirements.txt): `pypdf` and `python-docx`. Keep PPTX/XLSX/legacy Office support behind future parser adapters.

3. Create product-knowledge models for source documents, extracted sections, curated summaries, known-failure entries, acronym definitions, limit/spec records, retrieval matches, and knowledge context metadata.

4. Create a backend product-knowledge service that:
   - scans both `Log_Files_Folder` and `product_docs`,
   - extracts product code from filenames, preferring the first filename token,
   - categorizes documents from filename keywords,
   - parses PDF/DOCX content,
   - detects heading sections and falls back to bounded chunks,
   - assigns stable section IDs,
   - summarizes each section with GPT 5.4-mini at ingestion time,
   - writes the manifest, index, and JSONL section records.

5. Use category-specific summarization prompts:
   - HLD prompt: architecture, subsystems, interfaces, acronyms, limits/specs, product aliases.
   - Debug-learning prompt: symptom, log/error indicators, failing steps, root cause, recommended fix, confidence, and applicable product/operation.
   - Product-overview prompt: product purpose, component glossary, card aliases, key interfaces, and test-relevant context.

6. Implement local retrieval first with deterministic lexical scoring. Use `PRODUCTCODE` as the required product join key, then score by `failing_step`, `error_code`, `error_message`, acronyms, limits/spec terms, and failure-context tokens. Boost `debug_learning` matches above HLD/general sections when symptom tokens overlap.

7. Add repo-folder ingestion via a script such as `backend/scripts/build_product_knowledge.py`, so engineers can rebuild the root knowledge pack from `Log_Files_Folder` plus `product_docs` without using the UI.

8. Add full UI management:
   - new Knowledge tab in [frontend/src/App.jsx](frontend/src/App.jsx),
   - new page `frontend/src/pages/Knowledge.jsx`,
   - API methods in [frontend/src/api.js](frontend/src/api.js),
   - authenticated backend routes in [backend/app/main.py](backend/app/main.py) for upload, list, rebuild, section preview, deactivate/delete, and scan-source-folder actions.

9. Add a narrow product-knowledge retriever contract in [backend/app/contracts.py](backend/app/contracts.py), then wire it through [backend/app/dependencies.py](backend/app/dependencies.py).

10. Extend [backend/app/analyzer.py](backend/app/analyzer.py) so failed-unit analysis retrieves product context before cache lookup and LLM calls. Persist knowledge metadata on each record: knowledge hash, matched section IDs, matched categories, and match status.

11. Update [backend/app/llm_client.py](backend/app/llm_client.py) and [backend/app/copilot_client.py](backend/app/copilot_client.py) prompts to separate:
   - trusted curated product summaries,
   - higher-priority known-failure/debug-learning summaries,
   - untrusted fenced failure logs.

   The prompt should tell the model to prefer product/card glossary definitions over general-world meanings and to treat debug-learning sections as product-specific historical evidence when they match the observed symptom.

12. Update [backend/app/analysis_cache.py](backend/app/analysis_cache.py) so cache keys include product code, op id, failing step, context hash, knowledge hash, matched section IDs, and matched category mix. Bump the prompt/cache version so old generic answers do not survive product-aware diagnosis.

13. Update [frontend/src/pages/Engineer.jsx](frontend/src/pages/Engineer.jsx) to show whether product knowledge was used, which categories matched, which section titles matched, and when no knowledge exists for the product.

14. Update [README.md](README.md) with the doc workflow, supported source folders, filename conventions, category rules, privacy boundary, generated files, GPT 5.4-mini summary step, and cache invalidation behavior.

**Verification**

1. Add backend tests for filename product-code extraction and category detection using examples like `M79060-001_Debug Support Document Key Learning.pdf`, `M13983-700_Sedona USB Test Card.pdf`, and `N32828-201_MPDU_20V_PDB1_HLD_Rev05.docx`.

2. Add parser tests for PDF and DOCX section extraction, heading fallback, fake summarizer output, and no-raw-text generated artifacts.

3. Add retrieval tests for product partitioning, acronym matching, limits/spec matching, debug-learning priority, JSONL byte-offset reads, analyzer fallback, and cache invalidation by knowledge hash.

4. Add API tests for product-doc upload/list/rebuild/delete/scan routes with auth and file validation.

5. Run `cd backend; .\.venv\Scripts\python.exe -m pytest tests/ -q`.

6. Run `cd frontend; npm run build`.

7. Manual check: scan the three current support docs, confirm the root knowledge files contain three products/categories, process matching logs, confirm Engineer view shows matched product sections, rebuild knowledge, then reanalyze and confirm the new knowledge hash is used.

**Key Decisions Captured**

- V1 discovers product documents from both `Log_Files_Folder` and `product_docs`.
- V1 matches docs to logs by `PRODUCTCODE` extracted from filenames, usually the first filename token.
- V1 categorizes docs by filename keywords: HLD, debug/key-learning/support, product overview, or uncategorized.
- V1 extracts PDF and DOCX. PPTX/XLSX/legacy Office formats are planned extension points.
- GPT 5.4-mini may summarize product docs during ingestion.
- Runtime prognosis sends curated summaries only, not whole documents or raw extracted text.
- Debug-learning sections receive the strongest retrieval boost because they encode product-specific known failures and fixes.
- First retrieval implementation should be lightweight lexical search; embeddings can come later behind the same retriever interface.
- Knowledge changes invalidate diagnosis cache automatically through knowledge hashes.

**Open Questions**

1. What exact filename keywords should map to `debug_learning` besides `Debug`, `Support`, `Key Learning`, `Learning`, `Failure`, and `Troubleshooting`?

2. Should a document be allowed to apply to multiple product codes if several product codes appear in the filename or document text?

3. Should the Knowledge UI allow editing/approving GPT 5.4-mini summaries before they become active for diagnosis?

4. Should generated knowledge files be committed, or should they stay local/ignored because they may contain proprietary summarized product information?
