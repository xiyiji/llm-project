"""Pipeline orchestration: triage -> resolution -> communication -> persist."""

import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.agents import CommunicationAgent, ResolutionAgent
from app.llm import DeepSeekClient, get_client
from app.models import CaseRecord, LogRow
from app.store import CaseStore
from app.tools import get_customer, list_lockers, read_delivery_logs
from app.triage import triage_row


class Pipeline:
    def __init__(self, store: Optional[CaseStore] = None, client: Optional[DeepSeekClient] = None):
        self.store = store or CaseStore()
        self.client = client or get_client()
        self.resolution_agent = ResolutionAgent(self.client)
        self.communication_agent = CommunicationAgent(self.client)
        self._lockers = list_lockers()

    def process_row(
        self,
        row: LogRow,
        row_index: int,
        earlier: Optional[List[LogRow]] = None,
        case_id: Optional[str] = None,
    ) -> CaseRecord:
        if case_id is not None:
            existing = self.store.get(case_id)
            if existing is not None:
                return existing  # idempotent: this event was already processed
        start = time.time()
        triage = triage_row(row, earlier)
        record = CaseRecord(
            case_id=case_id or str(uuid.uuid4()),
            shipment_id=row.shipment_id,
            row_index=row_index,
            status_code=row.status_code,
            customer_id=row.customer_id,
            triage=triage,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        if triage.is_exception:
            customer = get_customer(row.customer_id)
            if customer is None:
                triage.notes.append(f"unknown customer {row.customer_id}; case held")
            else:
                decision, dec_cached, dec_latency = self.resolution_agent.decide(
                    row, customer, self._lockers, injection_detected=triage.injection_detected
                )
                locker = next(
                    (l for l in self._lockers if l.locker_id == decision.locker_id), None
                )
                comm, comm_cached, comm_latency, comm_cost = self.communication_agent.draft(
                    row, customer, decision, locker
                )
                record.decision = decision
                record.communication = comm
                record.cached = dec_cached or comm_cached
                record.provider = "deepseek" if decision.llm_used else "rules"
                record.model_tier = decision.model_tier
                record.llm_cost_usd = round(decision.llm_cost_usd + comm_cost, 8)
                record.review_status = "pending_review" if decision.escalate else "none"
                record.latency_ms = dec_latency + comm_latency

        if record.latency_ms == 0:
            record.latency_ms = int((time.time() - start) * 1000)
        self.store.save(record)
        return record

    def process_shipment(self, shipment_id: str) -> List[CaseRecord]:
        rows = read_delivery_logs()
        records = []
        for i, row in enumerate(rows):
            if row.shipment_id == shipment_id:
                records.append(self.process_row(row, i, earlier=rows[:i]))
        return records

    def process_all(self) -> List[CaseRecord]:
        rows = read_delivery_logs()
        return [self.process_row(row, i, earlier=rows[:i]) for i, row in enumerate(rows)]
