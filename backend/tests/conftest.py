"""Shared pytest fixtures for the Co_Trace backend test suite."""
from __future__ import annotations

import os
import pytest


@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    """Override WORK_DIR and cache file to a temp directory, and disable
    post-run cleanup so tests can assert on output files."""
    from app.config import settings

    monkeypatch.setattr(settings, "WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setattr(settings, "ANALYSIS_CACHE_FILE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(settings, "CLEANUP_JOB_WORKDIR_AFTER_RUN", False)
    os.makedirs(settings.WORK_DIR, exist_ok=True)
    return settings
