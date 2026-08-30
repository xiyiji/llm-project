"""Triage stage: deduplication, noise filtering, prompt-injection screening.

Driver notes are untrusted free text that later reaches an LLM prompt, so they
are screened here and never treated as instructions.
"""

from datetime import datetime
from typing import List, Optional

from app.models import LogRow, TriageResult
from app.rules import is_noise

INJECTION_PATTERNS = (
    "ignore previous",
    "ignore all previous",
    "ignore your instructions",
    "disregard the above",
    "disregard previous",
    "forget your instructions",
    "new instructions",
    "system prompt",
    "you are now",
    "act as",
    "override your",
    "reveal your prompt",
)


def scan_for_injection(text: str) -> bool:
    lowered = text.lower()
    return any(p in lowered for p in INJECTION_PATTERNS)


def _close_in_time(a: str, b: str, minutes: int = 10) -> bool:
    try:
        ta, tb = datetime.fromisoformat(a), datetime.fromisoformat(b)
    except ValueError:
        return False
    return abs((ta - tb).total_seconds()) <= minutes * 60


def is_content_duplicate(row: LogRow, earlier: List[LogRow]) -> bool:
    """Duplicate scan: same shipment, status, description and attempt, minutes apart."""
    for prev in earlier:
        if (
            prev.shipment_id == row.shipment_id
            and prev.status_code == row.status_code
            and prev.status_description == row.status_description
            and prev.attempt_number == row.attempt_number
            and _close_in_time(prev.timestamp, row.timestamp)
        ):
            return True
    return False


def triage_row(row: LogRow, earlier: Optional[List[LogRow]] = None) -> TriageResult:
    result = TriageResult()
    if row.is_duplicate_scan or (earlier and is_content_duplicate(row, earlier)):
        result.is_duplicate = True
        result.notes.append("duplicate scan; discarded")
        return result
    if is_noise(row):
        result.is_noise = True
        result.notes.append(f"{row.status_code} is routine, not an exception")
        return result
    if scan_for_injection(row.status_description):
        result.injection_detected = True
        result.notes.append(
            "driver note matched prompt-injection patterns; note treated as data only "
            "and case flagged for review"
        )
    return result
