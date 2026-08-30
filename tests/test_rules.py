"""Policy engine tests."""

from app.models import CustomerProfile, LogRow
from app.rules import (
    damage_severity,
    evaluate_escalation,
    find_locker,
    locker_eligible,
    parse_delay_hours,
    perishable_compromised,
)
from app.tools import list_lockers


def make_row(**overrides) -> LogRow:
    base = {
        "shipment_id": "SHP-X",
        "timestamp": "2026-03-05T10:00:00",
        "status_code": "ATTEMPTED",
        "status_description": "nobody home",
        "customer_id": "CUST-003",
        "delivery_address": "1 Test St, Town, 10001",
        "package_type": "STANDARD",
        "package_size": "SMALL",
        "attempt_number": 1,
        "is_duplicate_scan": False,
    }
    base.update(overrides)
    return LogRow.model_validate(base)


def make_customer(**overrides) -> CustomerProfile:
    base = {
        "customer_id": "CUST-X",
        "name": "Test",
        "tier": "STANDARD",
        "preferred_channel": "SMS",
        "exceptions_last_90d": 0,
        "active_credit": 0.0,
    }
    base.update(overrides)
    return CustomerProfile.model_validate(base)


def test_parse_delay_hours():
    assert parse_delay_hours("estimated 5hr delay") == 5.0
    assert parse_delay_hours("about 2 hours late") == 2.0
    assert parse_delay_hours("roads blocked") is None


def test_damage_severity_fragile_bump():
    assert damage_severity("box crushed on one side", "STANDARD") == "moderate"
    assert damage_severity("box crushed on one side", "FRAGILE") == "severe"
    assert damage_severity("small dent on corner", "STANDARD") == "minor"
    assert damage_severity("package is leaking liquid", "PERISHABLE") == "severe"


def test_perishable_weather_threshold():
    row = make_row(status_code="WEATHER_DELAY", package_type="PERISHABLE",
                   status_description="snow, estimated 5hr delay")
    assert perishable_compromised(row) is True
    row2 = make_row(status_code="WEATHER_DELAY", package_type="PERISHABLE",
                    status_description="snow, estimated 2hr delay")
    assert perishable_compromised(row2) is False


def test_third_attempt_escalates_any_tier():
    escalate, reasons = evaluate_escalation(make_row(attempt_number=3), make_customer())
    assert escalate and any("third-attempt" in r for r in reasons)


def test_vip_history_escalates():
    escalate, _ = evaluate_escalation(
        make_row(), make_customer(tier="VIP", exceptions_last_90d=3)
    )
    assert escalate


def test_standard_low_history_does_not_escalate():
    escalate, _ = evaluate_escalation(make_row(), make_customer(exceptions_last_90d=2))
    assert not escalate


def test_locker_rules():
    lockers = {l.locker_id: l for l in list_lockers()}
    small = make_row(package_size="SMALL")
    assert not locker_eligible(lockers["LOC-003"], small)          # FULL
    assert locker_eligible(lockers["LOC-002"], small)              # LIMITED + SMALL ok
    medium = make_row(package_size="MEDIUM")
    assert not locker_eligible(lockers["LOC-002"], medium)         # LIMITED + MEDIUM no
    perishable = make_row(package_type="PERISHABLE")
    assert not locker_eligible(lockers["LOC-001"], perishable)     # never perishable


def test_find_locker_uses_adjacent_zip():
    row = make_row(delivery_address="1 Test St, Town, 10005", package_size="LARGE")
    locker = find_locker(row, list_lockers())
    assert locker is not None and locker.locker_id == "LOC-006"    # 10006 is adjacent
