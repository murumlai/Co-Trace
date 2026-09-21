"""Manager Aggregator — pure computation over per-unit records. No LLM."""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .models import UnitRecord
from .record_views import latest_records_by_serial, signature_for

_MISSING = "__missing__"


def _unit_id(record: UnitRecord) -> str:
    return record.serial_number or record.unit_id


def station_key(record: UnitRecord) -> str:
    value = f"{record.host or ''}\0{record.station_id or ''}".encode("utf-8")
    return hashlib.sha1(value).hexdigest()[:16]


def _option_value(value: str | None) -> str:
    return value if value else _MISSING


def _parse_time(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO timestamp: {value}") from exc


def _comparable_time(value: str, boundary: datetime) -> datetime | None:
    try:
        timestamp = _parse_time(value)
    except ValueError:
        return None
    if boundary.tzinfo is None:
        return timestamp.replace(tzinfo=None)
    if timestamp.tzinfo is None:
        return None
    return timestamp.astimezone(timezone.utc)


def filter_records(
    records: list[UnitRecord],
    *,
    product_codes: set[str] | None = None,
    lot_ids: set[str] | None = None,
    station_keys: set[str] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> tuple[list[UnitRecord], int]:
    products = product_codes or set()
    lots = lot_ids or set()
    stations = station_keys or set()
    start = _parse_time(start_time) if start_time else None
    end = _parse_time(end_time) if end_time else None
    if start and end:
        if (start.tzinfo is None) != (end.tzinfo is None):
            raise ValueError("Start and end timestamps must use the same timezone style")
        comparable_end = end if end.tzinfo is None else end.astimezone(timezone.utc)
        comparable_start = start if start.tzinfo is None else start.astimezone(timezone.utc)
        if comparable_start > comparable_end:
            raise ValueError("Start timestamp must not be after end timestamp")

    selected: list[UnitRecord] = []
    missing_timestamp_excluded = 0
    for record in records:
        if products and _option_value(record.product_code) not in products:
            continue
        if lots and _option_value(record.lot_id) not in lots:
            continue
        if stations and station_key(record) not in stations:
            continue
        if start or end:
            source_time = record.start_time or record.end_time
            if not source_time:
                missing_timestamp_excluded += 1
                continue
            boundary = start or end
            assert boundary is not None
            comparable = _comparable_time(source_time, boundary)
            if comparable is None:
                missing_timestamp_excluded += 1
                continue
            comparable_start = start if start is None or start.tzinfo is None else start.astimezone(timezone.utc)
            comparable_end = end if end is None or end.tzinfo is None else end.astimezone(timezone.utc)
            if comparable_start and comparable < comparable_start:
                continue
            if comparable_end and comparable > comparable_end:
                continue
        selected.append(record)
    return selected, missing_timestamp_excluded


def _first_attempts(records: list[UnitRecord]) -> list[UnitRecord]:
    """First test attempt per serial number (earliest start_time)."""
    by_serial: dict[str, UnitRecord] = {}
    for r in records:
        key = r.serial_number or r.unit_id
        cur = by_serial.get(key)
        if cur is None or (r.start_time or "") < (cur.start_time or ""):
            by_serial[key] = r
    return list(by_serial.values())


def compute_summary(records: list[UnitRecord]) -> dict:
    total = len(records)
    firsts = _first_attempts(records)

    fpy_pass = sum(1 for r in firsts if r.result == "PASS")
    fpy_total = sum(1 for r in firsts if r.result in ("PASS", "FAIL"))
    fpy = (fpy_pass / fpy_total * 100.0) if fpy_total else 0.0

    # Passed/Failed reflect one final result per unit (latest attempt), not runs.
    latest = latest_records_by_serial(records)
    passed = sum(1 for r in latest if r.result == "PASS")
    failed = sum(1 for r in latest if r.result == "FAIL")
    unknown = sum(1 for r in latest if r.result == "UNKNOWN")
    latest_total = passed + failed
    latest_yield = (passed / latest_total * 100.0) if latest_total else 0.0
    first_by_unit = {_unit_id(record): record for record in firsts}
    recovered_after_retry = sum(
        1
        for record in latest
        if record.result == "PASS" and first_by_unit[_unit_id(record)].result == "FAIL"
    )
    retests = total - len(firsts)
    additional_attempt_share = (retests / total * 100.0) if total else 0.0

    return {
        "total_runs": total,
        "unique_units": len(firsts),
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
        "fpy": round(fpy, 2),
        "fpy_pass": fpy_pass,
        "fpy_total": fpy_total,
        "retests": retests,
        "latest_yield": round(latest_yield, 2),
        "latest_yield_pass": passed,
        "latest_yield_total": latest_total,
        "recovered_after_retry": recovered_after_retry,
        "additional_attempt_share": round(additional_attempt_share, 2),
    }


def compute_trend(records: list[UnitRecord]) -> list[dict]:
    """Yield trend grouped by calendar day derived from start_time."""
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    for r in records:
        if not r.start_time:
            continue
        day = r.start_time[:10]
        if r.result == "PASS":
            buckets[day]["pass"] += 1
        elif r.result == "FAIL":
            buckets[day]["fail"] += 1
    out = []
    for day in sorted(buckets):
        p, f = buckets[day]["pass"], buckets[day]["fail"]
        tot = p + f
        matching = [
            record for record in records
            if (record.start_time or "")[:10] == day and record.result in {"PASS", "FAIL"}
        ]
        out.append({
            "date": day,
            "pass": p,
            "fail": f,
            "yield": round(p / tot * 100.0, 2) if tot else 0.0,
            "attempt_ids": [record.unit_id for record in matching],
            "unit_ids": sorted({_unit_id(record) for record in matching}),
        })
    return out


def compute_pareto(records: list[UnitRecord], top: int = 10) -> list[dict]:
    counter: Counter[str] = Counter()
    labels: dict[str, str] = {}
    grouped: dict[str, list[UnitRecord]] = defaultdict(list)
    for r in records:
        if r.result == "FAIL":
            signature = signature_for(r)
            label = r.error_code or "UNKNOWN"
            if r.error_message:
                label = f"{r.error_code or 'FAIL'}: {r.error_message[:60]}"
            counter[signature] += 1
            grouped[signature].append(r)
            labels.setdefault(signature, label)
    total = sum(counter.values())
    out = []
    cum = 0
    for signature, count in counter.most_common(top):
        cum += count
        out.append({
            "signature": signature,
            "reason": labels[signature],
            "count": count,
            "pct": round(count / total * 100.0, 2) if total else 0.0,
            "cum_pct": round(cum / total * 100.0, 2) if total else 0.0,
            "attempt_ids": [record.unit_id for record in grouped[signature]],
            "unit_ids": sorted({_unit_id(record) for record in grouped[signature]}),
        })
    return out


def compute_failure_clusters(records: list[UnitRecord]) -> list[dict]:
    buckets: dict[str, list[UnitRecord]] = defaultdict(list)
    for record in records:
        if record.result == "FAIL":
            buckets[signature_for(record)].append(record)

    clusters: list[dict] = []
    for signature, failures in buckets.items():
        representative = failures[0]
        times = [
            timestamp
            for record in failures
            for timestamp in (record.start_time, record.end_time)
            if timestamp
        ]
        clusters.append({
            "signature": signature,
            "count": len(failures),
            "affected_serials": sorted({
                record.serial_number or record.unit_id for record in failures
            }),
            "stations": sorted({record.station_id for record in failures if record.station_id}),
            "lots": sorted({record.lot_id for record in failures if record.lot_id}),
            "product_codes": sorted({
                record.product_code for record in failures if record.product_code
            }),
            "first_seen": min(times) if times else None,
            "last_seen": max(times) if times else None,
            "error_code": representative.error_code,
            "error_message": representative.error_message,
            "failing_step": representative.failing_step,
            "analysis_context_source": representative.analysis_context_source,
            "knowledge_status_summary": dict(Counter(
                record.knowledge_match_status or "unknown" for record in failures
            )),
            "analysis_source_summary": dict(Counter(
                record.analysis_source or "unanalyzed" for record in failures
            )),
        })

    clusters.sort(key=lambda cluster: (cluster["count"], cluster["last_seen"] or ""), reverse=True)
    return clusters


def compute_station_breakdown(records: list[UnitRecord]) -> list[dict]:
    buckets: dict[tuple[str | None, str | None], dict[str, int]] = defaultdict(
        lambda: {"pass": 0, "fail": 0}
    )
    for r in records:
        if r.result not in {"PASS", "FAIL"}:
            continue
        key = (r.station_id, r.host)
        if r.result == "PASS":
            buckets[key]["pass"] += 1
        elif r.result == "FAIL":
            buckets[key]["fail"] += 1
    out = []
    for station_id, host in sorted(buckets, key=lambda key: (key[1] or "", key[0] or "")):
        p, f = buckets[(station_id, host)]["pass"], buckets[(station_id, host)]["fail"]
        tot = p + f
        matching = [
            record for record in records
            if (record.station_id, record.host) == (station_id, host)
            and record.result in {"PASS", "FAIL"}
        ]
        out.append({
            "station": f"{host or 'unknown'} / ST{station_id or '?'}",
            "station_id": station_id,
            "host": host,
            "pass": p,
            "fail": f,
            "total": tot,
            "yield": round(p / tot * 100.0, 2) if tot else 0.0,
            "key": station_key(matching[0]),
            "attempt_ids": [record.unit_id for record in matching],
            "unit_ids": sorted({_unit_id(record) for record in matching}),
        })
    return out


def compute_lot_comparison(records: list[UnitRecord]) -> list[dict]:
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    for r in records:
        if r.result not in {"PASS", "FAIL"}:
            continue
        key = r.lot_id or "unknown"
        if r.result == "PASS":
            buckets[key]["pass"] += 1
        elif r.result == "FAIL":
            buckets[key]["fail"] += 1
    out = []
    for key in sorted(buckets):
        p, f = buckets[key]["pass"], buckets[key]["fail"]
        tot = p + f
        matching = [
            record for record in records
            if (record.lot_id or "unknown") == key and record.result in {"PASS", "FAIL"}
        ]
        out.append({
            "lot": key,
            "pass": p,
            "fail": f,
            "total": tot,
            "yield": round(p / tot * 100.0, 2) if tot else 0.0,
            "attempt_ids": [record.unit_id for record in matching],
            "unit_ids": sorted({_unit_id(record) for record in matching}),
        })
    return out


def build_manager_view(
    records: list[UnitRecord],
    *,
    product_codes: set[str] | None = None,
    lot_ids: set[str] | None = None,
    station_keys: set[str] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict:
    selected, missing_timestamp_excluded = filter_records(
        records,
        product_codes=product_codes,
        lot_ids=lot_ids,
        station_keys=station_keys,
        start_time=start_time,
        end_time=end_time,
    )
    product_options = sorted({_option_value(record.product_code) for record in records})
    lot_options = sorted({_option_value(record.lot_id) for record in records})
    station_records: dict[str, UnitRecord] = {}
    for record in records:
        station_records.setdefault(station_key(record), record)
    return {
        "summary": compute_summary(selected),
        "trend": compute_trend(selected),
        "pareto": compute_pareto(selected),
        "stations": compute_station_breakdown(selected),
        "lots": compute_lot_comparison(selected),
        "scope": {
            "selected_attempt_count": len(selected),
            "selected_unit_count": len({_unit_id(record) for record in selected}),
            "missing_timestamp_excluded": missing_timestamp_excluded,
            "attempt_ids": [record.unit_id for record in selected],
            "unit_ids": sorted({_unit_id(record) for record in selected}),
            "filters": {
                "products": sorted(product_codes or []),
                "lots": sorted(lot_ids or []),
                "stations": sorted(station_keys or []),
                "start_time": start_time,
                "end_time": end_time,
            },
            "options": {
                "products": [{"value": value, "label": "Unknown" if value == _MISSING else value} for value in product_options],
                "lots": [{"value": value, "label": "Unknown" if value == _MISSING else value} for value in lot_options],
                "stations": [
                    {
                        "value": key,
                        "station_id": record.station_id,
                        "host": record.host,
                        "label": f"{record.host or 'unknown'} / ST{record.station_id or '?'}",
                    }
                    for key, record in sorted(station_records.items())
                ],
            },
            "time_semantics": "Attempt start time, falling back to end time; naive filters compare source wall time.",
        },
    }
