"""Shared chronological ordering for manufacturing attempts."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, Protocol, TypeVar


class TimestampedRecord(Protocol):
    start_time: str | None
    end_time: str | None
    run_folder: str
    unit_id: str


RecordT = TypeVar("RecordT", bound=TimestampedRecord)


@dataclass(frozen=True)
class ChronologicalOrder(Generic[RecordT]):
    records: list[RecordT]
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class ObservedPeriod:
    start_time: str | None
    end_time: str | None
    timezone_style: str
    unavailable_reason: str | None = None


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def order_chronologically(records: Iterable[RecordT]) -> ChronologicalOrder[RecordT]:
    values = list(records)
    if len(values) <= 1:
        return ChronologicalOrder(values)

    resolved: list[tuple[RecordT, datetime]] = []
    for record in values:
        source = record.start_time if record.start_time else record.end_time
        timestamp = parse_timestamp(source)
        if timestamp is None:
            reason = "Invalid timestamp prevents chronological ordering" if source else "Missing timestamp prevents chronological ordering"
            return ChronologicalOrder(_stable_order(values), reason)
        resolved.append((record, timestamp))

    awareness = {timestamp.tzinfo is not None for _, timestamp in resolved}
    if len(awareness) > 1:
        return ChronologicalOrder(
            _stable_order(values),
            "Mixed timezone styles prevent chronological ordering",
        )

    aware = awareness == {True}
    comparable = [
        (
            record,
            timestamp.astimezone(timezone.utc) if aware else timestamp,
        )
        for record, timestamp in resolved
    ]
    comparable.sort(key=lambda item: (item[1], _stable_key(item[0])))
    if len({timestamp for _, timestamp in comparable}) != len(comparable):
        return ChronologicalOrder(
            [record for record, _ in comparable],
            "Equal timestamps prevent chronological ordering",
        )
    return ChronologicalOrder([record for record, _ in comparable])


def observed_period(records: Iterable[RecordT]) -> ObservedPeriod:
    values = list(records)
    if not values:
        return ObservedPeriod(None, None, "unavailable")

    starts: list[tuple[RecordT, str, datetime]] = []
    ends: list[tuple[RecordT, str, datetime]] = []
    for record in values:
        start_source = record.start_time or record.end_time
        end_source = record.end_time or record.start_time
        if not start_source or not end_source:
            return ObservedPeriod(
                None,
                None,
                "unavailable",
                "Missing timestamp prevents determining the observed period",
            )
        start = parse_timestamp(start_source)
        end = parse_timestamp(end_source)
        if start is None or end is None:
            return ObservedPeriod(
                None,
                None,
                "unavailable",
                "Invalid timestamp prevents determining the observed period",
            )
        starts.append((record, start_source, start))
        ends.append((record, end_source, end))

    awareness = {timestamp.tzinfo is not None for _, _, timestamp in [*starts, *ends]}
    if len(awareness) > 1:
        return ObservedPeriod(
            None,
            None,
            "mixed",
            "Mixed timezone styles prevent determining the observed period",
        )

    aware = awareness == {True}
    normalize = lambda value: value.astimezone(timezone.utc) if aware else value
    first = min(starts, key=lambda item: (normalize(item[2]), _stable_key(item[0])))
    last = max(ends, key=lambda item: (normalize(item[2]), _stable_key(item[0])))
    return ObservedPeriod(
        first[1],
        last[1],
        "offset" if aware else "unspecified",
    )


def _stable_order(records: Iterable[RecordT]) -> list[RecordT]:
    return sorted(records, key=_stable_key)


def _stable_key(record: TimestampedRecord) -> tuple[str, str, str, str]:
    return (
        record.start_time or "",
        record.end_time or "",
        record.run_folder or "",
        record.unit_id,
    )