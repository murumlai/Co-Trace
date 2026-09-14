"""Atomic persistence for admin-authored known-failure playbooks."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone

from ..config import settings
from .models import AdminPlaybookEntry, PlaybookCreateRequest, PlaybookUpdateRequest


class AdminPlaybookStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings.PRODUCT_KNOWLEDGE_PLAYBOOKS_FILE
        self._lock = threading.Lock()

    def list_entries(
        self,
        *,
        product_code: str | None = None,
        review_status: str | None = None,
    ) -> list[AdminPlaybookEntry]:
        with self._lock:
            entries = self._load()
        return [
            entry for entry in entries
            if (not product_code or entry.product_code.casefold() == product_code.casefold())
            and (not review_status or entry.review_status == review_status)
        ]

    def create(
        self,
        playbook_id: str,
        request: PlaybookCreateRequest,
        *,
        owner: str,
    ) -> AdminPlaybookEntry:
        now = datetime.now(timezone.utc).isoformat()
        entry = AdminPlaybookEntry(
            playbook_id=playbook_id,
            owner=owner,
            created_at=now,
            updated_at=now,
            **request.model_dump(),
        )
        with self._lock:
            entries = self._load()
            entries.append(entry)
            self._save(entries)
        return entry

    def update(
        self,
        playbook_id: str,
        request: PlaybookUpdateRequest,
    ) -> AdminPlaybookEntry | None:
        with self._lock:
            entries = self._load()
            for index, entry in enumerate(entries):
                if entry.playbook_id != playbook_id:
                    continue
                updates = request.model_dump(exclude_none=True)
                updates["updated_at"] = datetime.now(timezone.utc).isoformat()
                entries[index] = entry.model_copy(update=updates)
                self._save(entries)
                return entries[index]
        return None

    def retire(self, playbook_id: str) -> AdminPlaybookEntry | None:
        return self.update(playbook_id, PlaybookUpdateRequest(review_status="retired"))

    def find_reviewed(
        self,
        *,
        signature: str,
        product_code: str | None,
    ) -> AdminPlaybookEntry | None:
        if not product_code:
            return None
        return next(
            (
                entry for entry in self.list_entries(
                    product_code=product_code,
                    review_status="reviewed",
                )
                if entry.log_signature.casefold() == signature.casefold()
            ),
            None,
        )

    def _load(self) -> list[AdminPlaybookEntry]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            return [AdminPlaybookEntry.model_validate(item) for item in data.get("entries", [])]
        except (OSError, json.JSONDecodeError, ValueError):
            return []

    def _save(self, entries: list[AdminPlaybookEntry]) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="playbooks.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {"schema_version": 1, "entries": [entry.model_dump() for entry in entries]},
                    handle,
                    ensure_ascii=True,
                    separators=(",", ":"),
                )
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)