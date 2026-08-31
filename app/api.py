"""FastAPI service for the exception handling pipeline."""

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.config import get_config
from app.evaluation import evaluate
from app.judge import judge_cases
from app.llm import get_client
from app.pipeline import Pipeline
from app.playbook import search_playbook
from app.tools import read_delivery_logs

app = FastAPI(
    title="Delivery Exception Handler",
    description="LLM-assisted last-mile delivery exception triage, resolution and customer communication.",
    version="1.0.0",
)

_pipeline = Pipeline()


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> str:
    return """<!doctype html><html><head><meta charset="utf-8">
<title>Delivery Exception Handler</title>
<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:60px auto;padding:0 20px;line-height:1.7;color:#222}
a{color:#8a4b0f}li{margin:6px 0}</style></head><body>
<h1>Delivery Exception Handler</h1>
<p>This service reads courier scan logs, spots failed deliveries (nobody home,
damaged box, wrong address...), decides what to do next by the company
playbook, and writes the message the customer receives.</p>
<ul>
<li><a href="/docs">Try the API</a> (run POST /process, then look at GET /metrics)</li>
<li><a href="/health">Health</a> &middot; <a href="/metrics">Metrics</a> &middot; <a href="/cases">Cases</a></li>
<li>Source: <a href="https://github.com/xiyiji/llm-project">github.com/xiyiji/llm-project</a></li>
</ul>
<p>Sister project: <b>LLM Router</b>, which picks the best AI model per request:
<a href="https://llm-router-api-9uqw.onrender.com">llm-router-api-9uqw.onrender.com</a></p>
</body></html>"""


@app.get("/health")
def health() -> dict:
    ok, reason = _pipeline.client.available()
    return {
        "status": "healthy",
        "llm": {
            "provider": get_config().llm.provider,
            "small_model": get_config().llm.small_model,
            "large_model": get_config().llm.large_model,
            "available": ok,
            **({} if ok else {"reason": reason}),
        },
        "data": {"delivery_log_rows": len(read_delivery_logs())},
    }


@app.post("/process/{shipment_id}")
def process_shipment(shipment_id: str) -> dict:
    records = _pipeline.process_shipment(shipment_id)
    if not records:
        raise HTTPException(status_code=404, detail=f"no log rows for {shipment_id}")
    return {"shipment_id": shipment_id, "cases": [r.model_dump() for r in records]}


@app.post("/process")
def process_all() -> dict:
    records = _pipeline.process_all()
    return {
        "processed": len(records),
        "exceptions": sum(1 for r in records if r.triage.is_exception),
        "escalated": sum(1 for r in records if r.decision and r.decision.escalate),
    }


@app.get("/cases")
def list_cases(shipment_id: Optional[str] = None) -> dict:
    return {"cases": [r.model_dump() for r in _pipeline.store.list_cases(shipment_id)]}


@app.post("/cases/{case_id}/approve")
def approve_case(case_id: str) -> dict:
    record = _pipeline.store.set_review(case_id, "approved", "supervisor approved the decision")
    if record is None:
        raise HTTPException(status_code=404, detail=f"no case {case_id}")
    return {"case_id": case_id, "review_status": record.review_status}


@app.post("/cases/{case_id}/override")
def override_case(case_id: str, body: dict) -> dict:
    resolution = body.get("resolution")
    valid = {"RESCHEDULE", "REROUTE_TO_LOCKER", "REPLACE", "RETURN_TO_SENDER", "HOLD_FOR_REVIEW", "NO_ACTION"}
    if resolution not in valid:
        raise HTTPException(status_code=422, detail=f"resolution must be one of {sorted(valid)}")
    record = _pipeline.store.get(case_id)
    if record is None or record.decision is None:
        raise HTTPException(status_code=404, detail=f"no decided case {case_id}")
    old = record.decision.resolution.value
    from app.models import Resolution

    record.decision.resolution = Resolution(resolution)
    record.decision.policy_overrides.append(
        f"supervisor override: {old} -> {resolution}" + (f" ({body['note']})" if body.get("note") else "")
    )
    record.review_status = "overridden"
    _pipeline.store.save(record)
    return {"case_id": case_id, "review_status": "overridden", "resolution": resolution}


@app.get("/metrics")
def metrics() -> dict:
    return {
        "cases": _pipeline.store.metrics(),
        "llm_cache": _pipeline.client.cache.stats(),
    }


@app.post("/evaluate")
def run_evaluation() -> dict:
    return evaluate(_pipeline).model_dump()


@app.post("/evaluate/judge")
def run_llm_judge(sample: int = 10) -> dict:
    from app.llm import LLMUnavailableError

    ok, reason = _pipeline.client.available()
    if not ok:
        raise HTTPException(status_code=503, detail=f"LLM judge unavailable: {reason}")
    try:
        return judge_cases(_pipeline.store.list_cases(), _pipeline.client, sample=sample)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"LLM judge unavailable: {exc}")


@app.get("/playbook/search")
def playbook_search(q: str, top_k: int = 3) -> dict:
    return {"query": q, "results": search_playbook(q, top_k)}
