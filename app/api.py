"""FastAPI service for the exception handling pipeline."""

from typing import Optional

from fastapi import FastAPI, HTTPException

from app.config import get_config
from app.evaluation import evaluate
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


@app.get("/health")
def health() -> dict:
    ok, reason = _pipeline.client.available()
    return {
        "status": "healthy",
        "llm": {
            "provider": get_config().llm.provider,
            "model": get_config().llm.model,
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


@app.get("/metrics")
def metrics() -> dict:
    return {
        "cases": _pipeline.store.metrics(),
        "llm_cache": _pipeline.client.cache.stats(),
    }


@app.post("/evaluate")
def run_evaluation() -> dict:
    return evaluate(_pipeline).model_dump()


@app.get("/playbook/search")
def playbook_search(q: str, top_k: int = 3) -> dict:
    return {"query": q, "results": search_playbook(q, top_k)}
