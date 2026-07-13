"""Manager Aggregator — pure computation over per-unit records. No LLM."""
from __future__ import annotations

from collections import Counter, defaultdict

from .models import UnitRecord


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

    passed = sum(1 for r in records if r.result == "PASS")
    failed = sum(1 for r in records if r.result == "FAIL")
    unknown = sum(1 for r in records if r.result == "UNKNOWN")

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
    for r in records:
        if r.result == "FAIL":
            label = r.error_code or "UNKNOWN"
            if r.error_message:
                label = f"{r.error_code or 'FAIL'}: {r.error_message[:60]}"
            counter[label] += 1
    total = sum(counter.values())
    out = []
    cum = 0
    for label, count in counter.most_common(top):
        cum += count
        out.append({
            "reason": label,
            "count": count,
            "pct": round(count / total * 100.0, 2) if total else 0.0,
            "cum_pct": round(cum / total * 100.0, 2) if total else 0.0,
        })
    return out


def compute_station_breakdown(records: list[UnitRecord]) -> list[dict]:
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    for r in records:
        key = f"{r.host or 'unknown'} / ST{r.station_id or '?'}"
        if r.result == "PASS":
            buckets[key]["pass"] += 1
        elif r.result == "FAIL":
            buckets[key]["fail"] += 1
    out = []
    for key in sorted(buckets):
        p, f = buckets[key]["pass"], buckets[key]["fail"]
        tot = p + f
        out.append({
            "station": key,
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
