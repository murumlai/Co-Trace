"""Upload persistence and safe root-level zip extraction."""
from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass
from typing import Sequence

from fastapi import UploadFile

from .config import settings

_INPUT_DIR = "input"
_INCOMING_DIR = "_incoming"
_CHUNK_SIZE = 1024 * 1024


class UploadStorageError(ValueError):
    """Raised for user-correctable upload storage/extraction problems."""


@dataclass(frozen=True)
class StoredUploadSummary:
    file_count: int = 0
    zip_count: int = 0
    extracted_file_count: int = 0


def get_job_input_root(workdir: str) -> str:
    """Return the directory the preprocessor should scan for this job.

    New jobs store uploaded/extracted inputs under ``<workdir>/input`` so the
    job root can keep only persistent job state. Older restored jobs may still
    have inputs directly in the job root, so fall back for compatibility.
    """
    input_root = os.path.join(workdir, _INPUT_DIR)
    return input_root if os.path.isdir(input_root) else workdir


async def save_uploads(
    files: Sequence[UploadFile], paths: Sequence[str], workdir: str, job_label: str
) -> StoredUploadSummary:
    """Save regular uploaded files and extract root-level ``.zip`` archives.

    Root-level zip archives are treated as batch containers and extracted into
    the job input directory. Zip files inside uploaded folders are preserved as
    regular files because they are often per-run DebugLog archives.
    """
    input_root = os.path.join(workdir, _INPUT_DIR)
    incoming_root = os.path.join(workdir, _INCOMING_DIR)
    os.makedirs(input_root, exist_ok=True)
    os.makedirs(incoming_root, exist_ok=True)

    root_zip_indexes = {
        i for i, upload in enumerate(files)
        if _is_root_zip(_upload_relpath(upload, paths, i))
    }
    multi_zip = len(root_zip_indexes) > 1

    regular_files = 0
    extracted_files = 0
    for i, upload in enumerate(files):
        rel = _upload_relpath(upload, paths, i)
        if i in root_zip_indexes:
            tmp_path = _safe_join(incoming_root, f"{i}_{os.path.basename(rel)}")
            await _write_upload(upload, tmp_path)
            zip_root = input_root
            if multi_zip:
                zip_root = os.path.join(input_root, f"zip_{i}_{_safe_name(os.path.splitext(os.path.basename(rel))[0])}")
            extracted_files += _extract_zip(tmp_path, zip_root)
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            continue

        dest = _safe_join(input_root, rel)
        await _write_upload(upload, dest)
        regular_files += 1

    return StoredUploadSummary(
        file_count=regular_files + extracted_files,
        zip_count=len(root_zip_indexes),
        extracted_file_count=extracted_files,
    )


def _upload_relpath(upload: UploadFile, paths: Sequence[str], index: int) -> str:
    raw = paths[index] if index < len(paths) and paths[index] else (upload.filename or f"file_{index}")
    rel = raw.replace("\\", "/").lstrip("/")
    if not rel or rel.endswith("/"):
        raise UploadStorageError("Invalid uploaded file path.")
    return rel


def _is_root_zip(rel: str) -> bool:
    return rel.lower().endswith(".zip") and "/" not in rel and "\\" not in rel


def _safe_join(base: str, rel: str) -> str:
    rel = rel.replace("\\", "/").lstrip("/")
    parts = [part for part in rel.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." or ":" in part for part in parts):
        raise UploadStorageError(f"Invalid uploaded file path: {rel}")
    target = os.path.normpath(os.path.join(base, *parts))
    base_norm = os.path.normpath(base)
    if target != base_norm and not target.startswith(base_norm + os.sep):
        raise UploadStorageError(f"Invalid uploaded file path: {rel}")
    return target


async def _write_upload(upload: UploadFile, dest: str) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as out:
        while True:
            chunk = await upload.read(_CHUNK_SIZE)
            if not chunk:
                break
            out.write(chunk)


def _extract_zip(zip_path: str, dest_root: str) -> int:
    os.makedirs(dest_root, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = [info for info in zf.infolist() if not info.is_dir()]
            if len(infos) > settings.UPLOAD_ZIP_MAX_FILES:
                raise UploadStorageError(
                    f"Zip contains too many files ({len(infos)}). Limit is {settings.UPLOAD_ZIP_MAX_FILES}."
                )
            total_bytes = 0
            for info in infos:
                if info.file_size > settings.UPLOAD_ZIP_MAX_FILE_BYTES:
                    raise UploadStorageError(
                        f"Zip member is too large: {info.filename} ({info.file_size} bytes)."
                    )
                total_bytes += info.file_size
                if total_bytes > settings.UPLOAD_ZIP_MAX_TOTAL_BYTES:
                    raise UploadStorageError(
                        f"Zip is too large after extraction ({total_bytes} bytes)."
                    )

            count = 0
            for info in infos:
                target = _safe_join(dest_root, info.filename)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    copied = 0
                    while True:
                        chunk = src.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > settings.UPLOAD_ZIP_MAX_FILE_BYTES:
                            raise UploadStorageError(f"Zip member exceeded size limit: {info.filename}")
                        out.write(chunk)
                count += 1
            return count
    except zipfile.BadZipFile as exc:
        raise UploadStorageError("Uploaded .zip file is not a valid zip archive.") from exc


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)[:80] or "archive"
