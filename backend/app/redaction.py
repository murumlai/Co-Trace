"""Pattern-based redaction. Runs on any text before it can leave the process
(e.g. sent to the LLM). Scrubs serials, IPs, MACs, hostnames and credentials."""
from __future__ import annotations

import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # credential pairs in psexec / command lines: -u user -p pass
    (re.compile(r"(-u\s+)\S+", re.IGNORECASE), r"\1[REDACTED_USER]"),
    (re.compile(r"(-p\s+)\S+", re.IGNORECASE), r"\1[REDACTED_PW]"),
    # key=value credential-like fields
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|apikey|api_key)\s*[=:]\s*\S+"),
     r"\1=[REDACTED]"),
    (re.compile(r"(?i)\b(user|username|userid|uid)\s*[=:]\s*\S+"), r"\1=[REDACTED_USER]"),
    # serial numbers (scan block + common inline forms)
    (re.compile(r"(?i)\b(serialnumber|child_sn|serial)\s*[=:]\s*\S+"), r"\1=[REDACTED_SN]"),
    (re.compile(r"\bRM[A-Z]{1,2}\d{6,}\b"), "[REDACTED_SN]"),
    # hostnames
    (re.compile(r"(?i)\b(host|hostname|testserver)\s*[=:]\s*\S+"), r"\1=[REDACTED_HOST]"),
    (re.compile(r"\\\\[A-Za-z0-9._-]+"), r"\\\\[REDACTED_HOST]"),
    # MAC addresses
    (re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"), "[REDACTED_MAC]"),
    # IPv4 addresses
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
]


def redact(text: str | None) -> str:
    if not text:
        return ""
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_record_fields(**fields: str | None) -> dict[str, str]:
    """Redact a set of named structured fields."""
    return {k: redact(v) for k, v in fields.items()}
