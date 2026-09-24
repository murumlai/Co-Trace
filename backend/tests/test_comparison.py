from __future__ import annotations

from app.comparison import compare_jobs
from app.job_registry import Job
from app.models import BatchMetadata, UnitRecord
from app.orchestrator import _batch_fingerprint


def _record(unit_id: str, serial: str, result: str, product: str = "P1") -> UnitRecord:
    return UnitRecord(
        unit_id=unit_id,
        serial_number=serial,
        result=result,
        product_code=product,
        start_time=f"2026-09-2{unit_id[-1]}T08:00:00",
    )


def _job(
    job_id: str,
    created_at: float,
    records: list[UnitRecord],
    *,
    status: str = "done",
    owner_id: str = "42",
) -> Job:
    return Job(
        job_id=job_id,
        owner_id=owner_id,
        status=status,
        created_at=created_at,
        records=records,
        batch=BatchMetadata(
            display_name=job_id,
            product_codes=sorted({record.product_code for record in records if record.product_code}),
            batch_fingerprint=_batch_fingerprint(records),
            observed_start_time=records[0].start_time if records else None,
            observed_end_time=records[-1].start_time if records else None,
        ),
    )


def test_fingerprint_is_stable_for_reordered_attempts_and_changes_with_outcome():
    records = [_record("a1", "SN1", "PASS"), _record("a2", "SN2", "FAIL")]
    duplicate = list(reversed(records))
    changed = [_record("a1", "SN1", "FAIL"), _record("a2", "SN2", "FAIL")]

    assert _batch_fingerprint(records) == _batch_fingerprint(duplicate)
    assert _batch_fingerprint(records) != _batch_fingerprint(changed)
    assert _batch_fingerprint([]) is None


def test_uses_newest_prior_owned_completed_nonduplicate_with_same_product_scope():
    current = _job("current", 40, [_record("c1", "SN1", "PASS"), _record("c2", "SN2", "PASS")])
    duplicate = _job("duplicate", 35, list(current.records))
    other_product = _job("other", 30, [_record("o1", "SN1", "FAIL", "P2")])
    comparable = _job("baseline", 25, [_record("b1", "SN1", "PASS"), _record("b2", "SN2", "FAIL")])
    older = _job("older", 20, [_record("d1", "SN1", "FAIL"), _record("d2", "SN2", "FAIL")])

    result = compare_jobs(current, [older, comparable, other_product, duplicate, current])

    assert result["available"] is True
    assert result["baseline"]["job_id"] == "baseline"
    assert result["metrics"]["latest_observed_unit_yield"]["current"] == 100
    assert result["metrics"]["latest_observed_unit_yield"]["baseline"] == 50
    assert result["metrics"]["latest_observed_unit_yield"]["delta_pp"] == 50
    assert result["scope"]["current_attempts"] == 2
    assert result["scope"]["baseline_attempts"] == 2


def test_incomparable_or_missing_fingerprint_returns_unavailable():
    current = _job("current", 40, [_record("c1", "SN1", "PASS")])
    current.batch.batch_fingerprint = None
    assert compare_jobs(current, [current])["reason"] == "Current batch fingerprint is unavailable"

    current.batch.batch_fingerprint = _batch_fingerprint(current.records)
    assert compare_jobs(current, [current])["reason"] == "No earlier comparable batch"


def test_never_selects_newer_equal_time_or_different_owner_jobs():
    current = _job("current", 40, [_record("c1", "SN1", "PASS")])
    newer = _job("newer", 50, [_record("n1", "SN1", "FAIL")])
    equal = _job("equal", 40, [_record("e1", "SN1", "FAIL")])
    private = _job("private", 30, [_record("p1", "SN1", "FAIL")], owner_id="legacy-owner")

    result = compare_jobs(current, [newer, equal, private])

    assert result["available"] is False
    assert result["reason"] == "No earlier comparable batch"


def test_selected_product_subset_ignores_unrelated_candidate_products():
    current = _job(
        "current",
        40,
        [_record("c1", "SN1", "PASS", "P1"), _record("c2", "SN2", "FAIL", "P2")],
    )
    baseline = _job(
        "baseline",
        30,
        [_record("b1", "SN1", "FAIL", "P1"), _record("b2", "SN2", "PASS", "P3")],
    )

    result = compare_jobs(current, [baseline], product_codes={"P1"})

    assert result["available"] is True
    assert result["baseline"]["job_id"] == "baseline"
    assert result["scope"]["products"] == ["P1"]


def test_duplicate_and_partially_overlapping_selected_populations_are_rejected():
    current_records = [_record("c1", "SN1", "PASS"), _record("c2", "SN2", "FAIL")]
    current = _job("current", 40, current_records)
    duplicate = _job("duplicate", 30, list(reversed(current_records)))
    overlap = _job("overlap", 20, [current_records[0], _record("b2", "SN3", "FAIL")])

    duplicate_result = compare_jobs(current, [duplicate])
    overlap_result = compare_jobs(current, [overlap])

    assert duplicate_result["reason"] == "Only duplicate uploads found"
    assert overlap_result["reason"] == "Comparable batches overlap the selected attempts"


def test_unavailable_legacy_metadata_and_bounded_history_are_disclosed():
    current = _job("current", 40, [_record("c1", "SN1", "PASS")])
    legacy = _job("legacy", 30, [_record("b1", "SN1", "FAIL")])
    legacy.batch.batch_fingerprint = None

    legacy_result = compare_jobs(current, [legacy])
    bounded_result = compare_jobs(current, [legacy], history_complete=False)

    assert legacy_result["reason"] == "Earlier batch metadata is unavailable"
    assert bounded_result["reason"] == "No comparable batch in searched history"


def test_user_entered_target_has_explicit_provenance_and_percentage_point_gap():
    current = _job("current", 40, [_record("c1", "SN1", "PASS")])
    baseline = _job("baseline", 20, [_record("b1", "SN1", "FAIL")])

    result = compare_jobs(
        current,
        [baseline],
        target_metric="latest_observed_unit_yield",
        target_percent=95,
    )

    assert result["target"] == {
        "metric": "latest_observed_unit_yield",
        "percent": 95,
        "available": True,
        "reason": None,
        "gap_pp": 5,
        "provenance": "user_entered",
    }


def test_zero_denominator_metrics_and_target_are_unavailable_not_zero_percent():
    current = _job("current", 40, [_record("c1", "SN1", "UNKNOWN")])
    baseline = _job("baseline", 20, [_record("b2", "SN2", "UNKNOWN")])

    result = compare_jobs(
        current,
        [baseline],
        target_metric="latest_observed_unit_yield",
        target_percent=95,
    )

    metric = result["metrics"]["latest_observed_unit_yield"]
    assert metric["available"] is False
    assert metric["current"] is None
    assert metric["baseline"] is None
    assert metric["delta_pp"] is None
    assert metric["current_numerator"] == 0
    assert metric["current_denominator"] == 0
    assert result["target"]["available"] is False
    assert result["target"]["gap_pp"] is None


def test_observed_zero_success_remains_available():
    current = _job("current", 40, [_record("c1", "SN1", "FAIL")])
    baseline = _job("baseline", 20, [_record("b1", "SN1", "PASS")])

    result = compare_jobs(current, [baseline])

    metric = result["metrics"]["latest_observed_unit_yield"]
    assert metric["available"] is True
    assert metric["current"] == 0
    assert metric["current_numerator"] == 0
    assert metric["current_denominator"] == 1
    assert metric["delta_pp"] == -100


def test_current_time_scope_is_not_replayed_on_baseline():
    current = _job("current", 40, [
        _record("c1", "SN1", "FAIL"),
        _record("c2", "SN2", "PASS"),
    ])
    baseline = _job("baseline", 20, [
        _record("b1", "SN3", "FAIL"),
        _record("b2", "SN4", "PASS"),
    ])

    result = compare_jobs(
        current,
        [baseline],
        start_time="2026-09-22T00:00:00",
    )

    assert result["available"] is True
    assert result["scope"]["current_attempts"] == 1
    assert result["scope"]["baseline_attempts"] == 2
    assert result["scope"]["current_start_time"] == "2026-09-22T00:00:00"
    assert result["scope"]["time_rule"] == "Current metrics use the active time scope; the baseline uses its own full observed period."
