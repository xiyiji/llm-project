"""Data contracts for the exception handling pipeline."""

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Resolution(str, Enum):
    RESCHEDULE = "RESCHEDULE"
    REROUTE_TO_LOCKER = "REROUTE_TO_LOCKER"
    REPLACE = "REPLACE"
    RETURN_TO_SENDER = "RETURN_TO_SENDER"
    HOLD_FOR_REVIEW = "HOLD_FOR_REVIEW"
    NO_ACTION = "NO_ACTION"


class Tone(str, Enum):
    FORMAL = "FORMAL"
    CASUAL = "CASUAL"


class LogRow(BaseModel):
    shipment_id: str
    timestamp: str
    status_code: str
    status_description: str
    customer_id: str
    delivery_address: str
    package_type: str
    package_size: str
    attempt_number: int
    is_duplicate_scan: bool

    @property
    def zip_code(self) -> str:
        return self.delivery_address.rsplit(",", 1)[-1].strip()


class CustomerProfile(BaseModel):
    customer_id: str
    name: str
    tier: str
    preferred_channel: str
    exceptions_last_90d: int
    active_credit: float


class Locker(BaseModel):
    locker_id: str
    address: str
    zip_code: str
    capacity_status: str
    operating_hours: str
    max_package_size: str


class TriageResult(BaseModel):
    is_duplicate: bool = False
    is_noise: bool = False
    injection_detected: bool = False
    notes: List[str] = Field(default_factory=list)

    @property
    def is_exception(self) -> bool:
        return not (self.is_duplicate or self.is_noise)


class ResolutionDecision(BaseModel):
    resolution: Resolution
    escalate: bool
    escalation_reasons: List[str] = Field(default_factory=list)
    reasoning: str
    playbook_refs: List[str] = Field(default_factory=list)
    locker_id: Optional[str] = None
    service_credit_usd: float = 0.0
    llm_used: bool = False
    llm_agreed: Optional[bool] = None
    policy_overrides: List[str] = Field(default_factory=list)
    model_tier: str = "rules"
    cascade_reasons: List[str] = Field(default_factory=list)
    llm_confidence: Optional[float] = None
    llm_cost_usd: float = 0.0


class CommunicationDraft(BaseModel):
    channel: str
    tone: Tone
    subject: Optional[str] = None
    body: str
    validation_passed: bool = True
    validation_issues: List[str] = Field(default_factory=list)
    llm_used: bool = False
    revision_count: int = 0


class CaseRecord(BaseModel):
    case_id: str
    shipment_id: str
    row_index: int
    status_code: str
    customer_id: str
    triage: TriageResult
    decision: Optional[ResolutionDecision] = None
    communication: Optional[CommunicationDraft] = None
    cached: bool = False
    latency_ms: int = 0
    provider: str = "rules"
    model_tier: str = "rules"
    llm_cost_usd: float = 0.0
    review_status: str = "none"
    created_at: str = ""


class EvaluationReport(BaseModel):
    total_rows: int
    noise_dedup_accuracy: float
    resolution_accuracy: float
    escalation_accuracy: float
    tone_accuracy: float
    task_completion_rate: float
    per_case: List[Dict] = Field(default_factory=list)
