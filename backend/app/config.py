"""Central configuration. All values overridable via environment variables."""
from __future__ import annotations

import os


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# Repo root = two levels above this file (backend/app/config.py -> repo root).
# Product-knowledge artifacts are generated here regardless of the process CWD.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _repo_path(*parts: str) -> str:
    return os.path.join(_REPO_ROOT, *parts)


class Settings:
    # --- LLM provider selection ---
    # Routes failed-unit diagnosis. One of: "github_models" | "copilot_sdk" |
    # "offline_stub". Default preserves the original GitHub Models behavior
    # (which itself degrades to the offline stub when GITHUB_TOKEN is unset).
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "copilot_sdk")

    # --- LLM (GitHub Models) ---
    # If no token is present the analyzer falls back to a deterministic offline stub,
    # so the app is fully runnable without any external calls.
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    LLM_ENDPOINT: str = os.getenv("LLM_ENDPOINT", "https://models.inference.ai.azure.com/chat/completions")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-5.4-mini")  # cost-efficient default
    LLM_TIMEOUT_S: float = float(os.getenv("LLM_TIMEOUT_S", "30"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "2"))

    # --- LLM (GitHub Copilot SDK provider) ---
    # Two-tier model policy: a cheap "mini" model summarizes/classifies the
    # bounded redacted excerpt; a larger "reasoning" model produces the final
    # root cause and suggested solution. Both default to the mini model so a
    # single-model setup works out of the box.
    COPILOT_MINI_MODEL: str = os.getenv("COPILOT_MINI_MODEL", "gpt-5.4-mini")
    COPILOT_REASONING_MODEL: str = os.getenv("COPILOT_REASONING_MODEL", "claude-sonnet-4.6")
    COPILOT_PROXY: str = os.getenv("COPILOT_PROXY", "http://proxy-us.intel.com:912")
    COPILOT_TIMEOUT_S: float = float(os.getenv("COPILOT_TIMEOUT_S", "60"))
    # Run the mini enrichment/summarization pass before the reasoning call.
    COPILOT_ENABLE_MINI_ENRICH: bool = _env_flag("COPILOT_ENABLE_MINI_ENRICH", True)
    # Cost display uses token-credit estimates unless a provider returns exact
    # usage. Adjust this if your internal credit accounting uses a different unit.
    LLM_TOKEN_CREDIT_SIZE: int = int(os.getenv("LLM_TOKEN_CREDIT_SIZE", "1000"))

    # --- Auth (placeholder) ---
    APP_USERNAME: str = os.getenv("APP_USERNAME", "admin")
    APP_PASSWORD: str = os.getenv("APP_PASSWORD", "admin")
    SESSION_TTL_S: int = int(os.getenv("SESSION_TTL_S", str(60 * 60 * 8)))

    # --- Jobs / storage ---
    WORK_DIR: str = os.getenv("WORK_DIR", os.path.join(os.getcwd(), ".cotrace_work"))
    JOB_TTL_S: int = int(os.getenv("JOB_TTL_S", str(60 * 60 * 24 * 30)))  # 30 days

    # --- Logging ---
    APP_DEBUG: bool = _env_flag("COTRACE_DEBUG", False) or _env_flag("APP_DEBUG", False)
    LOG_DIR: str = os.getenv("LOG_DIR", os.getcwd())
    BACKEND_LOG_FILE: str = os.getenv("BACKEND_LOG_FILE", os.path.join(LOG_DIR, "backendLog.txt"))
    FRONTEND_LOG_FILE: str = os.getenv("FRONTEND_LOG_FILE", os.path.join(LOG_DIR, "frontend_Log.txt"))
    FRONTEND_LOG_MAX_CONTEXT_CHARS: int = int(os.getenv("FRONTEND_LOG_MAX_CONTEXT_CHARS", "4000"))
    ANALYSIS_CACHE_ENABLED: bool = _env_flag("ANALYSIS_CACHE_ENABLED", True)
    ANALYSIS_CACHE_FILE: str = os.getenv("ANALYSIS_CACHE_FILE", os.path.join(WORK_DIR, "analysis_cache.json"))
    UPLOAD_ZIP_MAX_FILES: int = int(os.getenv("UPLOAD_ZIP_MAX_FILES", "20000"))
    UPLOAD_ZIP_MAX_TOTAL_BYTES: int = int(os.getenv("UPLOAD_ZIP_MAX_TOTAL_BYTES", str(2 * 1024 * 1024 * 1024)))
    UPLOAD_ZIP_MAX_FILE_BYTES: int = int(os.getenv("UPLOAD_ZIP_MAX_FILE_BYTES", str(512 * 1024 * 1024)))
    CLEANUP_JOB_WORKDIR_AFTER_RUN: bool = _env_flag("CLEANUP_JOB_WORKDIR_AFTER_RUN", True)

    # --- Preprocessing (FTRunner-primary) ---
    DEBUG_EXCERPT_CHAR_BUDGET: int = int(os.getenv("DEBUG_EXCERPT_CHAR_BUDGET", "6000"))
    FTRUNNER_SNIPPET_CHAR_BUDGET: int = int(os.getenv("FTRUNNER_SNIPPET_CHAR_BUDGET", "2000"))
    ZIP_MAX_TOTAL_BYTES: int = int(os.getenv("ZIP_MAX_TOTAL_BYTES", str(200 * 1024 * 1024)))
    ZIP_MAX_FILE_BYTES: int = int(os.getenv("ZIP_MAX_FILE_BYTES", str(100 * 1024 * 1024)))
    ZIP_MAX_DEPTH: int = int(os.getenv("ZIP_MAX_DEPTH", "3"))

    # --- Preprocessed JSON artifact ---
    # schema_version is stamped into every emitted <product_code>.json so
    # consumers can detect the compact contract. "compact" mode omits empty/
    # default fields, drops always-empty diagnosis placeholders, caps snippets
    # and writes minified JSON. "legacy" mode preserves the original pretty,
    # fully-populated shape. PRETTY forces indentation for debugging; GZIP
    # writes an additional <product_code>.json.gz alongside the raw file.
    PREPROCESSED_SCHEMA_VERSION: int = 2
    PREPROCESSED_JSON_FORMAT: str = os.getenv("PREPROCESSED_JSON_FORMAT", "compact")  # compact | legacy
    PREPROCESSED_JSON_PRETTY: bool = _env_flag("PREPROCESSED_JSON_PRETTY", False)
    PREPROCESSED_JSON_GZIP: bool = _env_flag("PREPROCESSED_JSON_GZIP", False)

    # --- Product-aware diagnosis (knowledge pack) ---
    # When enabled, failed-unit diagnosis retrieves curated product summaries by
    # PRODUCTCODE and sends only those summaries (never whole documents or raw
    # extracted text) alongside the bounded redacted failure excerpt.
    PRODUCT_KNOWLEDGE_ENABLED: bool = _env_flag("PRODUCT_KNOWLEDGE_ENABLED", True)
    # Repo-root generated artifacts (gitignored; may contain proprietary summaries).
    PRODUCT_KNOWLEDGE_MANIFEST_FILE: str = os.getenv(
        "PRODUCT_KNOWLEDGE_MANIFEST_FILE", _repo_path("product_knowledge.json")
    )
    PRODUCT_KNOWLEDGE_INDEX_FILE: str = os.getenv(
        "PRODUCT_KNOWLEDGE_INDEX_FILE", _repo_path("product_knowledge_index.json")
    )
    PRODUCT_KNOWLEDGE_SECTIONS_FILE: str = os.getenv(
        "PRODUCT_KNOWLEDGE_SECTIONS_FILE", _repo_path("product_knowledge_sections.jsonl")
    )
    # Source folders scanned for supporting product documents. Both are optional.
    PRODUCT_KNOWLEDGE_SOURCE_DIRS: list[str] = [
        p for p in os.getenv(
            "PRODUCT_KNOWLEDGE_SOURCE_DIRS",
            os.pathsep.join([_repo_path("Log_Files_Folder"), _repo_path("product_docs")]),
        ).split(os.pathsep) if p.strip()
    ]
    # Curated-docs folder used by the Knowledge UI upload route.
    PRODUCT_KNOWLEDGE_DOCS_DIR: str = os.getenv(
        "PRODUCT_KNOWLEDGE_DOCS_DIR", _repo_path("product_docs")
    )
    # Filename globs treated as supported source documents.
    PRODUCT_KNOWLEDGE_SCAN_GLOBS: list[str] = [
        g for g in os.getenv(
            "PRODUCT_KNOWLEDGE_SCAN_GLOBS", "*.pdf,*.docx"
        ).split(",") if g.strip()
    ]
    # Retrieval / prompt budgets.
    PRODUCT_KNOWLEDGE_TOP_K: int = int(os.getenv("PRODUCT_KNOWLEDGE_TOP_K", "4"))
    PRODUCT_KNOWLEDGE_MAX_CONTEXT_CHARS: int = int(
        os.getenv("PRODUCT_KNOWLEDGE_MAX_CONTEXT_CHARS", "4000")
    )
    # Sectioning bounds for parsed documents (chars).
    PRODUCT_KNOWLEDGE_SECTION_MAX_CHARS: int = int(
        os.getenv("PRODUCT_KNOWLEDGE_SECTION_MAX_CHARS", "6000")
    )
    PRODUCT_KNOWLEDGE_SECTION_MIN_CHARS: int = int(
        os.getenv("PRODUCT_KNOWLEDGE_SECTION_MIN_CHARS", "200")
    )
    # Upload limits for the Knowledge UI (single-document uploads).
    PRODUCT_KNOWLEDGE_UPLOAD_MAX_BYTES: int = int(
        os.getenv("PRODUCT_KNOWLEDGE_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024))
    )
    # Ingestion-time summarization model (GPT 5.4-mini per plan).
    PRODUCT_KNOWLEDGE_SUMMARY_MODEL: str = os.getenv(
        "PRODUCT_KNOWLEDGE_SUMMARY_MODEL", "gpt-5.4-mini"
    )

    # --- CORS (dev) ---
    CORS_ORIGINS: list[str] = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")


settings = Settings()
