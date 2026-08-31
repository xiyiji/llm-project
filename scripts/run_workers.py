"""Worker-pool throughput benchmark: N workers drain a queue of scan events.

Generates synthetic events, enqueues them (in-memory by default, Redis Streams
when REDIS_URL is set), runs a worker pool over the shared pipeline, and
reports throughput plus tier/cost breakdown. Redelivered events are skipped
via deterministic case ids.

Usage: python scripts/run_workers.py --events 5000 --workers 8
"""

import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import LogRow  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from app.queuing import case_id_for, get_queue  # noqa: E402
from app.store import CaseStore  # noqa: E402
from scripts.generate_data import PACKAGE_TYPES, SIZES, STREETS, TOWNS, pick_status  # noqa: E402

import random
from datetime import datetime, timedelta


def make_events(n: int, seed: int = 7):
    rng = random.Random(seed)
    t = datetime(2026, 3, 5, 8, 0)
    events = []
    for i in range(1, n + 1):
        code, desc = pick_status(rng)
        if "{h}" in desc:
            desc = desc.format(h=rng.choice([2, 3, 5, 6]))
        town, zip_code = rng.choice(TOWNS)
        t += timedelta(seconds=rng.randint(5, 90))
        events.append({
            "shipment_id": f"SHP-{i:05d}",
            "timestamp": t.isoformat(timespec="seconds"),
            "status_code": code,
            "status_description": desc,
            "customer_id": f"CUST-{rng.randint(1, 12):03d}",
            "delivery_address": f"{rng.randint(1, 400)} {rng.choice(STREETS)}, {town}, {zip_code}",
            "package_type": rng.choice(PACKAGE_TYPES),
            "package_size": rng.choice(SIZES),
            "attempt_number": rng.choice([1, 1, 1, 2, 3]) if code == "ATTEMPTED" else (0 if code == "SCANNED" else 1),
            "is_duplicate_scan": False,
        })
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--redeliver", type=int, default=0,
                        help="re-enqueue this many events to prove idempotency")
    args = parser.parse_args()

    q = get_queue()
    events = make_events(args.events)
    for e in events:
        q.put(e)
    for e in events[: args.redeliver]:
        q.put(e)  # duplicates: workers must not double-process these

    store = CaseStore(db_path=Path("var") / "worker_bench.db")
    store.clear()
    pipeline = Pipeline(store=store)
    processed = []
    lock = threading.Lock()

    def worker():
        while True:
            event = q.get(timeout=0.5)
            if event is None:
                return
            row = LogRow.model_validate(event)
            record = pipeline.process_row(row, 0, case_id=case_id_for(event))
            with lock:
                processed.append(record.case_id)

    start = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(args.workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - start

    metrics = store.metrics()
    print(json.dumps({
        "queue_backend": type(q).__name__,
        "events_enqueued": args.events + args.redeliver,
        "unique_cases": metrics["total_cases"],
        "workers": args.workers,
        "wall_seconds": round(wall, 2),
        "events_per_second": round((args.events + args.redeliver) / wall, 1),
        "exceptions": metrics["exceptions"],
        "escalated": metrics["escalated"],
        "by_model_tier": metrics["by_model_tier"],
        "total_llm_cost_usd": metrics["total_llm_cost_usd"],
        "cost_per_1000_exceptions_usd": metrics["cost_per_1000_exceptions_usd"],
    }, indent=2))


if __name__ == "__main__":
    main()
