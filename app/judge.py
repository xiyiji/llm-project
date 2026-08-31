"""LLM-as-judge: grade decision reasoning on sampled processed cases.

Complements the exact-match evaluation harness. The large model grades each
sampled decision for playbook grounding and coherence on a 1-5 scale, so
prompt or model changes can be compared beyond the small labeled set.
"""

import json
from typing import Dict, List

from app.config import get_config
from app.llm import DeepSeekClient, LLMUnavailableError
from app.models import CaseRecord

JUDGE_SYSTEM_PROMPT = """You grade decisions made by a delivery-exception system.
Given the case facts, the chosen resolution and the stated reasoning, score 1-5:
5 = resolution and reasoning clearly follow delivery operations best practice and the stated facts;
3 = defensible but reasoning is thin or partly unsupported; 1 = wrong or contradicts the facts.
Respond with JSON: {"score": <1-5>, "rationale": "<one sentence>"}"""


def judge_cases(
    cases: List[CaseRecord], client: DeepSeekClient, sample: int = 10
) -> Dict:
    decided = [c for c in cases if c.decision is not None][:sample]
    if not decided:
        return {"judged": 0, "average_score": None, "per_case": []}

    per_case = []
    total = 0.0
    model = get_config().llm.large_model
    for case in decided:
        payload = {
            "shipment_id": case.shipment_id,
            "status_code": case.status_code,
            "resolution": case.decision.resolution.value,
            "escalated": case.decision.escalate,
            "reasoning": case.decision.reasoning,
            "escalation_reasons": case.decision.escalation_reasons,
        }
        response = client.chat(
            [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
            json_mode=True,
            model=model,
        )
        verdict = json.loads(response.text)
        score = max(1.0, min(5.0, float(verdict.get("score", 0))))
        total += score
        per_case.append({
            "shipment_id": case.shipment_id,
            "resolution": case.decision.resolution.value,
            "score": score,
            "rationale": str(verdict.get("rationale", "")),
            "cost_usd": response.cost_usd,
        })
    return {
        "judged": len(per_case),
        "judge_model": model,
        "average_score": round(total / len(per_case), 2),
        "per_case": per_case,
    }
