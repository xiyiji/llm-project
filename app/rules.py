"""Deterministic policy engine derived from the exception resolution playbook.

The LLM proposes; these rules enforce. Hard escalation triggers and resolution
constraints from the playbook always win over model output.
"""

import re
from typing import List, Optional, Tuple

from app.config import get_config
from app.models import CustomerProfile, Locker, LogRow, Resolution, Tone
from app.tools import adjacent_zips

NOISE_STATUSES = {"DELIVERED", "SCANNED"}

SEVERE_DAMAGE_TERMS = ("leak", "spoil", "odor", "smell", "contents visible")
MODERATE_DAMAGE_TERMS = ("crush", "partially open", "shifting", "torn open")
MINOR_DAMAGE_TERMS = ("scuff", "small dent", "torn label")

FRAUD_TERMS = ("vacant lot", "demolished", "construction site")
SAFETY_TERMS = ("dog attacked", "threat", "unsafe", "weapon", "assault")

_DELAY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:hr|hrs|hour|hours|h)\b", re.IGNORECASE)


def is_noise(row: LogRow) -> bool:
    return row.status_code in NOISE_STATUSES


def parse_delay_hours(description: str) -> Optional[float]:
    m = _DELAY_RE.search(description)
    return float(m.group(1)) if m else None


def damage_severity(description: str, package_type: str) -> str:
    """Return minor / moderate / severe; FRAGILE bumps one level up."""
    desc = description.lower()
    if any(t in desc for t in SEVERE_DAMAGE_TERMS):
        level = 2
    elif any(t in desc for t in MODERATE_DAMAGE_TERMS):
        level = 1
    elif any(t in desc for t in MINOR_DAMAGE_TERMS):
        level = 0
    else:
        level = 1  # unclassified damage: treat as moderate rather than deliver broken goods
    if package_type == "FRAGILE":
        level = min(level + 1, 2)
    return ("minor", "moderate", "severe")[level]


def perishable_compromised(row: LogRow) -> bool:
    """Weather-delayed perishable past the playbook threshold counts as compromised."""
    if row.package_type != "PERISHABLE" or row.status_code != "WEATHER_DELAY":
        return False
    delay = parse_delay_hours(row.status_description)
    threshold = get_config().thresholds.perishable_delay_hours
    return delay is None or delay > threshold  # unknown delay: err on the side of pulling it


def evaluate_escalation(row: LogRow, customer: CustomerProfile) -> Tuple[bool, List[str]]:
    t = get_config().thresholds
    reasons: List[str] = []
    desc = row.status_description.lower()

    if row.attempt_number >= t.escalation_attempt_number:
        reasons.append(f"attempt {row.attempt_number} reached the third-attempt threshold")
    if customer.tier == "VIP" and customer.exceptions_last_90d >= t.vip_exception_threshold:
        reasons.append(
            f"VIP customer with {customer.exceptions_last_90d} exceptions in 90 days"
        )
    if row.status_code == "DAMAGED" and row.package_type == "PERISHABLE":
        reasons.append("damaged perishable package")
    if perishable_compromised(row):
        reasons.append("weather-compromised perishable past the 4 hour threshold")
    if row.status_code == "DAMAGED" and customer.tier == "VIP" and row.package_type == "FRAGILE":
        if damage_severity(row.status_description, row.package_type) != "minor":
            reasons.append("non-minor damage to a VIP fragile package")
    if any(term in desc for term in FRAUD_TERMS):
        reasons.append("address suggests possible fraud")
    if any(term in desc for term in SAFETY_TERMS):
        reasons.append("driver reported a safety concern")
    if customer.tier == "STANDARD" and customer.exceptions_last_90d > t.standard_exception_threshold:
        reasons.append(
            f"standard customer with {customer.exceptions_last_90d} exceptions in 90 days"
        )
    if (
        customer.tier == "PREMIUM"
        and row.package_type == "PERISHABLE"
        and row.status_code == "WEATHER_DELAY"
    ):
        delay = parse_delay_hours(row.status_description)
        if delay is not None and delay > t.premium_perishable_delay_hours:
            reasons.append("premium perishable delayed past 2 hours")

    return bool(reasons), reasons


def locker_eligible(locker: Locker, row: LogRow) -> bool:
    if row.package_type == "PERISHABLE":
        return False
    sizes = ["SMALL", "MEDIUM", "LARGE"]
    if sizes.index(row.package_size) > sizes.index(locker.max_package_size):
        return False
    if locker.capacity_status == "FULL":
        return False
    if locker.capacity_status == "LIMITED" and row.package_size != "SMALL":
        return False
    return True


def find_locker(
    row: LogRow, lockers: List[Locker], same_zip_only: bool = False
) -> Optional[Locker]:
    zips = [row.zip_code] if same_zip_only else [row.zip_code] + adjacent_zips(row.zip_code)
    for zip_code in zips:
        for locker in lockers:
            if locker.zip_code == zip_code and locker_eligible(locker, row):
                return locker
    return None


def decide_resolution(
    row: LogRow, customer: CustomerProfile, lockers: List[Locker]
) -> Tuple[Resolution, List[str], Optional[Locker]]:
    """Playbook-derived baseline resolution. Returns (resolution, reasons, locker)."""
    reasons: List[str] = []
    desc = row.status_description.lower()

    if row.status_code == "REFUSED":
        reasons.append("customer refused delivery; playbook section 4: return to sender")
        return Resolution.RETURN_TO_SENDER, reasons, None

    if row.status_code == "DAMAGED":
        severity = damage_severity(row.status_description, row.package_type)
        if severity == "minor":
            reasons.append("minor cosmetic damage; deliver and note it")
            return Resolution.NO_ACTION, reasons, None
        reasons.append(f"{severity} damage; playbook section 3: pull and replace")
        return Resolution.REPLACE, reasons, None

    if row.status_code == "WEATHER_DELAY":
        if perishable_compromised(row):
            reasons.append("perishable past the 4 hour weather threshold; replace")
            return Resolution.REPLACE, reasons, None
        reasons.append("weather delay within tolerance; notify and reschedule")
        return Resolution.RESCHEDULE, reasons, None

    if row.status_code == "ADDRESS_ISSUE":
        if any(term in desc for term in FRAUD_TERMS):
            reasons.append("possible fraudulent address; hold for fraud review")
            return Resolution.HOLD_FOR_REVIEW, reasons, None
        reasons.append("address needs verification; contact customer then reschedule")
        return Resolution.RESCHEDULE, reasons, None

    if row.status_code == "ATTEMPTED":
        if row.attempt_number >= get_config().thresholds.escalation_attempt_number:
            locker = find_locker(row, lockers)
            if locker:
                reasons.append(f"third attempt; reroute to locker {locker.locker_id}")
            else:
                reasons.append(
                    "third attempt; locker reroute intended but no eligible locker, "
                    "supervisor to arrange an alternative"
                )
            return Resolution.REROUTE_TO_LOCKER, reasons, locker
        # At the second attempt a reroute is only offered for a locker in the
        # customer's own zip; sending them to an adjacent zip waits for attempt 3.
        locker = find_locker(row, lockers, same_zip_only=True) if row.attempt_number >= 2 else None
        if locker:
            reasons.append(f"second attempt; offer reroute to locker {locker.locker_id}")
            return Resolution.REROUTE_TO_LOCKER, reasons, locker
        reasons.append(f"attempt {row.attempt_number}; reschedule next business day")
        return Resolution.RESCHEDULE, reasons, None

    reasons.append(f"unrecognized status {row.status_code}; hold for review")
    return Resolution.HOLD_FOR_REVIEW, reasons, None


def service_credit(row: LogRow, customer: CustomerProfile) -> float:
    if row.status_code == "DAMAGED" and customer.tier == "VIP":
        severity = damage_severity(row.status_description, row.package_type)
        return {"minor": 5.0, "moderate": 10.0, "severe": 10.0}[severity]
    return 0.0


def tone_for(customer: CustomerProfile) -> Tone:
    return Tone.FORMAL if customer.tier in ("VIP", "PREMIUM") else Tone.CASUAL


def channel_for(customer: CustomerProfile) -> str:
    return customer.preferred_channel
