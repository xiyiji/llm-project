"""Deterministic data-access tools: delivery logs, customer DB, lockers."""

import csv
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from app.config import DATA_DIR
from app.models import CustomerProfile, Locker, LogRow


def read_delivery_logs(path: Optional[Path] = None) -> List[LogRow]:
    path = path or (DATA_DIR / "delivery_logs.csv")
    rows: List[LogRow] = []
    with path.open("r", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            raw["attempt_number"] = int(raw["attempt_number"])
            raw["is_duplicate_scan"] = raw["is_duplicate_scan"].strip().lower() == "true"
            rows.append(LogRow.model_validate(raw))
    return rows


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or (DATA_DIR / "customers.db"))
    conn.row_factory = sqlite3.Row
    return conn


def get_customer(customer_id: str, db_path: Optional[Path] = None) -> Optional[CustomerProfile]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
    return CustomerProfile.model_validate(dict(row)) if row else None


def list_lockers(db_path: Optional[Path] = None) -> List[Locker]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM lockers").fetchall()
    return [Locker.model_validate(dict(r)) for r in rows]


def lockers_by_zip(db_path: Optional[Path] = None) -> Dict[str, List[Locker]]:
    grouped: Dict[str, List[Locker]] = {}
    for locker in list_lockers(db_path):
        grouped.setdefault(locker.zip_code, []).append(locker)
    return grouped


def adjacent_zips(zip_code: str) -> List[str]:
    """Numeric neighbors count as adjacent (10002 -> 10001, 10003)."""
    try:
        z = int(zip_code)
    except ValueError:
        return []
    return [str(z - 1), str(z + 1)]
