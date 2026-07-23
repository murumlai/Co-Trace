"""Tests for per-serial grouping and classification in record_views.

Covers the Engineer-view distinction between first-test-pass, retry-pass, and
consistently-failing units (added for the multi-attempt Engineer feature).
"""
from __future__ import annotations

from app.models import UnitRecord
from app.record_views import (
    classify_attempts,
    group_units_by_serial,
    latest_records_by_serial,
)


def _rec(unit_id: str, serial: str | None, result: str, start: str,
         product: str = "P1") -> UnitRecord:
    return UnitRecord(
        unit_id=unit_id,
        serial_number=serial,
        result=result,
        run_folder=unit_id,
        start_time=start,
        product_code=product,
        station_id="ST1",
    )


class TestClassifyAttempts:
    def test_single_pass_is_first_pass(self):
        attempts = [_rec("a1", "SN1", "PASS", "2026-01-01T10:00:00")]
        assert classify_attempts(attempts) == "first_pass"

    def test_fail_then_pass_is_retry_pass(self):
        attempts = [
            _rec("a1", "SN1", "FAIL", "2026-01-01T10:00:00"),
            _rec("a2", "SN1", "PASS", "2026-01-01T11:00:00"),
        ]
        assert classify_attempts(attempts) == "retry_pass"

    def test_all_fail_is_fail(self):
        attempts = [
            _rec("a1", "SN1", "FAIL", "2026-01-01T10:00:00"),
            _rec("a2", "SN1", "FAIL", "2026-01-01T11:00:00"),
        ]
        assert classify_attempts(attempts) == "fail"

    def test_pass_then_fail_regression_is_fail(self):
        attempts = [
            _rec("a1", "SN1", "PASS", "2026-01-01T10:00:00"),
            _rec("a2", "SN1", "FAIL", "2026-01-01T11:00:00"),
        ]
        assert classify_attempts(attempts) == "fail"

    def test_final_unknown_is_unknown(self):
        attempts = [_rec("a1", "SN1", "UNKNOWN", "2026-01-01T10:00:00")]
        assert classify_attempts(attempts) == "unknown"

    def test_multiple_fails_then_pass_is_retry_pass(self):
        attempts = [
            _rec("a1", "SN1", "FAIL", "2026-01-01T10:00:00"),
            _rec("a2", "SN1", "FAIL", "2026-01-01T11:00:00"),
            _rec("a3", "SN1", "PASS", "2026-01-01T12:00:00"),
        ]
        assert classify_attempts(attempts) == "retry_pass"


class TestGroupUnitsBySerial:
    def _mixed(self) -> list[UnitRecord]:
        return [
            _rec("a1", "SNA", "PASS", "2026-01-01T10:00:00"),   # first_pass
            _rec("b1", "SNB", "FAIL", "2026-01-01T10:00:00"),   # retry_pass
            _rec("b2", "SNB", "PASS", "2026-01-01T11:00:00"),
            _rec("c1", "SNC", "FAIL", "2026-01-01T10:00:00"),   # fail
            _rec("c2", "SNC", "FAIL", "2026-01-01T11:00:00"),
        ]

    def test_one_group_per_serial(self):
        groups = group_units_by_serial(self._mixed())
        assert len(groups) == 3

    def test_classifications(self):
        groups = {g.serial_number: g.classification for g in group_units_by_serial(self._mixed())}
        assert groups == {"SNA": "first_pass", "SNB": "retry_pass", "SNC": "fail"}

    def test_retry_pass_exposes_prior_failure(self):
        groups = group_units_by_serial(self._mixed())
        snb = next(g for g in groups if g.serial_number == "SNB")
        assert snb.result == "PASS"
        assert snb.failure_count == 1
        assert snb.failures[0].unit_id == "b1"
        assert snb.final.unit_id == "b2"

    def test_fail_group_lists_all_failures_and_latest_final(self):
        groups = group_units_by_serial(self._mixed())
        snc = next(g for g in groups if g.serial_number == "SNC")
        assert snc.failure_count == 2
        assert snc.final.unit_id == "c2"
        assert [f.unit_id for f in snc.failures] == ["c1", "c2"]

    def test_first_pass_has_no_failures(self):
        groups = group_units_by_serial(self._mixed())
        sna = next(g for g in groups if g.serial_number == "SNA")
        assert sna.failure_count == 0
        assert sna.failures == []

    def test_failing_units_sorted_first(self):
        groups = group_units_by_serial(self._mixed())
        assert groups[0].classification == "fail"
        assert groups[-1].classification == "first_pass"

    def test_records_without_serial_keyed_by_unit_id(self):
        records = [
            _rec("x1", None, "PASS", "2026-01-01T10:00:00"),
            _rec("x2", None, "FAIL", "2026-01-01T10:00:00"),
        ]
        groups = group_units_by_serial(records)
        assert len(groups) == 2

    def test_attempt_count_reflects_all_runs(self):
        groups = group_units_by_serial(self._mixed())
        snc = next(g for g in groups if g.serial_number == "SNC")
        assert snc.attempt_count == 2

    def test_empty_records(self):
        assert group_units_by_serial([]) == []

    def test_latest_records_by_serial_still_one_per_serial(self):
        """Existing helper must remain unchanged (used by Manager/artifacts)."""
        latest = latest_records_by_serial(self._mixed())
        serials = {r.serial_number for r in latest}
        assert serials == {"SNA", "SNB", "SNC"}
        snb = next(r for r in latest if r.serial_number == "SNB")
        assert snb.result == "PASS"
