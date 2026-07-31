"""Read/write the repo-root product-knowledge artifacts.

Three files make up the pack:

* ``product_knowledge.json``          — manifest (products, docs, hashes, counts)
* ``product_knowledge_index.json``    — retrieval index partitioned by product
* ``product_knowledge_sections.jsonl``— one curated ``KnowledgeSection`` per
  line, byte-offset addressable so the retriever reads only matched sections.

Writes are atomic (temp file + ``os.replace``). The JSONL is written in binary
so byte offsets recorded in the index are exact.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

from ..config import settings
from .models import (
    KnowledgeIndex,
    KnowledgeManifest,
    KnowledgeSection,
    SectionIndexEntry,
)

log = logging.getLogger("cotrace.knowledge")


class KnowledgeStore:
    """File-backed reader/writer for the knowledge pack artifacts."""

    def __init__(
        self,
        manifest_path: str | None = None,
        index_path: str | None = None,
        sections_path: str | None = None,
    ) -> None:
        self.manifest_path = manifest_path or settings.PRODUCT_KNOWLEDGE_MANIFEST_FILE
        self.index_path = index_path or settings.PRODUCT_KNOWLEDGE_INDEX_FILE
        self.sections_path = sections_path or settings.PRODUCT_KNOWLEDGE_SECTIONS_FILE

    # --- write ---------------------------------------------------------------

    def write_pack(
        self,
        manifest: KnowledgeManifest,
        index: KnowledgeIndex,
        sections: list[KnowledgeSection],
    ) -> None:
        """Write all three artifacts, wiring exact JSONL byte offsets into the
        index entries as sections are serialized."""
        offsets = self._write_sections(sections)
        for entries in index.by_product.values():
            for entry in entries:
                span = offsets.get(entry.section_id)
                if span is not None:
                    entry.byte_offset, entry.byte_length = span
        self._atomic_write_text(
            self.index_path, index.model_dump_json(exclude_none=True)
        )
        self._atomic_write_text(
            self.manifest_path, manifest.model_dump_json(exclude_none=True)
        )
        log.info(
            "Wrote product-knowledge pack: %s sections, %s products.",
            len(sections),
            len(index.by_product),
        )

    def _write_sections(self, sections: list[KnowledgeSection]) -> dict[str, tuple[int, int]]:
        directory = os.path.dirname(self.sections_path) or "."
        os.makedirs(directory, exist_ok=True)
        offsets: dict[str, tuple[int, int]] = {}
        fd, tmp = tempfile.mkstemp(prefix="pk_sections.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "wb") as fh:
                position = 0
                for section in sections:
                    line = section.model_dump_json(exclude_none=True).encode("utf-8")
                    offsets[section.section_id] = (position, len(line))
                    fh.write(line)
                    fh.write(b"\n")
                    position += len(line) + 1
            os.replace(tmp, self.sections_path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return offsets

    def _atomic_write_text(self, path: str, text: str) -> None:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="pk.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # --- read ----------------------------------------------------------------

    def exists(self) -> bool:
        return os.path.exists(self.manifest_path) and os.path.exists(self.index_path)

    def load_manifest(self) -> KnowledgeManifest | None:
        data = self._load_json(self.manifest_path)
        if data is None:
            return None
        try:
            return KnowledgeManifest.model_validate(data)
        except Exception:  # noqa: BLE001 - tolerate a stale/corrupt artifact
            log.exception("Could not parse knowledge manifest %s.", self.manifest_path)
            return None

    def load_index(self) -> KnowledgeIndex | None:
        data = self._load_json(self.index_path)
        if data is None:
            return None
        try:
            return KnowledgeIndex.model_validate(data)
        except Exception:  # noqa: BLE001
            log.exception("Could not parse knowledge index %s.", self.index_path)
            return None

    def read_section(self, entry: SectionIndexEntry) -> KnowledgeSection | None:
        """Read a single curated section using its recorded byte span."""
        if entry.byte_length <= 0:
            return None
        try:
            with open(self.sections_path, "rb") as fh:
                fh.seek(entry.byte_offset)
                raw = fh.read(entry.byte_length)
        except OSError:
            log.exception("Could not read section %s from JSONL.", entry.section_id)
            return None
        try:
            return KnowledgeSection.model_validate_json(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            log.exception("Could not parse section %s from JSONL.", entry.section_id)
            return None

    def iter_sections(self) -> list[KnowledgeSection]:
        """Read every curated section (admin/preview use, not hot-path)."""
        if not os.path.exists(self.sections_path):
            return []
        out: list[KnowledgeSection] = []
        with open(self.sections_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(KnowledgeSection.model_validate_json(line))
                except Exception:  # noqa: BLE001
                    continue
        return out

    def delete_pack(self) -> None:
        for path in (self.manifest_path, self.index_path, self.sections_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                log.exception("Could not delete knowledge artifact %s.", path)

    @staticmethod
    def _load_json(path: str) -> dict[str, Any] | None:
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            log.exception("Could not read knowledge artifact %s.", path)
            return None
