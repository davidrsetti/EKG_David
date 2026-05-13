"""
audit/pii_scanner.py — Detects and optionally redacts PII in query result sets.
Applied to every result before returning to the caller.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# ── Patterns ───────────────────────────────────────────────────────────
_PATTERNS: dict[str, re.Pattern] = {
    "email":         re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b"),
    "phone_intl":    re.compile(r"\+?[0-9][\d\s\-().]{7,14}[0-9]"),
    "uk_nino":       re.compile(r"\b[A-Z]{2}\d{6}[A-Z]\b"),
    "us_ssn":        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card":   re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "ip_address":    re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    "passport":      re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"),
}

_REDACT_PLACEHOLDER = "[REDACTED]"


@dataclass
class ScanResult:
    pii_found:   bool
    detections:  list[dict]   # [{"field": col, "type": pii_type, "count": n}]
    redacted_rows: list[dict] # rows with PII replaced


def scan_and_redact(
    rows: list[dict],
    redact: bool = True,
) -> ScanResult:
    """
    Scan result rows for PII patterns. Optionally redact detected values.
    Returns a ScanResult with detection summary and (optionally redacted) rows.
    """
    if not rows:
        return ScanResult(pii_found=False, detections=[], redacted_rows=[])

    detections: dict[str, dict] = {}  # "field:type" → {field, type, count}
    redacted_rows = []

    for row in rows:
        new_row = {}
        for col, val in row.items():
            val_str = str(val) if val is not None else ""
            matched_types = []
            for pii_type, pattern in _PATTERNS.items():
                if pattern.search(val_str):
                    key = f"{col}:{pii_type}"
                    if key not in detections:
                        detections[key] = {"field": col, "type": pii_type, "count": 0}
                    detections[key]["count"] += 1
                    matched_types.append((pii_type, pattern))

            if redact and matched_types:
                for pii_type, pattern in matched_types:
                    val_str = pattern.sub(_REDACT_PLACEHOLDER, val_str)
                new_row[col] = val_str
            else:
                new_row[col] = val
        redacted_rows.append(new_row)

    return ScanResult(
        pii_found     = bool(detections),
        detections    = list(detections.values()),
        redacted_rows = redacted_rows,
    )
