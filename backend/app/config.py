"""Central configuration. All values overridable via environment variables."""
from __future__ import annotations

import os


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


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

    # --- CORS (dev) ---
    CORS_ORIGINS: list[str] = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")


settings = Settings()
