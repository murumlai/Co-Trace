"""Derived record views used by API/artifact surfaces."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable

from .models import Classification, SerialUnitGroup, UnitRecord
from .redaction import redact

_WS = re.compile(r"\s+")
_NUM = re.compile(r"\d+")


def _normalize_msg(message: str | None) -> str:
    if not message:
        return ""
    text = _NUM.sub("#", message.lower())
    return _WS.sub(" ", text).strip()


def signature_for(record: UnitRecord) -> str:
    basis = f"{record.error_code or 'FAIL'}|{_normalize_msg(record.error_message)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


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


def build_debug_packet(
    records: list[UnitRecord],
    *,
    unit_id: str | None = None,
    signature: str | None = None,
) -> str:
    if bool(unit_id) == bool(signature):
        raise ValueError("Specify exactly one unit_id or signature")

    if unit_id:
        target = next((record for record in records if record.unit_id == unit_id), None)
        if target is None:
            raise LookupError("Unit not found")
        attempts = [
            record
            for record in records
            if (
                target.serial_number
                and record.serial_number == target.serial_number
                or not target.serial_number
                and record.unit_id == target.unit_id
            )
        ]
        title = target.serial_number or target.unit_id
        lines = [f"# Debug packet: {_field(title)}", "", "## Unit", ""]
        lines.extend(_identity_lines(target))
    else:
        attempts = [
            record
            for record in records
            if record.result == "FAIL" and signature_for(record) == signature
        ]
        if not attempts:
            raise LookupError("Failure cluster not found")
        representative = attempts[0]
        title = representative.error_code or signature or "failure"
        lines = [f"# Failure cluster packet: {_field(title)}", "", "## Cluster", ""]
        lines.extend([
            f"- Signature: {_field(signature)}",
            f"- Failed attempts: {len(attempts)}",
            f"- Affected units: {len({record.serial_number or record.unit_id for record in attempts})}",
            f"- Stations: {_field_list(record.station_id for record in attempts)}",
            f"- Lots: {_field_list(record.lot_id for record in attempts)}",
            f"- Products: {_field_list(record.product_code for record in attempts)}",
        ])

    ordered = sorted(attempts, key=_latest_sort_key)
    lines.extend(["", "## Attempt history", ""])
    for index, attempt in enumerate(ordered[:10], start=1):
        lines.extend(_attempt_lines(attempt, index))
    if len(ordered) > 10:
        lines.extend(["", f"_Omitted {len(ordered) - 10} additional attempts._"])
    lines.extend([
        "",
        "## Redaction",
        "",
        "Evidence excerpts were redacted and capped at 2,000 characters per attempt.",
        "",
    ])
    return "\n".join(lines)


def _identity_lines(record: UnitRecord) -> list[str]:
    return [
        f"- Serial: {_field(record.serial_number)}",
        f"- Unit run: {_field(record.unit_id)}",
        f"- Product: {_field(record.product_code)}",
        f"- Lot: {_field(record.lot_id)}",
        f"- Station: {_field(record.station_id)}",
        f"- Host: {_field(record.host)}",
    ]


def _attempt_lines(record: UnitRecord, index: int) -> list[str]:
    lines = [
        f"### Attempt {index}: {_field(record.result)}",
        "",
        f"- Unit run: {_field(record.unit_id)}",
        f"- Started: {_field(record.start_time)}",
        f"- Ended: {_field(record.end_time)}",
        f"- Duration: {record.duration_s:.1f}s",
        f"- Station / host: {_field(record.station_id)} / {_field(record.host)}",
        f"- Error: {_field(record.error_code)} - {_field(record.error_message)}",
        f"- Failing step: {_field(record.failing_step)}",
        f"- Analysis source: {_field(record.analysis_source)}",
        f"- Context source: {_field(record.analysis_context_source)}",
    ]
    optional_fields = [
        ("Root cause", record.root_cause),
        ("Suggested solution", record.suggested_solution),
        ("Category", record.root_cause_category),
        ("Confidence", record.confidence),
        ("Evidence summary", record.evidence_summary),
        ("Next debug action", record.next_debug_action),
        ("Likely owner", record.likely_owner),
        ("Safety / escape risk", record.safety_or_escape_risk),
        ("Needs more evidence", record.needs_more_evidence),
        ("Knowledge sections", ", ".join(record.knowledge_section_ids)),
        ("Knowledge categories", ", ".join(record.knowledge_categories)),
        ("Acronyms used", ", ".join(record.acronyms_used)),
        ("Unknown acronyms", ", ".join(record.unknown_acronyms)),
    ]
    lines.extend(f"- {label}: {_field(value)}" for label, value in optional_fields if value not in (None, "", []))
    excerpt = record.redacted_snippet or record.debug_excerpt or record.ftrunner_snippet
    if excerpt:
        safe_excerpt = redact(excerpt)[:2000]
        lines.extend(["", "Evidence excerpt:", "", *[f"    {line}" for line in safe_excerpt.splitlines()]])
    lines.append("")
    return lines


def _field(value: object) -> str:
    text = " ".join(str(value if value not in (None, "") else "Unavailable").split())
    return text[:500]


def _field_list(values: Iterable[object]) -> str:
    return ", ".join(sorted({_field(value) for value in values if value})) or "Unavailable"


def _unit_key(record: UnitRecord) -> str:
    return f"serial:{record.serial_number}" if record.serial_number else f"run:{record.unit_id}"


def _latest_sort_key(record: UnitRecord) -> tuple[str, str, str, str]:
    return (
        record.start_time or "",
        record.end_time or "",
        record.run_folder or "",
        record.unit_id,
    )
