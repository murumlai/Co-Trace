"""Derived record views used by API/artifact surfaces."""
from __future__ import annotations

from collections import defaultdict

from .models import UnitRecord


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


def _unit_key(record: UnitRecord) -> str:
    return f"serial:{record.serial_number}" if record.serial_number else f"run:{record.unit_id}"


def _latest_sort_key(record: UnitRecord) -> tuple[str, str, str, str]:
    return (
        record.start_time or "",
        record.end_time or "",
        record.run_folder or "",
        record.unit_id,
    )
