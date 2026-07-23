"""Safety-net tests: upload storage cleanup and zip safety.

Covers cleanup_job_workdir, _safe_join path traversal prevention, and
_extract_zip limits (zip-bomb, too many files, member too large).
"""
from __future__ import annotations

import io
import os
import zipfile

import pytest

from app.upload_storage import (
    UploadStorageError,
    _extract_zip,
    _safe_join,
    cleanup_job_workdir,
)


# ---------------------------------------------------------------------------
# cleanup_job_workdir
# ---------------------------------------------------------------------------

class TestCleanupJobWorkdir:
    def test_removes_everything_except_state_json(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "CLEANUP_JOB_WORKDIR_AFTER_RUN", True)

        workdir = tmp_path / "job1"
        workdir.mkdir()
        (workdir / "job_state.json").write_text("{}")
        (workdir / "some_artifact.json").write_text("{}")
        sub = workdir / "input"
        sub.mkdir()
        (sub / "ftrunnerlog01.txt").write_text("log")

        removed = cleanup_job_workdir(str(workdir))

        assert os.path.isfile(str(workdir / "job_state.json"))
        assert not os.path.exists(str(workdir / "some_artifact.json"))
        assert not os.path.exists(str(sub))
        assert len(removed) > 0

    def test_disabled_when_flag_is_false(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "CLEANUP_JOB_WORKDIR_AFTER_RUN", False)

        workdir = tmp_path / "job2"
        workdir.mkdir()
        (workdir / "some_artifact.json").write_text("{}")

        removed = cleanup_job_workdir(str(workdir))

        assert removed == []
        assert os.path.isfile(str(workdir / "some_artifact.json"))

    def test_returns_empty_list_for_nonexistent_dir(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "CLEANUP_JOB_WORKDIR_AFTER_RUN", True)

        removed = cleanup_job_workdir(str(tmp_path / "nonexistent"))
        assert removed == []

    def test_state_json_absent_still_removes_other_files(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "CLEANUP_JOB_WORKDIR_AFTER_RUN", True)

        workdir = tmp_path / "job3"
        workdir.mkdir()
        (workdir / "data.bin").write_bytes(b"\x00" * 10)

        removed = cleanup_job_workdir(str(workdir))
        assert "data.bin" in removed


# ---------------------------------------------------------------------------
# _safe_join — path traversal prevention
# ---------------------------------------------------------------------------

class TestSafeJoin:
    def test_valid_relative_path(self, tmp_path):
        result = _safe_join(str(tmp_path), "subdir/file.txt")
        assert result == os.path.normpath(os.path.join(str(tmp_path), "subdir", "file.txt"))

    def test_dot_dot_raises(self, tmp_path):
        with pytest.raises(UploadStorageError):
            _safe_join(str(tmp_path), "../escape.txt")

    def test_absolute_component_raises(self, tmp_path):
        with pytest.raises(UploadStorageError):
            _safe_join(str(tmp_path), "C:/Windows/system32")

    def test_backslash_dot_dot_raises(self, tmp_path):
        with pytest.raises(UploadStorageError):
            _safe_join(str(tmp_path), "..\\escape.txt")

    def test_deep_valid_path(self, tmp_path):
        result = _safe_join(str(tmp_path), "a/b/c/file.log")
        assert str(tmp_path) in result
        assert "a" in result


# ---------------------------------------------------------------------------
# _extract_zip — limit checks
# ---------------------------------------------------------------------------

def _make_zip(members: dict[str, bytes]) -> str:
    """Write an in-memory zip to a temp file and return the path."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestExtractZip:
    def _write_zip(self, tmp_path, members: dict[str, bytes]) -> str:
        zip_dir = tmp_path / "zips"
        zip_dir.mkdir(parents=True, exist_ok=True)
        path = str(zip_dir / "test.zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        return path

    def test_extracts_normal_zip(self, tmp_path):
        zip_path = self._write_zip(tmp_path / "zips", {"ftrunnerlog01.txt": b"log content"})
        out_dir = str(tmp_path / "out")
        count = _extract_zip(zip_path, out_dir)
        assert count == 1
        assert os.path.isfile(os.path.join(out_dir, "ftrunnerlog01.txt"))

    def test_extracts_nested_paths(self, tmp_path):
        zip_path = self._write_zip(tmp_path / "zips",
                                   {"run1/ftrunnerlog01.txt": b"log",
                                    "run2/ftrunnerlog01.txt": b"log2"})
        out_dir = str(tmp_path / "out")
        count = _extract_zip(zip_path, out_dir)
        assert count == 2

    def test_rejects_too_many_files(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "UPLOAD_ZIP_MAX_FILES", 2)

        members = {f"file{i}.txt": b"x" for i in range(3)}
        zip_path = self._write_zip(tmp_path / "zips", members)
        with pytest.raises(UploadStorageError, match="too many files"):
            _extract_zip(zip_path, str(tmp_path / "out"))

    def test_rejects_oversized_member(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "UPLOAD_ZIP_MAX_FILE_BYTES", 5)
        monkeypatch.setattr(settings, "UPLOAD_ZIP_MAX_TOTAL_BYTES", 1_000_000)

        zip_path = self._write_zip(tmp_path / "zips", {"big.bin": b"X" * 10})
        with pytest.raises(UploadStorageError, match="too large"):
            _extract_zip(zip_path, str(tmp_path / "out"))

    def test_rejects_oversized_total(self, tmp_path, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "UPLOAD_ZIP_MAX_FILE_BYTES", 1_000_000)
        monkeypatch.setattr(settings, "UPLOAD_ZIP_MAX_TOTAL_BYTES", 10)

        zip_path = self._write_zip(tmp_path / "zips",
                                   {"a.txt": b"X" * 6, "b.txt": b"X" * 6})
        with pytest.raises(UploadStorageError, match="too large"):
            _extract_zip(zip_path, str(tmp_path / "out"))

    def test_rejects_bad_zip(self, tmp_path):
        bad_zip = tmp_path / "zips" / "bad.zip"
        bad_zip.parent.mkdir(parents=True)
        bad_zip.write_bytes(b"this is not a zip file")
        with pytest.raises(UploadStorageError, match="not a valid zip"):
            _extract_zip(str(bad_zip), str(tmp_path / "out"))

    def test_zip_slip_prevention(self, tmp_path):
        """A zip member with a path traversal name must not extract outside dest."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # Use a path that tries to escape; _safe_join will raise
            info = zipfile.ZipInfo("../escape.txt")
            zf.writestr(info, b"evil")
        zip_path = tmp_path / "zips" / "slip.zip"
        zip_path.parent.mkdir(parents=True)
        zip_path.write_bytes(buf.getvalue())

        out_dir = str(tmp_path / "out")
        with pytest.raises(UploadStorageError):
            _extract_zip(str(zip_path), out_dir)

        escaped = os.path.normpath(os.path.join(str(tmp_path), "escape.txt"))
        assert not os.path.exists(escaped)
