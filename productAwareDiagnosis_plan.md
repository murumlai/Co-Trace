**Plan: Product-Aware Diagnosis**

Yes, this is feasible. Recommended shape: preprocess product PDFs/DOCX into a repo-root knowledge pack, retrieve only a few product-matched curated sections at runtime, and send those summaries with the log excerpt to the LLM. Avoid a single giant JSON blob for runtime reads; use a small manifest plus an indexed JSONL section store so the backend can seek only the matched sections.

**Recommended Architecture**

Use repo-root local artifacts:

- `product_knowledge.json`: manifest, schema version, product list, document metadata, global/product knowledge hashes.
- `product_knowledge_index.json`: lightweight lexical index, product partitions, section offsets.
- `product_knowledge_sections.jsonl`: one curated section summary per line, byte-offset addressable.
- `product_docs/`: optional local source-doc folder for PDF/DOCX.

At ingestion time, the app parses PDF/DOCX, chunks by headings plus fallback windows, sends section text to GPT 5.4-mini to create curated summaries, and stores only summaries/metadata for diagnosis use. At runtime, the analyzer matches by `PRODUCTCODE`, retrieves top sections by local lexical search, and includes only those summaries in the prognosis prompt.

**Steps**

1. Add product-knowledge configuration in [backend/app/config.py](backend/app/config.py): enable flag, repo-root paths, top-k, max context chars, upload limits, and `PRODUCT_KNOWLEDGE_SUMMARY_MODEL=gpt-5.4-mini`.

2. Add parsing dependencies in [backend/requirements.txt](backend/requirements.txt): `pypdf` and `python-docx`. Keep `.doc` out of v1.

3. Create a backend product-knowledge service that:
   - parses PDF/DOCX,
   - detects heading sections,
   - falls back to bounded chunks,
   - assigns stable section IDs,
   - summarizes with GPT 5.4-mini,
   - writes manifest, index, and JSONL section records.

4. Implement local retrieval first with deterministic lexical scoring. Use `PRODUCTCODE` as the required product join key, then score by `failing_step`, `error_code`, `error_message`, acronyms, limits/spec terms, and failure-context tokens. Keep local embeddings as a later pluggable retriever.

5. Add repo-folder ingestion via a script such as `backend/scripts/build_product_knowledge.py`, so engineers can drop docs under `product_docs/<PRODUCTCODE>/` and rebuild the knowledge pack.

6. Add full UI management:
   - new Knowledge tab in [frontend/src/App.jsx](frontend/src/App.jsx),
   - new page `frontend/src/pages/Knowledge.jsx`,
   - API methods in [frontend/src/api.js](frontend/src/api.js),
   - authenticated backend routes in [backend/app/main.py](backend/app/main.py) for upload, list, rebuild, section preview, deactivate/delete.

7. Add a narrow product-knowledge retriever contract in [backend/app/contracts.py](backend/app/contracts.py), then wire it through [backend/app/dependencies.py](backend/app/dependencies.py).

8. Extend [backend/app/analyzer.py](backend/app/analyzer.py) so failed-unit analysis retrieves product context before cache lookup and LLM calls. Persist knowledge metadata on each record: knowledge hash, matched section IDs, and match status.

9. Update [backend/app/llm_client.py](backend/app/llm_client.py) and [backend/app/copilot_client.py](backend/app/copilot_client.py) prompts to separate:
   - trusted curated product summaries,
   - untrusted fenced failure logs.

   The prompt should tell the model to prefer product glossary/acronym definitions over generic meanings.

10. Update [backend/app/analysis_cache.py](backend/app/analysis_cache.py) so cache keys include product code, op id, failing step, context hash, knowledge hash, and matched section IDs. Bump the prompt/cache version so old generic answers do not survive product-aware diagnosis.

11. Update [frontend/src/pages/Engineer.jsx](frontend/src/pages/Engineer.jsx) to show whether product knowledge was used, which sections matched, and when no knowledge exists for the product.

12. Update [README.md](README.md) with the doc workflow, privacy boundary, generated files, GPT 5.4-mini summary step, and cache invalidation behavior.

**Verification**

1. Add backend tests for PDF/DOCX parsing, sectioning, fake summarizer output, lexical retrieval, JSONL offset reads, analyzer fallback, and cache invalidation by knowledge hash.

2. Add API tests for product-doc upload/list/rebuild/delete with auth and file validation.

3. Run `cd backend; .\.venv\Scripts\python.exe -m pytest tests/ -q`.

4. Run `cd frontend; npm run build`.

5. Manual check: upload/index a PDF or DOCX for a matching `PRODUCTCODE`, process logs, confirm Engineer view shows matched product sections, rebuild knowledge, then reanalyze and confirm the new knowledge hash is used.

**Key Decisions Captured**

- V1 matches docs to logs by `PRODUCTCODE`.
- V1 supports PDF and DOCX.
- GPT 5.4-mini may summarize product docs during ingestion.
- Runtime prognosis sends curated summaries only, not whole docs.
- First retrieval implementation should be lightweight lexical search; embeddings can come later behind the same retriever interface.
- Knowledge changes invalidate diagnosis cache automatically through knowledge hashes.