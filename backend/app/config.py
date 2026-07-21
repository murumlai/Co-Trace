"""Central configuration. All values overridable via environment variables."""
from __future__ import annotations

import os


class Settings:
    # --- LLM (GitHub Models) ---
    # If no token is present the analyzer falls back to a deterministic offline stub,
    # so the app is fully runnable without any external calls.
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    LLM_ENDPOINT: str = os.getenv("LLM_ENDPOINT", "https://models.inference.ai.azure.com/chat/completions")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")  # cost-efficient default
    LLM_TIMEOUT_S: float = float(os.getenv("LLM_TIMEOUT_S", "30"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "2"))

    # --- Auth (placeholder) ---
    APP_USERNAME: str = os.getenv("APP_USERNAME", "admin")
    APP_PASSWORD: str = os.getenv("APP_PASSWORD", "admin")
    SESSION_TTL_S: int = int(os.getenv("SESSION_TTL_S", str(60 * 60 * 8)))

    # --- Jobs / storage ---
    WORK_DIR: str = os.getenv("WORK_DIR", os.path.join(os.getcwd(), ".cotrace_work"))
    JOB_TTL_S: int = int(os.getenv("JOB_TTL_S", str(60 * 60 * 2)))

    # --- Preprocessing (FTRunner-primary) ---
    DEBUG_EXCERPT_CHAR_BUDGET: int = int(os.getenv("DEBUG_EXCERPT_CHAR_BUDGET", "6000"))
    ZIP_MAX_TOTAL_BYTES: int = int(os.getenv("ZIP_MAX_TOTAL_BYTES", str(200 * 1024 * 1024)))
    ZIP_MAX_FILE_BYTES: int = int(os.getenv("ZIP_MAX_FILE_BYTES", str(100 * 1024 * 1024)))
    ZIP_MAX_DEPTH: int = int(os.getenv("ZIP_MAX_DEPTH", "3"))

    # --- CORS (dev) ---
    CORS_ORIGINS: list[str] = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")


settings = Settings()
