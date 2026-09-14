"""Manager Aggregator — pure computation over per-unit records. No LLM."""
from __future__ import annotations

from collections import Counter, defaultdict

from .models import UnitRecord
from .record_views import latest_records_by_serial, signature_for


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

    return {
        "total_runs": total,
        "unique_units": len(firsts),
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
        "fpy": round(fpy, 2),
        "fpy_pass": fpy_pass,
        "fpy_total": fpy_total,
        "retests": total - len(firsts),
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
        out.append({
            "date": day,
            "pass": p,
            "fail": f,
            "yield": round(p / tot * 100.0, 2) if tot else 0.0,
        })
    return out


def compute_pareto(records: list[UnitRecord], top: int = 10) -> list[dict]:
    counter: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for r in records:
        if r.result == "FAIL":
            signature = signature_for(r)
            label = r.error_code or "UNKNOWN"
            if r.error_message:
                label = f"{r.error_code or 'FAIL'}: {r.error_message[:60]}"
            counter[signature] += 1
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
        key = (r.station_id, r.host)
        if r.result == "PASS":
            buckets[key]["pass"] += 1
        elif r.result == "FAIL":
            buckets[key]["fail"] += 1
    out = []
    for station_id, host in sorted(buckets, key=lambda key: (key[1] or "", key[0] or "")):
        p, f = buckets[(station_id, host)]["pass"], buckets[(station_id, host)]["fail"]
        tot = p + f
        out.append({
            "station": f"{host or 'unknown'} / ST{station_id or '?'}",
            "station_id": station_id,
            "host": host,
            "pass": p,
            "fail": f,
            "total": tot,
            "yield": round(p / tot * 100.0, 2) if tot else 0.0,
        })
    return out


def compute_lot_comparison(records: list[UnitRecord]) -> list[dict]:
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    for r in records:
        key = r.lot_id or "unknown"
        if r.result == "PASS":
            buckets[key]["pass"] += 1
        elif r.result == "FAIL":
            buckets[key]["fail"] += 1
    out = []
    for key in sorted(buckets):
        p, f = buckets[key]["pass"], buckets[key]["fail"]
        tot = p + f
        out.append({
            "lot": key,
            "pass": p,
            "fail": f,
            "total": tot,
            "yield": round(p / tot * 100.0, 2) if tot else 0.0,
        })
    return out


def build_manager_view(records: list[UnitRecord]) -> dict:
    return {
        "summary": compute_summary(records),
        "trend": compute_trend(records),
        "pareto": compute_pareto(records),
        "stations": compute_station_breakdown(records),
        "lots": compute_lot_comparison(records),
    }
