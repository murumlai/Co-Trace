"""Discovery, categorization, and parsing of supporting product documents.

Filename conventions (verified against real sample docs):

* ``M79060-001_Debug Support Document Key Learning.pdf`` -> ``debug_learning``
* ``M13983-700_Sedona USB Test Card.pdf``               -> ``product_overview``
* ``N32828-201_MPDU_20V_PDB1_HLD_Rev05.docx``           -> ``hld``

Product code = the first filename token when it looks like a product code,
otherwise the first product-code match anywhere in the filename.

PDF and DOCX are supported in v1. PPTX/XLSX/legacy Office formats are planned
parser-adapter extension points and intentionally not implemented here.
"""
from __future__ import annotations

import glob
import hashlib
import os
import re

from ..config import settings
from .models import DocumentCategory, ExtractedSection, SourceDocument

# Product codes: 1-2 letters, 4-6 digits, dash, 2-4 digits (e.g. M79060-001).
_PRODUCT_CODE_RE = re.compile(r"[A-Z]{1,2}[0-9]{4,6}-[0-9]{2,4}")

# Ordered by precedence: debug_learning > hld > product_overview.
# Short acronyms (FA, RCA) are matched with word boundaries to avoid over-match.
_DEBUG_LEARNING_KEYWORDS = (
    "debug",
    "support",
    "key learning",
    "learning",
    "failure",
    "troubleshooting",
    "troubleshoot",
    "lesson",
    "known issue",
)
_DEBUG_LEARNING_WORD_KEYWORDS = ("fa", "rca")
_HLD_KEYWORDS = ("hld", "high level design", "high-level design", "architecture")
_PRODUCT_OVERVIEW_KEYWORDS = (
    "card",
    "product",
    "overview",
    "board",
    "module",
    "datasheet",
    "user guide",
    "manual",
    "spec",
)


def extract_product_code(filename: str) -> str | None:
    """Return the product code for ``filename``.

    Prefers the first ``_``/space-delimited token when it is itself a product
    code, then falls back to the first product-code match anywhere.
    """
    stem = os.path.splitext(os.path.basename(filename))[0]
    first_token = re.split(r"[_\s]+", stem, maxsplit=1)[0]
    token_match = _PRODUCT_CODE_RE.fullmatch(first_token)
    if token_match:
        return token_match.group(0)
    anywhere = _PRODUCT_CODE_RE.search(stem)
    return anywhere.group(0) if anywhere else None


def detect_category(filename: str) -> DocumentCategory:
    """Classify a document by filename keywords (case-insensitive)."""
    name = os.path.basename(filename).lower()
    # Tokenize on non-alphanumerics so `_fa_`/`_rca_` acronyms are found
    # (underscores are word chars, so \b alone would miss them).
    tokens = set(re.split(r"[^a-z0-9]+", name))
    if any(kw in name for kw in _DEBUG_LEARNING_KEYWORDS):
        return "debug_learning"
    if any(kw in tokens for kw in _DEBUG_LEARNING_WORD_KEYWORDS):
        return "debug_learning"
    if any(kw in name for kw in _HLD_KEYWORDS):
        return "hld"
    if any(kw in name for kw in _PRODUCT_OVERVIEW_KEYWORDS):
        return "product_overview"
    return "uncategorized"


def make_doc_id(product_code: str | None, filename: str) -> str:
    basis = f"{product_code or ''}|{os.path.basename(filename)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def scan_source_documents(
    source_dirs: list[str] | None = None,
    globs: list[str] | None = None,
) -> list[SourceDocument]:
    """Discover supported product documents across the configured source dirs."""
    dirs = source_dirs if source_dirs is not None else settings.PRODUCT_KNOWLEDGE_SOURCE_DIRS
    patterns = globs if globs is not None else settings.PRODUCT_KNOWLEDGE_SCAN_GLOBS
    seen: dict[str, SourceDocument] = {}
    for root in dirs:
        if not root or not os.path.isdir(root):
            continue
        for pattern in patterns:
            for path in glob.glob(os.path.join(root, "**", pattern), recursive=True):
                if not os.path.isfile(path):
                    continue
                doc = describe_document(path, source_root=root)
                # First discovery wins (stable across overlapping source dirs).
                seen.setdefault(doc.doc_id, doc)
    return sorted(seen.values(), key=lambda d: (d.product_code or "", d.filename))


def describe_document(path: str, source_root: str = "") -> SourceDocument:
    filename = os.path.basename(path)
    product_code = extract_product_code(filename)
    category = detect_category(filename)
    try:
        size_bytes = os.path.getsize(path)
    except OSError:
        size_bytes = 0
    doc = SourceDocument(
        doc_id=make_doc_id(product_code, filename),
        path=os.path.abspath(path),
        filename=filename,
        product_code=product_code,
        category=category,
        size_bytes=size_bytes,
        source_root=source_root,
    )
    if product_code is None:
        doc.warnings.append("No product code found in filename.")
    return doc


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def _extract_pdf_lines(path: str) -> list[str]:
    from pypdf import PdfReader  # noqa: PLC0415 - optional/heavy import

    reader = PdfReader(path)
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines.extend(text.splitlines())
    return lines


def _extract_docx_blocks(path: str) -> list[tuple[bool, str]]:
    """Return (is_heading, text) blocks for a DOCX, in document order."""
    from docx import Document  # noqa: PLC0415 - optional/heavy import

    document = Document(path)
    blocks: list[tuple[bool, str]] = []
    for para in document.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (para.style.name if para.style else "") or ""
        is_heading = style.startswith("Heading") or style == "Title"
        blocks.append((is_heading, text))
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append((False, " | ".join(cells)))
    return blocks


# ---------------------------------------------------------------------------
# Sectioning
# ---------------------------------------------------------------------------

def _is_heading_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if re.match(r"^\d+(\.\d+){0,3}[.\)]?\s+\S", s):
        return True
    letters = [c for c in s if c.isalpha()]
    if letters and len(s) <= 70 and s == s.upper():
        return True
    return False


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split ``text`` into <= max_chars chunks on paragraph/line boundaries."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if size + len(para) > max_chars and buf:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0
        if len(para) > max_chars:
            # Hard-split an oversized paragraph.
            for i in range(0, len(para), max_chars):
                chunks.append(para[i : i + max_chars])
            continue
        buf.append(para)
        size += len(para)
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks or [text[:max_chars]]


def _sections_from_headed_lines(
    lines: list[tuple[bool, str]],
) -> list[tuple[str | None, str]]:
    """Group (is_heading, text) pairs into (heading, body) sections."""
    sections: list[tuple[str | None, str]] = []
    heading: str | None = None
    body: list[str] = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            sections.append((heading, text))

    for is_heading, text in lines:
        if is_heading:
            flush()
            heading = text
            body = []
        else:
            body.append(text)
    flush()
    return sections


def parse_document(doc: SourceDocument) -> tuple[str, list[ExtractedSection]]:
    """Parse ``doc`` into bounded sections.

    Returns ``(content_hash, sections)``. Raises ``ValueError`` for unsupported
    extensions and when no text can be extracted.
    """
    ext = os.path.splitext(doc.filename)[1].lower()
    if ext == ".pdf":
        raw_lines = _extract_pdf_lines(doc.path)
        headed = [(_is_heading_line(ln), ln.strip()) for ln in raw_lines if ln.strip()]
    elif ext == ".docx":
        headed = _extract_docx_blocks(doc.path)
    else:
        raise ValueError(f"Unsupported document type: {ext}")

    full_text = "\n".join(text for _, text in headed).strip()
    if not full_text:
        raise ValueError("No extractable text in document.")
    content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()[:16]

    max_chars = settings.PRODUCT_KNOWLEDGE_SECTION_MAX_CHARS
    min_chars = settings.PRODUCT_KNOWLEDGE_SECTION_MIN_CHARS

    headed_sections = _sections_from_headed_lines(headed)
    has_headings = any(is_heading for is_heading, _ in headed)
    if not has_headings or not headed_sections:
        headed_sections = [(None, chunk) for chunk in _chunk_text(full_text, max_chars)]

    # Enforce max size, then merge undersized trailing sections forward.
    bounded: list[tuple[str | None, str]] = []
    for heading, text in headed_sections:
        for chunk in _chunk_text(text, max_chars):
            bounded.append((heading, chunk))

    # Merge undersized *headingless* chunks forward; never merge away a headed
    # section (that would lose document structure).
    merged: list[tuple[str | None, str]] = []
    for heading, text in bounded:
        if merged and heading is None and len(text) < min_chars:
            prev_heading, prev_text = merged[-1]
            if len(prev_text) + len(text) <= max_chars:
                merged[-1] = (prev_heading, f"{prev_text}\n{text}")
                continue
        merged.append((heading, text))

    sections: list[ExtractedSection] = []
    for order, (heading, text) in enumerate(merged):
        sections.append(
            ExtractedSection(
                section_id=f"{doc.doc_id}-s{order:03d}",
                doc_id=doc.doc_id,
                product_code=doc.product_code,
                category=doc.category,
                heading=heading,
                order=order,
                text=text,
            )
        )
    return content_hash, sections
