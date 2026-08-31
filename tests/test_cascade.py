"""Model-cascade tests: tier selection, cost accounting, supervisor review."""

import json

import pytest
from fastapi.testclient import TestClient

from app.llm import LLMResponse
from app.models import CustomerProfile
from app.pipeline import Pipeline
from app.rules import assess_ambiguity
from app.store import CaseStore
from app.tools import list_lockers
from tests.test_rules import make_customer, make_row


class FakeClient:
    """Stands in for DeepSeekClient; returns scripted JSON per model."""

    def __init__(self, small: dict, large: dict = None):
        self.responses = {"deepseek-chat": small, "deepseek-reasoner": large or small}
        self.calls = []
        self.cache = type("C", (), {"stats": staticmethod(lambda: {"hit_rate": 0.0})})()

    def available(self):
        return True, None

    def chat(self, messages, json_mode=False, model=None):
        model = model or "deepseek-chat"
        self.calls.append(model)
        payload = self.responses[model]
        if "body" not in payload:  # resolution call vs communication call
            payload = dict(payload)
        return LLMResponse(
            json.dumps(payload), False, 5, "deepseek", model,
            input_tokens=1000, output_tokens=200,
            cost_usd=0.0005 if model == "deepseek-chat" else 0.002,
        )


AGREEING_COMM = {"subject": "Update", "body": "We are sorry about the delivery issue. " * 3 + "Next steps and timeline follow."}


def build_pipeline(tmp_path, client):
    return Pipeline(store=CaseStore(db_path=tmp_path / "c.db"), client=client)


def test_clear_case_stays_on_rules_tier(tmp_path):
    client = FakeClient({"resolution": "RETURN_TO_SENDER", "escalate": False, "confidence": 0.9})
    pipe = build_pipeline(tmp_path, client)
    row = make_row(status_code="REFUSED", status_description="customer said no thanks refused it")
    record = pipe.process_row(row, 0)
    assert record.model_tier == "rules"
    assert record.llm_cost_usd == 0.0
    assert client.calls == []  # no model call at all


def test_ambiguous_case_uses_small_model(tmp_path):
    small = {"resolution": "RESCHEDULE", "escalate": False, "confidence": 0.9,
             "reasoning": "weather delay, duration unknown, reschedule"}
    client = FakeClient(small)
    client.responses["deepseek-chat"] = small
    pipe = build_pipeline(tmp_path, client)
    # weather delay with no parseable duration on a STANDARD customer
    row = make_row(status_code="WEATHER_DELAY",
                   status_description="roads flooded delay unknown at this time")
    record = pipe.process_row(row, 0)
    assert record.model_tier == "small"
    assert "deepseek-chat" in client.calls
    assert "deepseek-reasoner" not in [c for c in client.calls[:1]]
    assert record.llm_cost_usd > 0


def test_low_confidence_escalates_to_large_model(tmp_path):
    small = {"resolution": "RESCHEDULE", "escalate": False, "confidence": 0.4,
             "reasoning": "not sure"}
    large = {"resolution": "REPLACE", "escalate": True, "confidence": 0.95,
             "reasoning": "perishable likely compromised, replace"}
    client = FakeClient(small, large)
    pipe = build_pipeline(tmp_path, client)
    row = make_row(status_code="WEATHER_DELAY", package_type="PERISHABLE",
                   status_description="storm, no delay estimate available")
    record = pipe.process_row(row, 0)
    assert record.model_tier == "large"
    resolution_calls = [c for c in client.calls if True]
    assert resolution_calls[0] == "deepseek-chat" and "deepseek-reasoner" in client.calls
    assert record.decision.resolution.value == "REPLACE"
    assert any("confidence" in r for r in record.decision.cascade_reasons)


def test_high_stakes_disagreement_escalates(tmp_path):
    # small model confident but disagrees with the rules baseline on a VIP case
    small = {"resolution": "NO_ACTION", "escalate": False, "confidence": 0.95,
             "reasoning": "looks fine"}
    large = {"resolution": "REPLACE", "escalate": True, "confidence": 0.9,
             "reasoning": "damaged fragile for VIP, replace"}
    client = FakeClient(small, large)
    pipe = build_pipeline(tmp_path, client)
    # DAMAGED with no known severity words -> ambiguous; VIP CUST-001 -> high stakes
    row = make_row(status_code="DAMAGED", customer_id="CUST-001", package_type="FRAGILE",
                   status_description="box looks weird somehow not sure whats wrong")
    record = pipe.process_row(row, 0)
    assert record.model_tier == "large"
    assert any("high-stakes" in r for r in record.decision.cascade_reasons)


def test_hard_triggers_survive_model_disagreement(tmp_path):
    # model says don't escalate; third attempt is a hard trigger
    small = {"resolution": "RESCHEDULE", "escalate": False, "confidence": 0.95,
             "reasoning": "just reschedule"}
    client = FakeClient(small)
    pipe = build_pipeline(tmp_path, client)
    row = make_row(attempt_number=3, status_description="x" * 230)  # long note -> ambiguous
    record = pipe.process_row(row, 0)
    assert record.decision.escalate is True
    assert record.decision.policy_overrides


def test_ambiguity_scoring():
    assert assess_ambiguity(make_row(status_code="REFUSED"))[0] == 0
    score, reasons = assess_ambiguity(
        make_row(status_code="DAMAGED", status_description="something happened to the box")
    )
    assert score >= 1 and any("severity" in r for r in reasons)
    assert assess_ambiguity(make_row(), injection_detected=True)[0] >= 1


def test_metrics_report_tiers_and_cost(tmp_path):
    small = {"resolution": "RESCHEDULE", "escalate": False, "confidence": 0.9, "reasoning": "ok"}
    client = FakeClient(small)
    pipe = build_pipeline(tmp_path, client)
    pipe.process_row(make_row(status_code="REFUSED", status_description="refused plain case"), 0)
    pipe.process_row(
        make_row(shipment_id="SHP-Y", status_code="WEATHER_DELAY",
                 status_description="flooding, duration unclear"), 1)
    metrics = pipe.store.metrics()
    assert metrics["by_model_tier"].get("rules") == 1
    assert metrics["by_model_tier"].get("small") == 1
    assert metrics["total_llm_cost_usd"] > 0
    assert metrics["cost_per_1000_exceptions_usd"] > 0


def test_supervisor_approve_and_override(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from app import api

    client = TestClient(api.app)
    client.post("/process")
    cases = client.get("/cases").json()["cases"]
    escalated = [c for c in cases if c["review_status"] == "pending_review"]
    assert escalated

    case_id = escalated[0]["case_id"]
    approved = client.post(f"/cases/{case_id}/approve").json()
    assert approved["review_status"] == "approved"

    case_id2 = escalated[1]["case_id"]
    overridden = client.post(
        f"/cases/{case_id2}/override",
        json={"resolution": "HOLD_FOR_REVIEW", "note": "waiting on customer callback"},
    ).json()
    assert overridden["review_status"] == "overridden"
    detail = [c for c in client.get("/cases").json()["cases"] if c["case_id"] == case_id2][0]
    assert detail["decision"]["resolution"] == "HOLD_FOR_REVIEW"
    assert any("supervisor override" in o for o in detail["decision"]["policy_overrides"])

    assert client.post("/cases/nope/approve").status_code == 404
    assert client.post(f"/cases/{case_id}/override", json={"resolution": "BAD"}).status_code == 422


def test_unknown_status_routes_to_llm_tier(tmp_path):
    small = {"resolution": "HOLD_FOR_REVIEW", "escalate": False, "confidence": 0.9,
             "reasoning": "unknown status, hold"}
    client = FakeClient(small)
    pipe = build_pipeline(tmp_path, client)
    row = make_row(status_code="CUSTOMS_HOLD", status_description="held at customs paperwork issue")
    record = pipe.process_row(row, 0)
    assert record.model_tier == "small"
    assert record.decision.resolution.value == "HOLD_FOR_REVIEW"


def test_llm_judge_scores_cases(tmp_path):
    from app.judge import judge_cases

    small = {"resolution": "RESCHEDULE", "escalate": False, "confidence": 0.9, "reasoning": "ok"}
    client = FakeClient(small)
    client.responses["deepseek-reasoner"] = {"score": 4, "rationale": "sound and grounded"}
    pipe = build_pipeline(tmp_path, client)
    pipe.process_row(make_row(status_code="REFUSED", status_description="refused it outright"), 0)
    report = judge_cases(pipe.store.list_cases(), client, sample=5)
    assert report["judged"] == 1
    assert report["average_score"] == 4.0
    assert report["per_case"][0]["rationale"]


def test_llm_judge_endpoint_gated_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from app import api

    client = TestClient(api.app)
    assert client.post("/evaluate/judge").status_code == 503


def test_worker_pool_idempotent(tmp_path):
    import threading

    from app.models import LogRow
    from app.queuing import InMemoryQueue, case_id_for

    q = InMemoryQueue()
    event = {
        "shipment_id": "SHP-W1", "timestamp": "2026-03-05T10:00:00",
        "status_code": "REFUSED", "status_description": "did not want it",
        "customer_id": "CUST-003", "delivery_address": "1 Test St, Town, 10001",
        "package_type": "STANDARD", "package_size": "SMALL",
        "attempt_number": 1, "is_duplicate_scan": False,
    }
    for _ in range(5):  # same event redelivered five times
        q.put(event)

    pipe = build_pipeline(tmp_path, FakeClient({"resolution": "RETURN_TO_SENDER", "escalate": False, "confidence": 0.9}))

    def worker():
        while True:
            e = q.get(timeout=0.2)
            if e is None:
                return
            pipe.process_row(LogRow.model_validate(e), 0, case_id=case_id_for(e))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert pipe.store.metrics()["total_cases"] == 1  # processed once, not five times
