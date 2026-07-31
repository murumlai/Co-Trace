"""Rebuild the repo-root product-knowledge pack from supporting documents.

Scans the configured source folders (``Log_Files_Folder`` and ``product_docs``
by default), extracts and summarizes PDF/DOCX product docs with GPT 5.4-mini,
and writes the three generated artifacts:

* ``product_knowledge.json``
* ``product_knowledge_index.json``
* ``product_knowledge_sections.jsonl``

Summarization requires an LLM backend (``copilot auth login``); the build fails
fast if none is available.

Usage (from the repo root, with the backend venv active)::

    python backend/scripts/build_product_knowledge.py
    python backend/scripts/build_product_knowledge.py --source-dir product_docs
    python backend/scripts/build_product_knowledge.py --source-dir A --source-dir B
"""
from __future__ import annotations

import argparse
import os
import sys

# Make ``app`` importable when run as a standalone script.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.knowledge import parsing  # noqa: E402
from app.knowledge.service import KnowledgeIngestionService  # noqa: E402
from app.knowledge.summarizer import ProductKnowledgeError  # noqa: E402


def _progress(done: int, total: int, message: str) -> None:
    print(f"[{done}/{total}] {message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the product-knowledge pack.")
    parser.add_argument(
        "--source-dir",
        action="append",
        default=None,
        help="Override source folder(s) to scan. Repeatable.",
    )
    args = parser.parse_args(argv)

    docs = parsing.scan_source_documents(source_dirs=args.source_dir)
    if not docs:
        print("No supported product documents found. Nothing to do.")
        return 0

    print(f"Discovered {len(docs)} document(s):")
    for doc in docs:
        code = doc.product_code or "UNKNOWN"
        print(f"  - {doc.filename}  [{code} / {doc.category}]")

    service = KnowledgeIngestionService()
    try:
        manifest = service.build(docs, progress=_progress)
    except ProductKnowledgeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2

    print("\nKnowledge pack written.")
    print(f"  products:   {len(manifest.products)}")
    print(f"  documents:  {len(manifest.documents)}")
    print(f"  categories: {manifest.category_counts}")
    print(f"  global hash: {manifest.global_hash}")
    if manifest.warnings:
        print(f"  warnings ({len(manifest.warnings)}):")
        for warning in manifest.warnings[:20]:
            print(f"    ! {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
