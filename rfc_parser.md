## Plan: XLSX RFC Knowledge Support

Enable product-specific `.xlsx` RFC documents in the existing product-knowledge pipeline by adding an Excel parser adapter, an RFC-specific document category/schema, row-level indexing, upload/UI support, and focused tests. The recommended approach keeps the current architecture: scan -> parse -> summarize/curate -> write manifest/index/JSONL -> lexical retrieval -> LLM prompt context. No separate RFC service or runtime Excel reading is needed.

**Architecture impact**
- No new architecture is required. This fits the existing parser-adapter extension point already called out in `backend/app/knowledge/parsing.py` and the product-aware diagnosis design.
- The only structural changes are model/schema extensions for RFC references and a new `rfc_knowledge` category. Runtime diagnosis still reads curated JSONL sections by byte offset and never loads raw source documents.
- Update `architecture.md` to document the new category and RFC reference fields because the persisted knowledge schema changes.

**Steps**
1. Prepare the source document convention. The user must name or rename the RFC workbook so the filename contains the base product code or a full revisioned `PRODUCTCODE`, preferably at the start, e.g. `N32828_RFC.xlsx` or `N32828-201_RFC.xlsx`. Ingestion scripts must never rename source documents; they should fail with a clear validation error when an RFC workbook filename does not contain any product code or product-family code. Keep one RFC workbook per product family unless a future mapping file is added.
2. Add the Excel dependency in `backend/requirements.txt`: use `openpyxl`, not pandas, because ingestion only needs workbook/sheet/row reading.
3. Extend supported document discovery in `backend/app/config.py` by adding `*.xlsx` to `PRODUCT_KNOWLEDGE_SCAN_GLOBS`.
4. Harden discovery in `backend/app/knowledge/parsing.py`: skip Office lock/temp files whose basename starts with `~$`, so the current `Product_Docs/~$20VMPDUPDB1_RFC_.xlsx` is never ingested, and reject RFC workbooks that have no product code or product-family code in the filename.
5. Add `rfc_knowledge` to `DocumentCategory` and `CATEGORY_PRIORITY` in `backend/app/knowledge/models.py`, with priority above `debug_learning` because these rows directly map failure signatures to RFC guidance.
6. Update `detect_category()` in `backend/app/knowledge/parsing.py` so filenames containing `rfc` classify as `rfc_knowledge`.
7. Implement `.xlsx` dispatch in `parse_document()` and add an `_extract_xlsx_rfc_sections()` helper in `backend/app/knowledge/parsing.py`.
8. Excel parser details: use `openpyxl.load_workbook(read_only=True, data_only=True)`, process all visible sheets, detect the header row case-insensitively, and normalize variants of these columns: `Failed Test Name / Error Name`, `Error Message/ Bin / Issue / Findings`, and `RFCs`.
9. Row-level sectioning: each non-empty data row with a failed-test/error-name and at least one RFC becomes one `ExtractedSection`; heading should identify workbook sheet plus failed test/error name; text should be label-prefixed fields rather than a raw pipe dump so the summarizer sees stable semantics.
10. RFC parsing rules: split multiple RFCs in one cell on common separators such as newline, comma, semicolon, slash, or bullet markers, while preserving adjacent note text. Treat RFC cell values as "RFC IDs plus notes," not as links to fetch.
11. Add RFC models in `backend/app/knowledge/models.py`: a small `RfcReference` record with fields such as `rfc_id`, `notes`, `failed_test_name`, and `error_message_or_finding`; add `rfc_references: list[RfcReference]` to `KnownFailureEntry`; and add product-family metadata so an RFC document for `N32828` can apply to `N32828-201`, `N32828-101`, `N32828-501`, and other revisions. Bump knowledge schema version in `backend/app/knowledge/service.py` from 1 to 2.
12. Add an RFC-specific summarizer prompt in `backend/app/knowledge/summarizer.py` and map `rfc_knowledge` to it. The prompt should extract exact failed test/error name, error message/bin/issue/findings, and every RFC ID/note without inventing missing fields.
13. Extend `_coerce_failures()`, `derive_keywords()`, and `keyword_weights()` in `backend/app/knowledge/summarizer.py` so RFC IDs, failed test names, error messages, bins, issue/findings text, and RFC notes are retained and indexed.
14. Update retrieval in `backend/app/knowledge/retriever.py`: boost `rfc_knowledge` matches similarly or higher than `debug_learning`, match RFC sections by exact product code first and then by product-family code when a revisioned product has no exact RFC workbook, and include RFC references in `_format_match()` so the diagnosis LLM sees the RFC IDs and notes in the curated context.
15. Update backend upload support in `backend/app/main.py`: add `.xlsx` to `_ALLOWED_DOC_EXTS` and revise the 400 message from "PDF/DOCX only" to include XLSX.
16. Update frontend upload support in `frontend/src/pages/Knowledge.jsx`: change the file input `accept` list to `.pdf,.docx,.xlsx` and update empty-state/help text to mention XLSX RFC documents.
17. Update docs in `README.md` and `architecture.md`: supported formats, RFC workbook filename convention, product-family matching across revisions, required columns, one-row-per-entry behavior, generated schema version, and the privacy boundary that runtime uses curated JSONL summaries only.
18. Rebuild the product knowledge pack after implementation with the user-named RFC workbook so `product_knowledge.json`, `product_knowledge_index.json`, and `product_knowledge_sections.jsonl` include the RFC entries. Treat those generated artifacts according to the repo's existing commit/local policy.

**Relevant files**
- `Product_Docs/<PRODUCT_FAMILY>_RFC.xlsx` or `Product_Docs/<PRODUCTCODE>_RFC.xlsx` - user-named source workbook; expected to contain a base product code such as `N32828` or a full revisioned code such as `N32828-201`, plus the three RFC table columns.
- `backend/requirements.txt` - add `openpyxl` dependency.
- `backend/app/config.py` - add `*.xlsx` scan glob.
- `backend/app/knowledge/parsing.py` - skip temp files, detect RFC category, extract product-family codes, parse XLSX rows into row-level sections.
- `backend/app/knowledge/models.py` - add `rfc_knowledge`, product-family metadata, `RfcReference`, and `KnownFailureEntry.rfc_references`.
- `backend/app/knowledge/summarizer.py` - add RFC prompt, coercion, keywords, token weights.
- `backend/app/knowledge/service.py` - bump schema version and keep index generation compatible with RFC category priority.
- `backend/app/knowledge/retriever.py` - match revisioned products to family-level RFC knowledge, boost RFC sections, and format RFC context for LLM diagnosis.
- `backend/app/main.py` - allow XLSX uploads.
- `frontend/src/pages/Knowledge.jsx` - allow/admin-upload XLSX and update UI copy.
- `architecture.md` and `README.md` - document supported RFC workbook flow and schema update.

**Verification**
1. Add parser tests in `backend/tests/test_knowledge_parsing.py` or a new `backend/tests/test_knowledge_parsing_xlsx.py` that create a minimal `.xlsx` using `openpyxl`, verify RFC category detection, product-family extraction from names like `N32828_RFC.xlsx` and `N32828-201_RFC.xlsx`, row-level sections, multi-RFC splitting, all-sheet processing, empty-row skipping, Office temp-file skipping, and clear failure when an RFC workbook filename has no product code or product-family code.
2. Update summarizer tests in `backend/tests/test_knowledge_summarizer.py` with fake RFC JSON output and assert `rfc_references` are coerced, retained, and indexed as keywords.
3. Update service tests in `backend/tests/test_knowledge_service.py` to build a pack from a fake RFC workbook and assert product/category counts, schema version 2, token weights, and no full raw workbook text persisted beyond curated fields.
4. Update retriever tests in `backend/tests/test_knowledge_retriever.py` so a `UnitRecord` for `N32828-201`, `N32828-101`, or `N32828-501` can retrieve the same family-level `N32828` RFC knowledge, matching failed step or error message retrieves `rfc_knowledge` first, and the formatted context includes RFC IDs/notes.
5. Update API tests in `backend/tests/test_knowledge_api.py` and `backend/tests/test_knowledge_upload_single_doc.py` to verify XLSX upload is accepted and unsupported file validation still works.
6. Run targeted backend tests: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_knowledge_parsing.py tests/test_knowledge_summarizer.py tests/test_knowledge_service.py tests/test_knowledge_retriever.py tests/test_knowledge_api.py tests/test_knowledge_upload_single_doc.py -q`.
7. Run full backend tests if targeted tests pass: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/ -q`.
8. Run frontend build: `cd frontend; npm run build`.
9. Manual validation: after the user names the workbook with a base product code or full product code, rebuild knowledge, confirm the Knowledge page shows an `rfc_knowledge` category for the target product family, then analyze failed logs from at least two revisions whose failed test/error message appears in the workbook and confirm the Engineer view reports product knowledge used with RFC context.

**Decisions**
- The user owns RFC workbook filename changes. Ingestion/build scripts must not rename source documents; they only validate that RFC workbook filenames contain a product code or product-family code and fail clearly when they do not.
- RFC workbooks are product-family scoped. A workbook named for `N32828` should apply to revisioned log products such as `N32828-201`, `N32828-101`, and `N32828-501`; a workbook named for a full revisioned code should also expose its base family code for fallback matching.
- RFC cells contain IDs plus notes; they should be preserved in curated context, not treated as external documents to fetch.
- Each spreadsheet row becomes one retrievable failure/RFC entry for precise matching.
- This scope does not add embeddings, workbook editing UI, approval workflow, or ingestion of separate RFC files referenced by ID.
