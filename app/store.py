"""SQLite persistence for processed cases; metrics survive restarts."""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional

from app.config import VAR_DIR
from app.models import CaseRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    shipment_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    status_code TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    is_exception INTEGER NOT NULL,
    resolution TEXT,
    escalate INTEGER,
    cached INTEGER NOT NULL,
    provider TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class CaseStore:
    def __init__(self, db_path: Optional[Path] = None):
        VAR_DIR.mkdir(exist_ok=True)
        self.db_path = db_path or (VAR_DIR / "cases.db")
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, record: CaseRecord) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record.case_id,
                    record.shipment_id,
                    record.row_index,
                    record.status_code,
                    record.customer_id,
                    int(record.triage.is_exception),
                    record.decision.resolution.value if record.decision else None,
                    int(record.decision.escalate) if record.decision else None,
                    int(record.cached),
                    record.provider,
                    record.latency_ms,
                    record.created_at,
                    record.model_dump_json(),
                ),
            )

    def get(self, case_id: str) -> Optional[CaseRecord]:
        with self._conn() as conn:
            row = conn.execute("SELECT payload FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return CaseRecord.model_validate(json.loads(row["payload"])) if row else None

    def list_cases(self, shipment_id: Optional[str] = None) -> List[CaseRecord]:
        query = "SELECT payload FROM cases"
        args: tuple = ()
        if shipment_id:
            query += " WHERE shipment_id = ?"
            args = (shipment_id,)
        query += " ORDER BY row_index"
        with self._conn() as conn:
            rows = conn.execute(query, args).fetchall()
        return [CaseRecord.model_validate(json.loads(r["payload"])) for r in rows]

    def metrics(self) -> Dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM cases").fetchone()["c"]
            if total == 0:
                return {"total_cases": 0}
            exceptions = conn.execute(
                "SELECT COUNT(*) c FROM cases WHERE is_exception = 1"
            ).fetchone()["c"]
            escalated = conn.execute(
                "SELECT COUNT(*) c FROM cases WHERE escalate = 1"
            ).fetchone()["c"]
            cached = conn.execute("SELECT COUNT(*) c FROM cases WHERE cached = 1").fetchone()["c"]
            by_resolution = {
                r["resolution"]: r["c"]
                for r in conn.execute(
                    "SELECT resolution, COUNT(*) c FROM cases "
                    "WHERE resolution IS NOT NULL GROUP BY resolution"
                )
            }
            by_provider = {
                r["provider"]: r["c"]
                for r in conn.execute("SELECT provider, COUNT(*) c FROM cases GROUP BY provider")
            }
            avg_latency = conn.execute(
                "SELECT AVG(latency_ms) a FROM cases WHERE is_exception = 1"
            ).fetchone()["a"]
        return {
            "total_cases": total,
            "exceptions": exceptions,
            "noise_or_duplicate": total - exceptions,
            "escalated": escalated,
            "escalation_rate": round(escalated / exceptions, 4) if exceptions else 0.0,
            "case_cache_hits": cached,
            "by_resolution": by_resolution,
            "by_provider": by_provider,
            "avg_latency_ms": round(avg_latency or 0.0, 2),
        }

    def clear(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM cases")
