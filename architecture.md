# Co_Trace — Architecture

Co_Trace is a manufacturing test-log triage platform. It ingests FTRunner production logs, preprocesses them into normalized records, runs LLM-assisted root-cause analysis (grounded in a curated product-knowledge pack and an acronym glossary), and surfaces results through Engineer and Manager views.

## System Overview

```mermaid
graph TB
    subgraph Client["Frontend — React + Vite + Tailwind (SPA)"]
        direction TB
        Main["main.jsx<br/>entry / logging init"]
        AppShell["App.jsx<br/>tab router + batch orchestration"]
        Auth["auth.jsx<br/>AuthContext"]
        ApiJs["api.js<br/>HTTP client wrapper"]
        Logger["logger.js<br/>frontend telemetry"]

        subgraph Pages["Pages"]
            Home["Home<br/>upload + batch"]
            Engineer["Engineer<br/>per-unit results"]
            Manager["Manager<br/>metrics dashboard"]
            Knowledge["Knowledge<br/>docs + acronyms"]
            Login["Login"]
            About["About"]
        end

        subgraph Comps["Components"]
            TermView["TerminalViewer"]
            UI["ui.jsx primitives"]
        end
    end

    subgraph Server["Backend — FastAPI (Python)"]
        direction TB
        MainPy["main.py<br/>routes + middleware"]
        AuthPy["auth.py<br/>GitHub OAuth + admin JWT"]
        Deps["dependencies.py<br/>composition root / DI"]
        Config["config.py<br/>env settings"]
        Contracts["contracts.py<br/>protocols"]
        Models["models.py<br/>pydantic schemas"]

        subgraph Pipeline["Analysis Pipeline"]
            Orchestrator["orchestrator.py<br/>background job runner"]
            Preprocessor["preprocessor.py<br/>FTRunner log parser"]
            Analyzer["analyzer.py<br/>signature dedup + LLM"]
            Aggregator["aggregator.py<br/>FPY / Pareto / trends"]
            RecordViews["record_views.py<br/>serial grouping"]
            Redaction["redaction.py<br/>PII scrubbing"]
        end

        subgraph State["State & Storage"]
            JobReg["job_registry.py<br/>job lifecycle + TTL"]
            AnalysisCache["analysis_cache.py<br/>disk cache"]
            UploadStore["upload_storage.py<br/>uploads + zip extract"]
        end

        subgraph LLM["LLM Providers"]
            CopilotClient["copilot_client.py<br/>Copilot SDK (2-tier)"]
            LlmClient["llm_client.py<br/>GitHub Models / stub"]
        end

        subgraph KnowledgeSub["knowledge/ subsystem"]
            KService["service.py<br/>ingestion orchestrator"]
            KParsing["parsing.py<br/>PDF/DOCX/XLSX parse"]
            KSummarizer["summarizer.py<br/>LLM curation"]
            KRetriever["retriever.py<br/>lexical retrieval"]
            KStorage["storage.py<br/>pack read/write"]
            KGlossary["acronym_glossary.py<br/>approved acronyms"]
            KModels["models.py"]
        end
    end

    subgraph Disk["Persistent Storage (disk)"]
        WorkDir[("job_state.json<br/>per-product .json")]
        CacheDir[("analysis cache JSON")]
        Pack[("product_knowledge.json<br/>_index.json<br/>_sections.jsonl")]
        Glossary[("product_acronyms.json")]
    end

    subgraph External["External Services"]
        GitHub["GitHub OAuth"]
        Models_API["GitHub Models API"]
        CopilotSDK["GitHub Copilot SDK"]
        Docs["Product Docs<br/>(PDF/DOCX/XLSX)"]
    end

    %% Frontend wiring
    Main --> AppShell
    AppShell --> Auth
    AppShell --> Pages
    Pages --> Comps
    Pages --> ApiJs
    Auth --> ApiJs
    Logger --> ApiJs

    %% Frontend -> Backend
    ApiJs -->|"REST /api/*"| MainPy

    %% Backend routing
    MainPy --> AuthPy
    MainPy --> Deps
    MainPy --> Orchestrator
    MainPy --> Aggregator
    MainPy --> RecordViews
    MainPy --> KService
    Deps --> Config
    Deps --> JobReg
    Deps --> AnalysisCache
    Deps --> UploadStore
    Deps --> Analyzer
    Deps --> KStorage
    Deps --> KRetriever
    Deps --> KGlossary

    %% Pipeline flow
    Orchestrator --> Preprocessor
    Orchestrator --> Analyzer
    Orchestrator --> JobReg
    Orchestrator --> UploadStore
    Preprocessor --> Redaction
    Analyzer --> Redaction
    Analyzer --> AnalysisCache
    Analyzer --> KRetriever
    Analyzer --> KGlossary
    Analyzer --> CopilotClient
    Analyzer --> LlmClient

    %% Knowledge ingestion
    KService --> KParsing
    KService --> KSummarizer
    KService --> KStorage
    KSummarizer --> CopilotClient
    KSummarizer --> LlmClient
    KRetriever --> KStorage
    KParsing --> Docs

    %% Auth external
    AuthPy --> GitHub
    LlmClient --> Models_API
    CopilotClient --> CopilotSDK

    %% Disk persistence
    JobReg --> WorkDir
    AnalysisCache --> CacheDir
    KStorage --> Pack
    KGlossary --> Glossary
    UploadStore --> WorkDir
```

## Analysis Request Flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant FE as Frontend (Home)
    participant API as main.py
    participant Orch as orchestrator.py
    participant Pre as preprocessor.py
    participant Anz as analyzer.py
    participant Cache as analysis_cache.py
    participant KR as knowledge/retriever
    participant LLM as Copilot/LLM client
    participant Job as job_registry.py

    User->>FE: Select .txt/.log/.zip files
    FE->>API: POST /api/upload
    API->>Job: create(job_id, workdir)
    API-->>FE: job_id (status=pending)
    API->>Orch: run_job() [BackgroundTask]

    Orch->>Pre: parse run folders
    Pre-->>Orch: UnitRecord[] (redacted)
    Orch->>Orch: write per-product .json

    loop each unique error signature
        Orch->>Anz: analyze failed units
        Anz->>Cache: lookup(context hash)
        alt cache hit
            Cache-->>Anz: cached diagnosis
        else cache miss
            Anz->>KR: retrieve product knowledge + acronyms
            KR-->>Anz: grounded context
            Anz->>LLM: analyze_failure(redacted + context)
            LLM-->>Anz: root_cause + solution
            Anz->>Cache: store result
        end
        Anz-->>Orch: rec.root_cause / suggested_solution
        Orch->>Job: save progress
    end

    Orch->>Job: status=done

    loop poll
        FE->>API: GET /api/jobs/{id}/status
        API-->>FE: progress + LLM metrics
    end

    FE->>API: GET /api/jobs/{id}/units (Engineer)
    FE->>API: GET /api/jobs/{id}/manager (Aggregates)
    API-->>FE: results / FPY / Pareto / trends
```

## Data Model (ER-style)

Relationships are logical (in-memory / JSON documents), not a relational DB. `UnitRecord` is the spine: the preprocessor emits one per test run, `record_views.py` groups them per serial, and the analyzer enriches failing units with LLM + knowledge metadata.

```mermaid
erDiagram
    JobStatus ||--|| JobProgress : has
    JobStatus ||--|| LlmUsageMetrics : aggregates
    JobStatus ||--o{ UnitRecord : produces
    SerialUnitGroup ||--|| UnitRecord : "final attempt"
    SerialUnitGroup ||--o{ UnitRecord : "failing attempts"
    UnitRecord ||--o{ StepRecord : "steps[]"
    UnitRecord }o--o{ KnowledgeSection : "knowledge_section_ids"
    UnitRecord }o--o{ AcronymGlossaryEntry : "acronyms_used"
    LlmUsageMetrics ||--|| LlmModelMetrics : "mini"
    LlmUsageMetrics ||--|| LlmModelMetrics : "reasoning"

    KnowledgeManifest ||--o{ ProductManifestEntry : products
    KnowledgeManifest ||--o{ SourceDocumentMeta : documents
    SourceDocumentMeta ||--o{ KnowledgeSection : "produces (doc_id)"
    KnowledgeIndex ||--o{ SectionIndexEntry : "by_product"
    SectionIndexEntry ||--|| KnowledgeSection : "byte-offset -> JSONL"
    KnowledgeSection ||--o{ KnownFailureEntry : known_failures
    KnowledgeSection ||--o{ AcronymDefinition : acronyms
    KnowledgeSection ||--o{ LimitSpecRecord : limits
    KnowledgeContext ||--o{ RetrievalMatch : matches

    UnitRecord {
        string unit_id PK
        string serial_number
        string product_code FK
        string station_id
        string host
        string start_time
        string end_time
        float duration_s
        enum result "PASS|FAIL|UNKNOWN"
        string error_code
        string error_message
        string failing_step
        enum device_class "pan|aic|unknown"
        bool has_debuglog
        string debug_excerpt "transient"
        string signature "SHA1 dedup key"
        string root_cause "LLM"
        string suggested_solution "LLM"
        string analysis_source "llm|cached|local-cache|stub"
        string analysis_cache_key
        bool knowledge_used
        string knowledge_hash
        string knowledge_match_status
        list knowledge_section_ids FK
        list acronyms_used
        list unknown_acronyms
    }

    StepRecord {
        string name
        enum result "PASS|FAIL|UNKNOWN"
        float duration_s
    }

    SerialUnitGroup {
        string serial_number
        string unit_id "final attempt PK"
        enum classification "first_pass|retry_pass|fail|unknown"
        enum result
        int attempt_count
        int failure_count
    }

    JobStatus {
        string job_id PK
        enum status "pending|running|done|error|cancelled"
        string message
        int unit_count
        list warnings
    }

    JobProgress {
        int processed
        int total
    }

    LlmUsageMetrics {
        string provider
        int cache_hits
        int local_cache_hits
        int disk_cache_hits
        int total_calls
        float total_estimated_credits
    }

    LlmModelMetrics {
        string model
        int calls
        int errors
        int input_tokens
        int output_tokens
        float estimated_credits
    }

    KnowledgeManifest {
        int schema_version "2 (rfc_knowledge added)"
        string generated_at
        string summary_model
        string global_hash
    }

    ProductManifestEntry {
        string product_code PK
        int document_count
        int section_count
        string knowledge_hash
    }

    SourceDocumentMeta {
        string doc_id PK
        string filename
        string product_code FK
        string product_family_code FK "base code for RFC family match"
        enum category "hld|debug_learning|product_overview|rfc_knowledge|uncategorized"
        string content_hash
        int section_count
    }

    KnowledgeSection {
        string section_id PK
        string doc_id FK
        string product_code FK
        string product_family_code FK "base code for RFC family match"
        enum category "hld|debug_learning|product_overview|rfc_knowledge|uncategorized"
        string heading
        string summary "curated, no raw text"
        list keywords
        string summary_model
    }

    SectionIndexEntry {
        string section_id PK
        string product_code FK
        string product_family_code FK "base code for RFC family match"
        enum category
        int priority "rfc_knowledge=4 > debug_learning=3 > hld=2 > product_overview=1"
        map token_weights
        int byte_offset
        int byte_length
    }

    KnownFailureEntry {
        string symptom
        string log_signature
        string failing_step
        string root_cause
        string corrective_action
        list rfc_references "RfcReference[]"
    }

    RfcReference {
        string rfc_id
        string notes
        string failed_test_name
        string error_message_or_finding
    }

    AcronymDefinition {
        string acronym
        string definition
    }

    LimitSpecRecord {
        string name
        string value
        string unit
    }

    KnowledgeContext {
        string product_code FK
        string knowledge_hash
        enum match_status "matched|no_match|no_product_knowledge|disabled|no_product_code"
        bool matched
        string context_text "assembled prompt"
    }

    RetrievalMatch {
        string section_id FK
        string product_code FK
        enum category
        float score
        string summary
    }

    AcronymGlossaryEntry {
        string acronym PK
        string definition
        string product_code FK "null = global"
        enum status "approved|needs_review|rejected"
        string notes
    }
```

**Notes**

- `debug_excerpt` / `ExtractedSection.text` are *transient* — used to drive the LLM in-process and never persisted with the curated artifacts.
- `signature` = `SHA1(error_code + normalized error_message)`; it is the dedup key that maps many `UnitRecord`s to a single LLM call and cache entry.
- `knowledge_hash` and `acronym_glossary_hash` are folded into the analysis cache key so approving new knowledge/acronyms invalidates stale diagnoses. Invalidation is **targeted, not global**: `product_code` is itself part of the key, so entries are already partitioned per product. `knowledge_hash` is the per-product manifest hash (`manifest.product_hash(product_code)`), so a doc change for product A invalidates only A's diagnoses. `acronym_glossary_hash` is hashed from *only the approved acronym pairs actually used in that record* (not the whole glossary file), so editing an acronym invalidates only diagnoses that referenced it. A full knowledge rebuild is the exception — LLM re-summarization can shift every per-product hash. Changing the model, prompt version, or provider invalidates everything (those fields are also in the key).
- `SectionIndexEntry.byte_offset` / `byte_length` address the exact line in `product_knowledge_sections.jsonl`, so retrieval only deserializes matched sections.

## Key Architectural Patterns

| Pattern | Where |
| --- | --- |
| Dependency Injection / composition root | `dependencies.py` wires singletons; `orchestrator.py` receives collaborators |
| Protocol-based design (duck typing) | `contracts.py` defines `JobRepository`, `Preprocessor`, `FailureAnalyzer` |
| Cache-aside with source tracking | in-memory signature cache → disk `analysis_cache.py` → LLM |
| Signature deduplication | one LLM call per `SHA1(error_code + normalized message)` per job |
| Grounded LLM prompting | curated knowledge pack + approved acronym glossary injected as trusted context |
| Graceful degradation | Copilot SDK → GitHub Models → deterministic offline stub |
| Atomic writes | job state, cache, and knowledge pack use temp file + `os.replace` |
| PII redaction at boundary | `redaction.py` scrubs serials/IPs/MACs/credentials before LLM + at-rest |

## Component Responsibilities

### Frontend (`frontend/src`)
- **App.jsx** — tab-based SPA shell; batch upload orchestration and polling.
- **auth.jsx** — React `AuthContext` (GitHub OAuth + admin login, session expiry).
- **api.js** — HTTP wrapper mapping to all `/api/*` endpoints; dispatches `cotrace:unauthorized` on 401.
- **Pages** — Home (upload), Engineer (per-unit results), Manager (metrics), Knowledge (docs + acronyms), Login, About.

### Backend (`backend/app`)
- **main.py** — FastAPI routes, middleware, job lifecycle endpoints.
- **orchestrator.py** — background pipeline: preprocess → write artifacts → analyze.
- **preprocessor.py** — parses FTRunner logs into normalized `UnitRecord`s.
- **analyzer.py** — dedups failures by signature; injects knowledge/glossary; calls LLM; caches.
- **aggregator.py** — pure computation of FPY, Pareto, trends, station breakdowns.
- **knowledge/** — ingestion (parse → summarize → store) and lexical retrieval of the product-knowledge pack + acronym glossary.
- **job_registry.py / analysis_cache.py / upload_storage.py** — durable job state, diagnosis cache, and upload handling.
- **copilot_client.py / llm_client.py** — LLM provider adapters with two-tier model policy and offline fallback.
```

