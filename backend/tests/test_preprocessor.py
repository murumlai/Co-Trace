"""Safety-net tests: FTRunner parsing, DebugLog excerpt, product JSON, and
incomplete-folder detection. These lock pre-existing parsing behavior before
any SOLID refactor changes the structure.
"""
from __future__ import annotations

import os
import zipfile

import pytest

from app.preprocessor import (
    FtrunnerPreprocessor,
    _RE_DONE_HEADER,
    _RE_SCAN_HEADER,
    _extract_kv_block,
    _strip_ansi,
    extract_debug_excerpt,
    find_incomplete_folders,
    write_product_jsons,
    build_product_json,
)
from app.models import UnitRecord


# ---------------------------------------------------------------------------
# Helpers to build minimal FTRunner log text
# ---------------------------------------------------------------------------

def _ft_log(*, scan_kv: str = "", body: str = "", done_block: str = "") -> str:
    return (
        "[2025-11-28 09:01:15 INF] scan file content:\n"
        "[2025-11-28 09:01:15 INF] \n"
        f"{scan_kv}\n"
        f"{body}\n"
        f"{done_block}"
    )


def _done_pass(end_time: str = "20251128090120") -> str:
    return (
        "[2025-11-28 09:01:20 INF] done file content:\n"
        "[2025-11-28 09:01:20 INF] \n"
        f"Result=PASS\n"
        f"EndTime={end_time}\n"
    )


def _done_fail(code: str = "E001", msg: str = "Voltage out of range",
               end_time: str = "20251128090120") -> str:
    return (
        "[2025-11-28 09:01:20 INF] done file content:\n"
        "[2025-11-28 09:01:20 INF] \n"
        f"Result=FAIL\n"
        f"EndTime={end_time}\n"
        f"Errorcode={code}\n"
        f"ErrorMsg={msg}\n"
    )


def _write_ftrunner(folder: str, content: str, name: str = "ftrunnerlog01.txt") -> None:
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
        fh.write(content)


# ---------------------------------------------------------------------------
# _extract_kv_block
# ---------------------------------------------------------------------------

class TestExtractKvBlock:
    def test_parses_scan_kv_pairs(self):
        text = _ft_log(scan_kv="SERIALNUMBER=SN001\nPRODUCTCODE=K77469-400\n")
        result = _extract_kv_block(text, _RE_SCAN_HEADER)
        assert result["SERIALNUMBER"] == "SN001"
        assert result["PRODUCTCODE"] == "K77469-400"

    def test_parses_done_kv_pairs(self):
        text = _done_pass()
        result = _extract_kv_block(text, _RE_DONE_HEADER)
        assert result["Result"] == "PASS"
        assert result["EndTime"] == "20251128090120"

    def test_returns_empty_when_header_absent(self):
        result = _extract_kv_block("no header here\n", _RE_SCAN_HEADER)
        assert result == {}

    def test_strips_log_prefix_before_matching(self):
        text = (
            "scan file content:\n"
            "[2025-11-28 09:01:15 INF] \n"
            "[2025-11-28 09:01:15 INF] SERIALNUMBER=SN002\n"
            "[2025-11-28 09:01:15 INF] PRODUCTCODE=K77469-400\n"
            "\n"
        )
        result = _extract_kv_block(text, _RE_SCAN_HEADER)
        assert result.get("SERIALNUMBER") == "SN002"
        assert result.get("PRODUCTCODE") == "K77469-400"

    def test_stops_at_blank_line_after_block_started(self):
        text = (
            "scan file content:\n\n"
            "SERIALNUMBER=SN003\nPRODUCTCODE=K77469-400\n\n"
            "EXTRAKEY=should_not_appear\n"
        )
        result = _extract_kv_block(text, _RE_SCAN_HEADER)
        assert "EXTRAKEY" not in result
        assert result["SERIALNUMBER"] == "SN003"


# ---------------------------------------------------------------------------
# _parse_done_block  (unit tests for the static parsing method)
# ---------------------------------------------------------------------------

class TestParseDoneBlock:
    def test_pass_result_fields(self):
        result = FtrunnerPreprocessor._parse_done_block(_done_pass())
        assert result["result"] == "PASS"
        assert result["error_code"] is None
        assert result["error_message"] is None

    def test_fail_result_fields_populated(self):
        result = FtrunnerPreprocessor._parse_done_block(
            _done_fail("E002", "Temperature exceeded threshold")
        )
        assert result["result"] == "FAIL"
        assert result["error_code"] == "E002"
        assert result["error_message"] == "Temperature exceeded threshold"

    def test_fail_end_time_parsed(self):
        result = FtrunnerPreprocessor._parse_done_block(_done_fail(end_time="20251129120000"))
        assert result["end_time"] == "20251129120000"

    def test_pass_does_not_leak_error_fields(self):
        result = FtrunnerPreprocessor._parse_done_block(_done_pass())
        assert result["error_code"] is None
        assert result["error_message"] is None


# ---------------------------------------------------------------------------
# Implicit PASS / ERR-level fallback
# ---------------------------------------------------------------------------

class TestImplicitPassRule:
    """No done block + no ERR log-level line → implicit PASS (K77469 heuristic)."""

    def test_no_done_no_err_yields_pass(self):
        text = (
            "[2025-11-28 09:01:15 INF] scan file content:\n"
            "[2025-11-28 09:01:15 INF] \n"
            "SERIALNUMBER=SN010\n\n"
            "[2025-11-28 09:01:20 INF] Test complete.\n"
        )
        result = FtrunnerPreprocessor._parse_done_block(text)
        assert result["result"] == "PASS"

    def test_err_line_without_done_block_yields_fail(self):
        text = (
            "[2025-11-28 09:01:15 INF] scan file content:\n"
            "[2025-11-28 09:01:15 INF] \n"
            "SERIALNUMBER=SN011\n\n"
            "09:01:20 ERR] Something failed in the station\n"
        )
        result = FtrunnerPreprocessor._parse_done_block(text)
        assert result["result"] == "FAIL"
        assert result["error_code"] == "UNKNOWN"

    def test_err_fallback_message_is_descriptive(self):
        text = "09:01:20 ERR] timeout\n"
        result = FtrunnerPreprocessor._parse_done_block(text)
        assert result["result"] == "FAIL"
        assert "error" in result["error_message"].lower()


# ---------------------------------------------------------------------------
# ANSI stripping
# ---------------------------------------------------------------------------

class TestAnsiStripping:
    def test_strips_standard_color_codes(self):
        text = "\x1b[34mBlue\x1b[0m and \x1b[41mred\x1b[0m"
        assert _strip_ansi(text) == "Blue and red"

    def test_strips_bracket_only_codes(self):
        # Some FTRunner logs emit `[34m` without ESC
        text = "[34mColored[0m plain"
        assert _strip_ansi(text) == "Colored plain"

    def test_plain_text_unchanged(self):
        text = "Result=PASS\nEndTime=20251128090120\n"
        assert _strip_ansi(text) == text


# ---------------------------------------------------------------------------
# FtrunnerPreprocessor.process_run_folder  (integration)
# ---------------------------------------------------------------------------

class TestProcessRunFolder:
    def _run_folder(self, tmp_path, log_content: str) -> tuple[str, str]:
        root = str(tmp_path)
        run_dir = os.path.join(root, "STC_WW4622_V401___20251128090115")
        _write_ftrunner(run_dir, log_content)
        return root, run_dir

    def test_pass_unit_basic_fields(self, tmp_path):
        log = _ft_log(
            scan_kv="SERIALNUMBER=SN100\nPRODUCTCODE=K77469-400\nSTATIONID=ST01\n",
            done_block=_done_pass(),
        )
        root, run_dir = self._run_folder(tmp_path, log)
        rec = FtrunnerPreprocessor().process_run_folder(run_dir, root)
        assert rec is not None
        assert rec.result == "PASS"
        assert rec.serial_number == "SN100"
        assert rec.product_code == "K77469-400"
        assert rec.station_id == "ST01"

    def test_fail_unit_error_fields(self, tmp_path):
        log = _ft_log(
            scan_kv="SERIALNUMBER=SN101\nPRODUCTCODE=K77469-400\n",
            done_block=_done_fail("E005", "Test failed at voltage step"),
        )
        root, run_dir = self._run_folder(tmp_path, log)
        rec = FtrunnerPreprocessor().process_run_folder(run_dir, root)
        assert rec is not None
        assert rec.result == "FAIL"
        assert rec.error_code == "E005"
        assert rec.error_message == "Test failed at voltage step"
        assert rec.ftrunner_snippet is not None
        assert "FAIL" in rec.ftrunner_snippet

    def test_no_ftrunnerlog_returns_none(self, tmp_path):
        run_dir = os.path.join(str(tmp_path), "run1")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "somefile.bin"), "wb") as f:
            f.write(b"\x00" * 8)
        rec = FtrunnerPreprocessor().process_run_folder(run_dir, str(tmp_path))
        assert rec is None

    def test_implicit_pass_no_done_block(self, tmp_path):
        log = (
            "[2025-11-28 09:01:15 INF] scan file content:\n"
            "[2025-11-28 09:01:15 INF] \n"
            "SERIALNUMBER=SN102\nPRODUCTCODE=K77469-400\n\n"
            "[2025-11-28 09:01:20 INF] All tests complete.\n"
        )
        root, run_dir = self._run_folder(tmp_path, log)
        rec = FtrunnerPreprocessor().process_run_folder(run_dir, root)
        assert rec is not None
        assert rec.result == "PASS"
        assert rec.error_code is None

    def test_ansi_in_log_does_not_corrupt_parsing(self, tmp_path):
        log = (
            "\x1b[32m[2025-11-28 09:01:15 INF]\x1b[0m scan file content:\n"
            "\x1b[32m[2025-11-28 09:01:15 INF]\x1b[0m \n"
            "\x1b[32mSERIALNUMBER=SN103\x1b[0m\n"
            "\x1b[32mPRODUCTCODE=K77469-400\x1b[0m\n\n"
        ) + _done_pass()
        root, run_dir = self._run_folder(tmp_path, log)
        rec = FtrunnerPreprocessor().process_run_folder(run_dir, root)
        assert rec is not None
        assert rec.serial_number == "SN103"
        assert rec.product_code == "K77469-400"

    def test_step_blocks_parsed(self, tmp_path):
        log = _ft_log(
            scan_kv="SERIALNUMBER=SN104\nPRODUCTCODE=K77469-400\n",
            body=(
                "[2025-11-28 09:01:15 INF] ***PowerTest test start.***\n"
                "[2025-11-28 09:01:20 INF] TEST PASSED\n"
                "[2025-11-28 09:01:20 INF] ***PowerTest test end.***\n"
                "[2025-11-28 09:01:20 INF] Test time(hh\\mm\\ss): 00:00:05\n"
            ),
            done_block=_done_pass(),
        )
        root, run_dir = self._run_folder(tmp_path, log)
        rec = FtrunnerPreprocessor().process_run_folder(run_dir, root)
        assert rec is not None
        assert len(rec.steps) == 1
        assert rec.steps[0].name == "PowerTest"
        assert rec.steps[0].result == "PASS"
        assert rec.steps[0].duration_s == 5.0

    def test_failing_step_identified(self, tmp_path):
        # Add a timing line between step end and next step start so the
        # trailing *** of 'test end.***' doesn't trigger a false multi-line
        # regex match via the \s* in _RE_STEP_START.
        log = _ft_log(
            scan_kv="SERIALNUMBER=SN105\nPRODUCTCODE=K77469-400\n",
            body=(
                "[2025-11-28 09:01:15 INF] ***VoltageTest test start.***\n"
                "[2025-11-28 09:01:20 INF] TEST PASSED\n"
                "[2025-11-28 09:01:20 INF] ***VoltageTest test end.***\n"
                "[2025-11-28 09:01:20 INF] Test time(hh\\mm\\ss): 00:00:05\n"
                "[2025-11-28 09:01:21 INF] ***ThermalTest test start.***\n"
                "[2025-11-28 09:01:25 INF] Test failed.\n"
                "[2025-11-28 09:01:25 INF] ***ThermalTest test end.***\n"
                "[2025-11-28 09:01:25 INF] Test time(hh\\mm\\ss): 00:00:04\n"
            ),
            done_block=_done_fail("E003", "Thermal limit exceeded"),
        )
        root, run_dir = self._run_folder(tmp_path, log)
        rec = FtrunnerPreprocessor().process_run_folder(run_dir, root)
        assert rec is not None
        assert rec.failing_step == "ThermalTest"

    def test_device_class_pan_from_text_hint(self, tmp_path):
        log = _ft_log(
            scan_kv="SERIALNUMBER=SN200\nPRODUCTCODE=M13983-700\n",
            body="[2025-11-28 09:01:15 INF] Running hst_et flow\n",
            done_block=_done_pass(),
        )
        root, run_dir = self._run_folder(tmp_path, log)
        rec = FtrunnerPreprocessor().process_run_folder(run_dir, root)
        assert rec is not None
        assert rec.device_class == "pan"

    def test_device_class_aic_from_steps(self, tmp_path):
        log = _ft_log(
            scan_kv="SERIALNUMBER=SN201\nPRODUCTCODE=N32828-201\n",
            body=(
                "[2025-11-28 09:01:15 INF] ***CardTest test start.***\n"
                "[2025-11-28 09:01:20 INF] TEST PASSED\n"
                "[2025-11-28 09:01:20 INF] ***CardTest test end.***\n"
            ),
            done_block=_done_pass(),
        )
        root, run_dir = self._run_folder(tmp_path, log)
        rec = FtrunnerPreprocessor().process_run_folder(run_dir, root)
        assert rec is not None
        assert rec.device_class == "aic"

    def test_unit_id_is_stable_for_same_relative_path(self, tmp_path):
        log = _ft_log(
            scan_kv="SERIALNUMBER=SN300\nPRODUCTCODE=K77469-400\n",
            done_block=_done_pass(),
        )
        root, run_dir = self._run_folder(tmp_path, log)
        rec1 = FtrunnerPreprocessor().process_run_folder(run_dir, root)
        rec2 = FtrunnerPreprocessor().process_run_folder(run_dir, root)
        assert rec1 is not None and rec2 is not None
        assert rec1.unit_id == rec2.unit_id


# ---------------------------------------------------------------------------
# extract_debug_excerpt
# ---------------------------------------------------------------------------

class TestExtractDebugExcerpt:
    def test_anchors_on_error_code(self):
        debug_text = ("noise\n" * 100) + "E001 Voltage fault detected here\n" + ("noise\n" * 100)
        result = extract_debug_excerpt(debug_text, error_code="E001",
                                       error_message=None, failing_step=None)
        assert result is not None
        assert "E001" in result

    def test_anchors_on_error_message_when_code_absent(self):
        debug_text = ("info\n" * 50) + "TemperatureExceeded: sensor read 120C\n" + ("info\n" * 50)
        result = extract_debug_excerpt(debug_text, error_code=None,
                                       error_message="TemperatureExceeded", failing_step=None)
        assert result is not None
        assert "TemperatureExceeded" in result

    def test_anchors_on_failing_step_as_last_resort(self):
        debug_text = ("info\n" * 50) + "ThermalTest: step timed out\n" + ("info\n" * 50)
        result = extract_debug_excerpt(debug_text, error_code=None,
                                       error_message=None, failing_step="ThermalTest")
        assert result is not None
        assert "ThermalTest" in result

    def test_falls_back_to_generic_marker(self):
        debug_text = ("info line\n" * 30) + "RESULT : FAILED\nmore diagnostics\n"
        result = extract_debug_excerpt(debug_text, error_code=None,
                                       error_message=None, failing_step=None)
        assert result is not None

    def test_redacts_password_credential(self):
        debug_text = "Connecting with -u sysc -p tr@nsf3r\nVoltage fault\n"
        result = extract_debug_excerpt(debug_text, error_code=None,
                                       error_message="Voltage fault", failing_step=None)
        assert result is not None
        assert "tr@nsf3r" not in result
        assert "[REDACTED" in result

    def test_redacts_ip_address(self):
        debug_text = "Connecting to 10.250.0.1\nBus error\n"
        result = extract_debug_excerpt(debug_text, error_code=None,
                                       error_message="Bus error", failing_step=None)
        assert result is not None
        assert "10.250.0.1" not in result

    def test_returns_none_for_empty_text(self):
        assert extract_debug_excerpt("", error_code=None, error_message=None, failing_step=None) is None
        assert extract_debug_excerpt("   \n  ", error_code=None, error_message=None, failing_step=None) is None

    def test_respects_char_budget(self):
        debug_text = "A" * 10_000
        result = extract_debug_excerpt(debug_text, error_code=None,
                                       error_message=None, failing_step=None,
                                       char_budget=500)
        assert result is not None
        assert len(result) <= 500


# ---------------------------------------------------------------------------
# find_incomplete_folders
# ---------------------------------------------------------------------------

class TestFindIncompleteFolders:
    def test_flags_folder_without_ftrunnerlog(self, tmp_path):
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        (run_dir / "randomfile.bin").write_bytes(b"\x00" * 10)
        result = find_incomplete_folders(str(tmp_path))
        assert "run1" in result

    def test_does_not_flag_folder_with_ftrunnerlog(self, tmp_path):
        run_dir = tmp_path / "run2"
        run_dir.mkdir()
        (run_dir / "ftrunnerlog01.txt").write_text("scan file content:\n")
        result = find_incomplete_folders(str(tmp_path))
        assert "run2" not in result

    def test_does_not_flag_folder_with_loose_debuglog(self, tmp_path):
        run_dir = tmp_path / "run3"
        run_dir.mkdir()
        (run_dir / "debuglog.txt").write_text("DebugLog content\n")
        result = find_incomplete_folders(str(tmp_path))
        assert "run3" not in result

    def test_does_not_flag_folder_with_debuglog_in_zip(self, tmp_path):
        run_dir = tmp_path / "run4"
        run_dir.mkdir()
        zip_path = run_dir / "NoLotId_20251128.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.writestr("Sequencer 1/DebugLog.txt", "DebugLog content\n")
        result = find_incomplete_folders(str(tmp_path))
        assert "run4" not in result

    def test_skips_extracted_scratch_directory(self, tmp_path):
        """The _cotrace_extracted scratch dir should not itself appear as incomplete."""
        scratch = tmp_path / "_cotrace_extracted"
        scratch.mkdir()
        (scratch / "somefile.bin").write_bytes(b"\x00")
        result = find_incomplete_folders(str(tmp_path))
        assert "_cotrace_extracted" not in result


# ---------------------------------------------------------------------------
# build_product_json
# ---------------------------------------------------------------------------

class TestBuildProductJson:
    def _rec(self, serial: str, result: str, product: str = "K77469-400") -> UnitRecord:
        return UnitRecord(unit_id=serial, serial_number=serial,
                          product_code=product, result=result, run_folder=serial)

    def test_fpy_calculation(self):
        records = [
            self._rec("SN1", "PASS"),
            self._rec("SN2", "PASS"),
            self._rec("SN3", "FAIL"),
            self._rec("SN4", "FAIL"),
        ]
        data = build_product_json("K77469-400", records)
        summary = data["summary"]
        assert summary["total"] == 4
        assert summary["pass"] == 2
        assert summary["fail"] == 2
        assert summary["fpy"] == 50.0

    def test_deduplicates_by_serial_latest_wins(self):
        """Two records for the same serial: the one with the later run_folder wins."""
        from app.record_views import latest_records_by_serial

        r1 = UnitRecord(unit_id="u1", serial_number="SN1", product_code="K77469-400",
                        result="FAIL", run_folder="run1")
        r2 = UnitRecord(unit_id="u2", serial_number="SN1", product_code="K77469-400",
                        result="PASS", run_folder="run2")  # later run_folder > run1
        latest = latest_records_by_serial([r1, r2])
        assert len(latest) == 1
        assert latest[0].result == "PASS"

    def test_empty_records(self):
        data = build_product_json("K77469-400", [])
        assert data["summary"]["total"] == 0
        assert data["summary"]["fpy"] == 0.0

    def test_schema_version_present(self):
        data = build_product_json("K77469-400", [self._rec("SN1", "PASS")])
        assert "schema_version" in data
        assert isinstance(data["schema_version"], int)

    def test_product_code_in_output(self):
        data = build_product_json("MY-PRODUCT", [self._rec("SN1", "PASS", product="MY-PRODUCT")])
        assert data["product_code"] == "MY-PRODUCT"

    def test_write_product_jsons_creates_file(self, tmp_path):
        records = [self._rec("SN1", "PASS"), self._rec("SN2", "FAIL")]
        out_dir = str(tmp_path / "out")
        written = write_product_jsons(records, out_dir)
        assert len(written) == 1
        assert os.path.isfile(written[0])
