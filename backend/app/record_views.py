"""Derived record views used by API/artifact surfaces."""
from __future__ import annotations

from collections import defaultdict

from .models import Classification, SerialUnitGroup, UnitRecord


def latest_records_by_serial(records: list[UnitRecord]) -> list[UnitRecord]:
    """Return one latest test run per serial number.

    Engineer-facing views should show the final/latest observed result for a
    unit, not every retest. Records without a serial number remain one row per
    run because there is no stable unit identity to group by.
    """
    attempts: dict[str, list[UnitRecord]] = defaultdict(list)
    for record in records:
        attempts[_unit_key(record)].append(record)

    latest = [max(group, key=_latest_sort_key) for group in attempts.values()]
    latest.sort(key=_latest_sort_key, reverse=True)
    return latest


def classify_attempts(ordered_attempts: list[UnitRecord]) -> Classification:
    """Classify a single serial's chronologically-ordered attempts.

    - ``first_pass``: latest attempt PASSed and no attempt ever failed.
    - ``retry_pass``: latest attempt PASSed but at least one earlier attempt failed.
    - ``fail``: latest attempt is FAIL (unit is still failing).
    - ``unknown``: latest attempt result is UNKNOWN.
    """
    final = ordered_attempts[-1]
    has_failure = any(a.result == "FAIL" for a in ordered_attempts)
    if final.result == "PASS":
        return "retry_pass" if has_failure else "first_pass"
    if final.result == "FAIL":
        return "fail"
    return "unknown"


def group_units_by_serial(records: list[UnitRecord]) -> list[SerialUnitGroup]:
    """Group all test runs by serial number into one classified unit each.

    Each group carries the latest attempt (``final``), every failing attempt
    (``failures``, chronological, retaining LLM analysis), and a
    classification so the Engineer view can distinguish first-test-pass,
    retry-pass, and consistently-failing units.
    """
    attempts: dict[str, list[UnitRecord]] = defaultdict(list)
    for record in records:
        attempts[_unit_key(record)].append(record)

    groups: list[SerialUnitGroup] = []
    for group in attempts.values():
        ordered = sorted(group, key=_latest_sort_key)
        final = ordered[-1]
        failures = [a for a in ordered if a.result == "FAIL"]
        groups.append(
            SerialUnitGroup(
                serial_number=final.serial_number,
                unit_id=final.unit_id,
                classification=classify_attempts(ordered),
                result=final.result,
                attempt_count=len(ordered),
                failure_count=len(failures),
                final=final,
                failures=failures,
            )
        )

    # Show failing units first, then retry-pass, then first-pass; newest within.
    # Two-pass stable sort: order by recency (newest first), then by class.
    groups.sort(key=lambda g: _latest_sort_key(g.final), reverse=True)
    order = {"fail": 0, "unknown": 1, "retry_pass": 2, "first_pass": 3}
    groups.sort(key=lambda g: order.get(g.classification, 9))
    return groups


def _unit_key(record: UnitRecord) -> str:
    return f"serial:{record.serial_number}" if record.serial_number else f"run:{record.unit_id}"


def _latest_sort_key(record: UnitRecord) -> tuple[str, str, str, str]:
    return (
        record.start_time or "",
        record.end_time or "",
        record.run_folder or "",
        record.unit_id,
    )
