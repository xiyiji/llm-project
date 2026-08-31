"""Event queue abstraction: in-memory by default, Redis Streams when REDIS_URL is set.

The pipeline stays synchronous; workers pull scan events off the queue and run
it. Idempotency comes from deterministic case ids (uuid5 of the event key), so
redelivered or replayed events are skipped instead of double-processed.
"""

import json
import os
import queue
import uuid
from typing import Dict, Optional

EVENT_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def event_key(event: Dict) -> str:
    return f"{event['shipment_id']}|{event['timestamp']}|{event['status_code']}|{event['attempt_number']}"


def case_id_for(event: Dict) -> str:
    """Deterministic case id: the same scan event always maps to the same case."""
    return str(uuid.uuid5(EVENT_NAMESPACE, event_key(event)))


class InMemoryQueue:
    def __init__(self):
        self._q: "queue.Queue[Dict]" = queue.Queue()

    def put(self, event: Dict) -> None:
        self._q.put(event)

    def get(self, timeout: float = 1.0) -> Optional[Dict]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def size(self) -> int:
        return self._q.qsize()


class RedisStreamQueue:
    """Redis Streams backend with a consumer group; requires REDIS_URL."""

    STREAM = "delivery_events"
    GROUP = "exception_workers"

    def __init__(self, url: str, consumer: str = "worker-1"):
        import redis  # optional dependency, only needed for this backend

        self._r = redis.from_url(url, decode_responses=True)
        self.consumer = consumer
        try:
            self._r.xgroup_create(self.STREAM, self.GROUP, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def put(self, event: Dict) -> None:
        self._r.xadd(self.STREAM, {"event": json.dumps(event)})

    def get(self, timeout: float = 1.0) -> Optional[Dict]:
        entries = self._r.xreadgroup(
            self.GROUP, self.consumer, {self.STREAM: ">"},
            count=1, block=int(timeout * 1000),
        )
        if not entries:
            return None
        _, messages = entries[0]
        msg_id, fields = messages[0]
        self._r.xack(self.STREAM, self.GROUP, msg_id)
        return json.loads(fields["event"])

    def size(self) -> int:
        return self._r.xlen(self.STREAM)


def get_queue(consumer: str = "worker-1"):
    url = os.environ.get("REDIS_URL")
    if url:
        return RedisStreamQueue(url, consumer)
    return InMemoryQueue()
