from __future__ import annotations

from app.aggregator import compute_summary
from app.models import UnitRecord
from app.timestamp_ordering import observed_period, order_chronologically, parse_timestamp


def _record(unit_id: str, start_time: str | None, *, end_time: str | None = None) -> UnitRecord:
    return UnitRecord(
        unit_id=unit_id,
        serial_number="SN-1",
        result="FAIL",
        start_time=start_time,
        end_time=end_time,
        run_folder=unit_id,
    )


def test_parse_timestamp_normalizes_aware_values_and_rejects_invalid_values() -> None:
    zulu = parse_timestamp("2026-01-01T09:00:00Z")
    offset = parse_timestamp("2026-01-01T10:00:00+02:00")

    assert zulu is not None and zulu.utcoffset() is not None
    assert offset is not None and offset.utcoffset() is not None
    assert parse_timestamp("not-a-time") is None
    assert parse_timestamp(None) is None


def test_aware_timestamps_are_ordered_as_utc_instants() -> None:
    earlier = _record("fail", "2026-01-01T10:00:00+02:00")
    later = _record("pass", "2026-01-01T09:00:00Z")

    ordering = order_chronologically([later, earlier])

    assert [record.unit_id for record in ordering.records] == ["fail", "pass"]
    assert ordering.unavailable_reason is None


def test_missing_start_uses_end_time_fallback() -> None:
    earlier = _record("earlier", None, end_time="2026-01-01T08:00:00")
    later = _record("later", "2026-01-01T09:00:00")

    ordering = order_chronologically([later, earlier])

    assert [record.unit_id for record in ordering.records] == ["earlier", "later"]
    assert ordering.unavailable_reason is None


def test_mixed_missing_invalid_and_equal_times_are_unavailable() -> None:
    cases = [
        (
            [_record("aware", "2026-01-01T08:00:00Z"), _record("naive", "2026-01-01T09:00:00")],
            "Mixed timezone styles",
        ),
        ([_record("known", "2026-01-01T08:00:00"), _record("missing", None)], "Missing timestamp"),
        ([_record("known", "2026-01-01T08:00:00"), _record("invalid", "bad")], "Invalid timestamp"),
        (
            [_record("one", "2026-01-01T08:00:00"), _record("two", "2026-01-01T08:00:00")],
            "Equal timestamps",
        ),
    ]

    for records, expected in cases:
        ordering = order_chronologically(records)
        assert ordering.unavailable_reason is not None
        assert expected in ordering.unavailable_reason


def test_single_attempt_does_not_require_a_timestamp_to_establish_order() -> None:
    record = _record("only", None)

    ordering = order_chronologically([record])

    assert ordering.records == [record]
    assert ordering.unavailable_reason is None


def test_summary_uses_utc_order_for_first_latest_and_recovery() -> None:
    failure = _record("fail", "2026-01-01T10:00:00+02:00")
    passing = _record("pass", "2026-01-01T09:00:00Z")
    passing.result = "PASS"

    summary = compute_summary([passing, failure])

    assert summary["fpy_pass"] == 0
    assert summary["fpy_total"] == 1
    assert summary["passed"] == 1
    assert summary["recovered_after_retry"] == 1


def test_summary_excludes_incomparable_unit_from_chronological_denominators() -> None:
    aware = _record("aware", "2026-01-01T09:00:00Z")
    naive = _record("naive", "2026-01-01T10:00:00")
    naive.result = "PASS"

    summary = compute_summary([aware, naive])

    assert summary["unique_units"] == 1
    assert summary["fpy_total"] == 0
    assert summary["latest_yield_total"] == 0
    assert summary["unknown"] == 1
    assert summary["chronology_unavailable_units"] == 1


def test_observed_period_uses_utc_extrema_and_rejects_mixed_styles() -> None:
    earlier = _record(
        "earlier",
        "2026-01-01T10:00:00+02:00",
        end_time="2026-01-01T10:30:00+02:00",
    )
    later = _record(
        "later",
        "2026-01-01T09:00:00Z",
        end_time="2026-01-01T09:30:00Z",
    )

    period = observed_period([later, earlier])
    mixed = observed_period([earlier, _record("naive", "2026-01-01T07:00:00")])

    assert period.start_time == earlier.start_time
    assert period.end_time == later.end_time
    assert period.timezone_style == "offset"
    assert mixed.start_time is None
    assert mixed.end_time is None
    assert mixed.timezone_style == "mixed"
    assert mixed.unavailable_reason is not None