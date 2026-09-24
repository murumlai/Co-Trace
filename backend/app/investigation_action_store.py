"""Atomic owner-scoped persistence for versioned investigation actions."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .models import InvestigationActionEntry, InvestigationActionEvent


class ActionNotFound(LookupError):
    pass


class ActionStoreUnavailable(RuntimeError):
    pass


class ActionVersionConflict(RuntimeError):
    def __init__(self, current: InvestigationActionEntry) -> None:
        super().__init__("Investigation action changed; reload and retry")
        self.current = current


class DiskInvestigationActionStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings.INVESTIGATION_ACTION_STORE_FILE
        self._lock = threading.Lock()

    def create(self, entry: InvestigationActionEntry) -> InvestigationActionEntry:
        with self._lock:
            entries = self._active_entries(self._load())
            entries.append(entry)
            self._save(entries)
        return entry

    def list_for_job(self, job_id: str, owner_id: str) -> list[InvestigationActionEntry]:
        with self._lock:
            loaded = self._load()
            entries = self._active_entries(loaded)
            if len(entries) != len(loaded):
                self._save(entries)
        return [entry for entry in entries if entry.job_id == job_id and entry.owner_id == owner_id]

    def update(
        self,
        action_id: str,
        job_id: str,
        owner_id: str,
        expected_version: int,
        *,
        actor_id: str,
        actor_login: str,
        assignee: str | None,
        next_action: str | None,
        status: str | None,
        fields_set: set[str],
    ) -> InvestigationActionEntry:
        with self._lock:
            entries = self._active_entries(self._load())
            index = next((
                i for i, item in enumerate(entries)
                if item.action_id == action_id and item.job_id == job_id and item.owner_id == owner_id
            ), None)
            if index is None:
                raise ActionNotFound("Investigation action not found")
            current = entries[index]
            if current.version != expected_version:
                raise ActionVersionConflict(current)
            updated_at = datetime.now(timezone.utc).isoformat()
            next_assignee = assignee.strip()[:120] or None if "assignee" in fields_set and assignee is not None else (None if "assignee" in fields_set else current.assignee)
            next_text = next_action.strip()[:2000] if "next_action" in fields_set and next_action is not None else current.next_action
            next_status = status or current.status
            version = current.version + 1
            event = InvestigationActionEvent(
                version=version,
                actor_id=actor_id,
                actor_login=actor_login,
                changed_at=updated_at,
                previous_status=current.status,
                status=next_status,
                previous_assignee=current.assignee,
                assignee=next_assignee,
                previous_next_action=current.next_action,
                next_action=next_text,
            )
            updated = current.model_copy(update={
                "assignee": next_assignee,
                "next_action": next_text,
                "status": next_status,
                "version": version,
                "updated_at": updated_at,
                "history": [*current.history, event],
            })
            entries[index] = updated
            self._save(entries)
            return updated

    def _active_entries(self, entries: list[InvestigationActionEntry]) -> list[InvestigationActionEntry]:
        now = time.time()
        return [entry for entry in entries if entry.expires_at > now]

    def _load(self) -> list[InvestigationActionEntry]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            return [InvestigationActionEntry.model_validate(item) for item in data.get("entries", [])]
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ActionStoreUnavailable("Investigation actions cannot be loaded") from exc

    def _save(self, entries: list[InvestigationActionEntry]) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        payload: dict[str, Any] = {
            "schema_version": 1,
            "entries": [entry.model_dump() for entry in entries],
        }
        fd, temporary = tempfile.mkstemp(prefix="investigation-actions.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                try:
                    os.remove(temporary)
                except OSError:
                    pass
