"""Product-aware diagnosis: knowledge-pack ingestion and retrieval.

This subpackage preprocesses supporting product/card documents into a curated,
repo-root knowledge pack and retrieves a few relevant summaries at diagnosis
time. Runtime diagnosis never loads or sends whole documents — only curated
summaries matched to a failed record by ``PRODUCTCODE``.
"""
from __future__ import annotations
