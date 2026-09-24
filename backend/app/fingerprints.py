"""Stable fingerprints for selected manufacturing attempts."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def batch_fingerprint(records: Iterable[Any]) -> str | None:
    values = list(records)
    if not values:
        return None
    normalized = sorted((
        record.serial_number or record.unit_id,
        record.product_code or "",
        record.lot_id or "",
        record.station_id or "",
        record.host or "",
        record.start_time or "",
        record.end_time or "",
        record.result,
        record.error_code or "",
        record.error_message or "",
    ) for record in values)
    payload = json.dumps(normalized, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()