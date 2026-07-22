"""Measure preprocessed <product_code>.json size across serialization modes.

Runs the FTRunner-primary preprocessor against one or more log-batch folders
and reports, per product code:

* raw byte size in legacy (pretty) vs compact (minified) vs gzip modes
* unit / pass / fail counts
* per-field byte contribution for the heavy fields (steps, debug_excerpt,
  ftrunner_snippet, warnings, repeated metadata)

This drives the size-reduction prioritization in ``llm_plan.md`` and the
before/after verification for each optimization phase. It does not write any
artifacts — it only measures.

Usage (from the repo root, with the backend venv active)::

    python backend/scripts/measure_preprocessed.py Log_Files_Folder/All_LogFiles_M95113-001
    python backend/scripts/measure_preprocessed.py <folder1> <folder2> ...
"""
from __future__ import annotations

import gzip
import json
import os
import sys

# Make ``app`` importable when run as a standalone script.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.preprocessor import build_product_json, get_preprocessor  # noqa: E402


def _fmt(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{n:,} B"
        n /= 1024
    return f"{n} B"


def _field_bytes(units: list[dict], field: str) -> int:
    total = 0
    for u in units:
        if field in u:
            total += len(json.dumps({field: u[field]}, separators=(",", ":")).encode("utf-8"))
    return total


def measure_folder(folder: str) -> None:
    recs = get_preprocessor().process_folder(folder)
    by_product: dict[str, list] = {}
    for r in recs:
        by_product.setdefault(r.product_code or "UNKNOWN", []).append(r)

    print(f"\n=== {folder} ===")
    print(f"records: {len(recs)}  products: {len(by_product)}")

    for product_code, group in sorted(by_product.items()):
        doc = build_product_json(product_code, group)
        units = doc["units"]
        pretty = json.dumps(doc, indent=2).encode("utf-8")
        compact = json.dumps(doc, separators=(",", ":")).encode("utf-8")
        gz = gzip.compress(compact)

        summary = doc["summary"]
        print(f"\n  product_code={product_code}")
        print(
            f"    units={summary['total']} pass={summary['pass']} "
            f"fail={summary['fail']} unknown={summary['unknown']} fpy={summary['fpy']}"
        )
        print(f"    pretty : {_fmt(len(pretty))}")
        print(f"    compact: {_fmt(len(compact))}  ({len(compact) / max(len(pretty), 1):.0%} of pretty)")
        print(f"    gzip   : {_fmt(len(gz))}  ({len(gz) / max(len(compact), 1):.0%} of compact)")

        heavy = ("steps", "debug_excerpt", "ftrunner_snippet", "error_message")
        for field in heavy:
            fb = _field_bytes(units, field)
            if fb:
                print(f"      {field:<16}: {_fmt(fb)}  ({fb / max(len(compact), 1):.0%} of compact)")


def main(argv: list[str]) -> int:
    folders = argv[1:]
    if not folders:
        print(__doc__)
        return 2
    for folder in folders:
        if not os.path.isdir(folder):
            print(f"skip (not a directory): {folder}")
            continue
        measure_folder(folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
