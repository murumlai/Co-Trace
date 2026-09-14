"""Atomic file-backed persistence for owner-scoped engineer feedback."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Any

from .config import settings
from .models import FeedbackEntry


class DiskFeedbackStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings.FEEDBACK_STORE_FILE
        self._lock = threading.Lock()

    def add(self, entry: FeedbackEntry) -> FeedbackEntry:
        with self._lock:
            entries = self._active_entries(self._load())
            entries.append(entry)
            self._save(entries)
        return entry

    def list_for_job(self, job_id: str, owner_id: str) -> list[FeedbackEntry]:
        with self._lock:
            entries = self._active_entries(self._load())
            self._save(entries)
        return [
            entry for entry in entries
            if entry.job_id == job_id and entry.owner_id == owner_id
        ]

    def _active_entries(self, entries: list[FeedbackEntry]) -> list[FeedbackEntry]:
        now = time.time()
        return [entry for entry in entries if entry.expires_at > now]

    def _load(self) -> list[FeedbackEntry]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            return [FeedbackEntry.model_validate(item) for item in data.get("entries", [])]
        except (OSError, json.JSONDecodeError, ValueError):
            return []

    def _save(self, entries: list[FeedbackEntry]) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        payload: dict[str, Any] = {
            "schema_version": 1,
            "entries": [entry.model_dump() for entry in entries],
        }
        fd, temporary = tempfile.mkstemp(prefix="feedback.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)