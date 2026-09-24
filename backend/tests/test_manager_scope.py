from __future__ import annotations

import pytest

from app.aggregator import build_manager_view, station_key
from app.models import UnitRecord


def _record(
    unit_id: str,
    serial: str,
    result: str,
    start_time: str | None,
    *,
    product: str | None = "P1",
    lot: str | None = "LOT-1",
    station: str | None = "01",
    host: str | None = "tester-a",
    message: str = "failure",
) -> UnitRecord:
    return UnitRecord(
        unit_id=unit_id,
        serial_number=serial,
        result=result,
        start_time=start_time,
        product_code=product,
        lot_id=lot,
        station_id=station,
        host=host,
        error_code="E1" if result == "FAIL" else None,
        error_message=message if result == "FAIL" else None,
    )


def _records() -> list[UnitRecord]:
    return [
        _record("p1-fail", "SN-1", "FAIL", "2026-09-20T23:50:00"),
        _record("p1-pass", "SN-1", "PASS", "2026-09-21T00:10:00"),
        _record(
            "p2-fail",
            "SN-2",
            "FAIL",
            "2026-09-21T08:00:00",
            product="P2",
            lot="LOT-2",
            station="02",
            host="tester-b",
            message="second family",
        ),
        _record(
            "unknown-time",
            "SN-3",
            "UNKNOWN",
            None,
            product=None,
            lot=None,
            station=None,
            host=None,
        ),
    ]


def test_product_filter_calculates_first_and_latest_within_selection():
    view = build_manager_view(_records(), product_codes={"P1"})

    assert view["summary"] == {
        "total_runs": 2,
        "failed_attempts": 1,
        "unique_units": 1,
        "passed": 1,
        "failed": 0,
        "unknown": 0,
        "fpy": 0.0,
        "fpy_pass": 0,
        "fpy_total": 1,
        "retests": 1,
        "latest_yield": 100.0,
        "latest_yield_pass": 1,
        "latest_yield_total": 1,
        "recovered_after_retry": 1,
        "additional_attempt_share": 50.0,
    }
    assert view["scope"]["attempt_ids"] == ["p1-fail", "p1-pass"]
    assert view["scope"]["unit_ids"] == ["SN-1"]


def test_composed_product_lot_and_station_filters_use_exact_station_pair():
    records = _records()
    selected_station = station_key(records[2])

    view = build_manager_view(
        records,
        product_codes={"P2"},
        lot_ids={"LOT-2"},
        station_keys={selected_station},
    )

    assert view["scope"]["attempt_ids"] == ["p2-fail"]
    assert view["scope"]["filters"]["stations"] == [selected_station]
    assert view["stations"][0]["key"] == selected_station
    assert view["stations"][0]["attempt_ids"] == ["p2-fail"]
    assert view["stations"][0]["unit_ids"] == ["SN-2"]


def test_time_filter_handles_cross_midnight_and_recalculates_first_observed():
    view = build_manager_view(
        _records(),
        start_time="2026-09-21T00:00:00",
        end_time="2026-09-21T00:30:00",
    )

    assert view["scope"]["attempt_ids"] == ["p1-pass"]
    assert view["summary"]["fpy"] == 100.0
    assert view["summary"]["passed"] == 1
    assert view["scope"]["missing_timestamp_excluded"] == 1


def test_aware_time_filter_excludes_naive_and_missing_source_times():
    records = [
        _record("aware", "SN-A", "PASS", "2026-09-21T08:00:00Z"),
        _record("naive", "SN-B", "PASS", "2026-09-21T08:00:00"),
        _record("missing", "SN-C", "PASS", None),
    ]

    view = build_manager_view(
        records,
        start_time="2026-09-21T07:00:00Z",
        end_time="2026-09-21T09:00:00Z",
    )

    assert view["scope"]["attempt_ids"] == ["aware"]
    assert view["scope"]["missing_timestamp_excluded"] == 2


def test_row_identities_match_displayed_pass_fail_populations():
    records = _records()
    view = build_manager_view(records)

    pareto_ids = {attempt for row in view["pareto"] for attempt in row["attempt_ids"]}
    station_ids = {attempt for row in view["stations"] for attempt in row["attempt_ids"]}
    lot_ids = {attempt for row in view["lots"] for attempt in row["attempt_ids"]}
    trend_ids = {attempt for row in view["trend"] for attempt in row["attempt_ids"]}

    assert pareto_ids == {"p1-fail", "p2-fail"}
    assert station_ids == {"p1-fail", "p1-pass", "p2-fail"}
    assert lot_ids == {"p1-fail", "p1-pass", "p2-fail"}
    assert trend_ids == {"p1-fail", "p1-pass", "p2-fail"}
    assert "unknown-time" not in station_ids | lot_ids | trend_ids


def test_options_include_missing_values_without_fabricating_source_values():
    view = build_manager_view(_records())

    assert {item["value"] for item in view["scope"]["options"]["products"]} == {
        "P1", "P2", "__missing__"
    }
    assert next(
        item["label"] for item in view["scope"]["options"]["products"]
        if item["value"] == "__missing__"
    ) == "Unknown"


def test_empty_filter_result_returns_zero_summary_and_preserves_options():
    view = build_manager_view(_records(), product_codes={"NO-MATCH"})

    assert view["summary"]["total_runs"] == 0
    assert view["scope"]["selected_attempt_count"] == 0
    assert view["scope"]["options"]["products"]


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("not-a-time", None, "Invalid ISO timestamp"),
        ("2026-09-22T00:00:00", "2026-09-21T00:00:00", "must not be after"),
        ("2026-09-21T00:00:00Z", "2026-09-22T00:00:00", "same timezone style"),
    ],
)
def test_invalid_time_filters_are_rejected(start: str, end: str | None, message: str):
    with pytest.raises(ValueError, match=message):
        build_manager_view(_records(), start_time=start, end_time=end)
