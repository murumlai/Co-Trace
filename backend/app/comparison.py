"""Owner-scoped, deterministic comparison of completed batch jobs."""
from __future__ import annotations

from typing import Any

from .aggregator import build_manager_view, filter_records
from .fingerprints import batch_fingerprint

_METRICS = {
    "first_observed_pass_rate": ("fpy", "fpy_total"),
    "latest_observed_unit_yield": ("latest_yield", "latest_yield_total"),
}


def compare_jobs(
    current: Any,
    candidates: list[Any],
    *,
    product_codes: set[str] | None = None,
    lot_ids: set[str] | None = None,
    station_keys: set[str] | None = None,
    target_metric: str | None = None,
    target_percent: float | None = None,
    history_complete: bool = True,
) -> dict:
    if not current.batch.batch_fingerprint:
        return _unavailable("Current batch fingerprint is unavailable")

    products = set(product_codes or current.batch.product_codes)
    current_records, _ = filter_records(
        current.records,
        product_codes=products,
        lot_ids=lot_ids,
        station_keys=station_keys,
    )
    current_view = build_manager_view(
        current_records,
        product_codes=products,
        lot_ids=lot_ids,
        station_keys=station_keys,
    )
    if not current_view["summary"]["total_runs"]:
        return _unavailable("Current comparison scope has no attempts")
    current_products = {record.product_code for record in current_records}
    current_fingerprint = batch_fingerprint(current_records)
    current_attempt_ids = {record.unit_id for record in current_records}

    baseline = None
    baseline_view = None
    rejection_reasons: set[str] = set()
    for candidate in sorted(candidates, key=lambda job: (job.created_at, job.job_id), reverse=True):
        if candidate.job_id == current.job_id:
            continue
        if candidate.owner_id != current.owner_id:
            rejection_reasons.add("owner")
            continue
        if candidate.created_at >= current.created_at:
            rejection_reasons.add("not_prior")
            continue
        if candidate.status != "done":
            rejection_reasons.add("not_complete")
            continue
        if not candidate.batch.batch_fingerprint:
            rejection_reasons.add("missing_fingerprint")
            continue
        candidate_records, _ = filter_records(
            candidate.records,
            product_codes=products,
            lot_ids=lot_ids,
            station_keys=station_keys,
        )
        candidate_products = {record.product_code for record in candidate_records}
        if candidate_products != current_products:
            rejection_reasons.add("product_mismatch")
            continue
        candidate_fingerprint = batch_fingerprint(candidate_records)
        if candidate_fingerprint == current_fingerprint:
            rejection_reasons.add("duplicate")
            continue
        candidate_attempt_ids = {record.unit_id for record in candidate_records}
        if current_attempt_ids.intersection(candidate_attempt_ids):
            rejection_reasons.add("overlap")
            continue
        view = build_manager_view(
            candidate_records,
            product_codes=products,
            lot_ids=lot_ids,
            station_keys=station_keys,
        )
        if not view["summary"]["total_runs"]:
            continue
        baseline = candidate
        baseline_view = view
        break

    if baseline is None or baseline_view is None:
        return _unavailable(_unavailable_reason(rejection_reasons, history_complete))

    comparisons = {}
    for name, (value_key, denominator_key) in _METRICS.items():
        current_value = float(current_view["summary"].get(value_key) or 0)
        baseline_value = float(baseline_view["summary"].get(value_key) or 0)
        comparisons[name] = {
            "current": current_value,
            "baseline": baseline_value,
            "delta_pp": round(current_value - baseline_value, 2),
            "current_denominator": int(current_view["summary"].get(denominator_key) or 0),
            "baseline_denominator": int(baseline_view["summary"].get(denominator_key) or 0),
        }

    target = None
    if target_percent is not None:
        metric = target_metric if target_metric in _METRICS else "first_observed_pass_rate"
        value_key = _METRICS[metric][0]
        current_value = float(current_view["summary"].get(value_key) or 0)
        target = {
            "metric": metric,
            "percent": target_percent,
            "gap_pp": round(current_value - target_percent, 2),
            "provenance": "user_entered",
        }

    return {
        "available": True,
        "reason": None,
        "baseline": {
            "job_id": baseline.job_id,
            "display_name": baseline.batch.display_name or f"Batch {baseline.job_id[:8]}",
            "created_at": baseline.created_at,
            "observed_start_time": baseline.batch.observed_start_time,
            "observed_end_time": baseline.batch.observed_end_time,
        },
        "current": {
            "job_id": current.job_id,
            "display_name": current.batch.display_name or f"Batch {current.job_id[:8]}",
            "created_at": current.created_at,
            "observed_start_time": current.batch.observed_start_time,
            "observed_end_time": current.batch.observed_end_time,
        },
        "scope": {
            "products": sorted(products),
            "lots": sorted(lot_ids or []),
            "stations": sorted(station_keys or []),
            "current_attempts": current_view["summary"]["total_runs"],
            "baseline_attempts": baseline_view["summary"]["total_runs"],
            "current_units": current_view["summary"]["unique_units"],
            "baseline_units": baseline_view["summary"]["unique_units"],
            "history_complete": history_complete,
            "time_rule": "Each batch uses its full observed period; active absolute date filters are not replayed.",
        },
        "metrics": comparisons,
        "target": target,
    }


def _unavailable(reason: str) -> dict:
    return {
        "available": False,
        "reason": reason,
        "baseline": None,
        "current": None,
        "scope": None,
        "metrics": {},
        "target": None,
    }


def _unavailable_reason(rejections: set[str], history_complete: bool) -> str:
    if not history_complete:
        return "No comparable batch in searched history"
    if "duplicate" in rejections and rejections <= {"duplicate", "not_complete", "missing_fingerprint"}:
        return "Only duplicate uploads found"
    if "overlap" in rejections:
        return "Comparable batches overlap the selected attempts"
    if "product_mismatch" in rejections:
        return "No earlier batch has the same selected product population"
    if "missing_fingerprint" in rejections:
        return "Earlier batch metadata is unavailable"
    return "No earlier comparable batch"
