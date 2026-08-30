"""Evaluation against ground_truth.csv (row-aligned with delivery_logs.csv)."""

import csv
from pathlib import Path
from typing import List, Optional

from app.config import DATA_DIR
from app.models import EvaluationReport
from app.pipeline import Pipeline
from app.tools import read_delivery_logs


def read_ground_truth(path: Optional[Path] = None) -> List[dict]:
    path = path or (DATA_DIR / "ground_truth.csv")
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def evaluate(pipeline: Optional[Pipeline] = None) -> EvaluationReport:
    pipeline = pipeline or Pipeline()
    rows = read_delivery_logs()
    gt = read_ground_truth()
    assert len(rows) == len(gt), "ground truth must be row-aligned with delivery logs"

    per_case = []
    noise_ok = resolution_ok = escalation_ok = tone_ok = complete = 0
    exception_rows = 0

    for i, (row, truth) in enumerate(zip(rows, gt)):
        record = pipeline.process_row(row, i, earlier=rows[:i])
        gt_exception = truth["is_exception"] == "YES"
        pred_exception = record.triage.is_exception

        case = {
            "row": i,
            "shipment_id": row.shipment_id,
            "gt_exception": gt_exception,
            "pred_exception": pred_exception,
            "noise_dedup_correct": gt_exception == pred_exception,
        }
        if case["noise_dedup_correct"]:
            noise_ok += 1

        if gt_exception:
            exception_rows += 1
            pred_res = record.decision.resolution.value if record.decision else None
            pred_esc = bool(record.decision.escalate) if record.decision else None
            pred_tone = record.communication.tone.value if record.communication else None
            case.update(
                {
                    "gt_resolution": truth["expected_resolution"],
                    "pred_resolution": pred_res,
                    "resolution_correct": pred_res == truth["expected_resolution"],
                    "gt_escalate": truth["should_escalate"] == "YES",
                    "pred_escalate": pred_esc,
                    "escalation_correct": pred_esc == (truth["should_escalate"] == "YES"),
                    "gt_tone": truth["expected_tone"],
                    "pred_tone": pred_tone,
                    "tone_correct": pred_tone == truth["expected_tone"],
                }
            )
            resolution_ok += case["resolution_correct"]
            escalation_ok += case["escalation_correct"]
            tone_ok += case["tone_correct"]
            if (
                case["noise_dedup_correct"]
                and case["resolution_correct"]
                and case["escalation_correct"]
                and case["tone_correct"]
            ):
                complete += 1
        elif case["noise_dedup_correct"]:
            complete += 1
        per_case.append(case)

    n = len(rows)
    return EvaluationReport(
        total_rows=n,
        noise_dedup_accuracy=round(noise_ok / n, 4),
        resolution_accuracy=round(resolution_ok / exception_rows, 4) if exception_rows else 1.0,
        escalation_accuracy=round(escalation_ok / exception_rows, 4) if exception_rows else 1.0,
        tone_accuracy=round(tone_ok / exception_rows, 4) if exception_rows else 1.0,
        task_completion_rate=round(complete / n, 4),
        per_case=per_case,
    )
