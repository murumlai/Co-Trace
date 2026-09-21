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


def _job(job_id: str, created_at: float, records: list[UnitRecord], *, status: str = "done") -> Job:
    return Job(
        job_id=job_id,
        owner_id="42",
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
    assert compare_jobs(current, [current])["reason"] == "No comparable prior non-duplicate batch is available"


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
        "gap_pp": 5,
        "provenance": "user_entered",
    }
