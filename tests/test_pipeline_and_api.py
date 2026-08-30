"""End-to-end pipeline, evaluation, and API tests (offline: rules baseline)."""

import pytest
from fastapi.testclient import TestClient

from app.config import VAR_DIR
from app.evaluation import evaluate
from app.pipeline import Pipeline
from app.store import CaseStore


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


@pytest.fixture
def pipeline(offline, tmp_path):
    return Pipeline(store=CaseStore(db_path=tmp_path / "cases.db"))


def test_process_all_counts(pipeline):
    records = pipeline.process_all()
    assert len(records) == 13
    exceptions = [r for r in records if r.triage.is_exception]
    assert len(exceptions) == 9
    assert all(r.decision is not None for r in exceptions)
    assert all(r.communication is not None for r in exceptions)


def test_offline_runs_on_rules(pipeline):
    records = pipeline.process_all()
    assert all(r.provider == "rules" for r in records if r.triage.is_exception)


def test_metrics_persist(pipeline):
    pipeline.process_all()
    metrics = pipeline.store.metrics()
    assert metrics["total_cases"] == 13
    assert metrics["exceptions"] == 9
    assert metrics["escalation_rate"] > 0.5


def test_evaluation_perfect_on_baseline(pipeline):
    report = evaluate(pipeline)
    assert report.total_rows == 13
    assert report.noise_dedup_accuracy == 1.0
    assert report.resolution_accuracy == 1.0
    assert report.escalation_accuracy == 1.0
    assert report.tone_accuracy == 1.0
    assert report.task_completion_rate == 1.0


def test_communication_includes_locker_details(pipeline):
    records = pipeline.process_shipment("SHP-005")
    exception = [r for r in records if r.triage.is_exception][0]
    assert exception.decision.resolution.value == "REROUTE_TO_LOCKER"
    assert exception.decision.escalate  # locker full in 10003, supervisor involved
    assert exception.communication.validation_passed


def test_vip_damage_gets_credit(pipeline):
    records = pipeline.process_shipment("SHP-004")
    exception = [r for r in records if r.triage.is_exception][0]
    assert exception.decision.service_credit_usd == 10.0
    assert "credit" in exception.communication.body.lower()


def test_api_endpoints(offline):
    from app import api

    client = TestClient(api.app)
    assert client.get("/health").status_code == 200
    body = client.get("/health").json()
    assert body["llm"]["available"] is False

    result = client.post("/process").json()
    assert result["processed"] == 13

    metrics = client.get("/metrics").json()
    assert "llm_cache" in metrics and "hit_rate" in metrics["llm_cache"]

    search = client.get("/playbook/search", params={"q": "damaged perishable"}).json()
    assert search["results"]
    assert any("Damaged" in r["title"] or "Weather" in r["title"] for r in search["results"])

    assert client.post("/process/NOPE").status_code == 404

    report = client.post("/evaluate").json()
    assert report["task_completion_rate"] == 1.0


def test_api_failure_degrades_to_rules(monkeypatch, tmp_path):
    """A failing LLM API (bad key, no balance, outage) must not 500."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-invalid")
    from app.llm import DeepSeekClient

    class _Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("Error code: 402 - Insufficient Balance")

    monkeypatch.setattr(DeepSeekClient, "_sdk", lambda self: _Boom)
    pipe = Pipeline(store=CaseStore(db_path=tmp_path / "c.db"), client=DeepSeekClient())
    records = pipe.process_shipment("SHP-004")
    exception = [r for r in records if r.triage.is_exception][0]
    assert exception.decision is not None
    assert exception.provider == "rules"
    assert exception.decision.resolution.value == "REPLACE"
