"""Generate synthetic delivery logs for load testing and demos.

Usage: python scripts/generate_data.py 500 > synthetic_logs.csv
"""

import csv
import random
import sys
from datetime import datetime, timedelta

STATUSES = [
    ("DELIVERED", "Left at front door, signed by resident", 0.55),
    ("ATTEMPTED", "Nobody home rang bell no answer left notice", 0.18),
    ("ADDRESS_ISSUE", "cant find the building asked around nobody knows it", 0.07),
    ("DAMAGED", "Box crushed on one side contents might be damaged", 0.06),
    ("REFUSED", "Customer said they didnt order this refused to accept", 0.05),
    ("WEATHER_DELAY", "Heavy snow on route estimated {h}hr delay", 0.05),
    ("SCANNED", "Scanned at depot during morning sort", 0.04),
]
PACKAGE_TYPES = ["STANDARD", "STANDARD", "STANDARD", "FRAGILE", "PERISHABLE"]
SIZES = ["SMALL", "MEDIUM", "LARGE"]
STREETS = ["Maple Drive", "Birch Lane", "Oak Avenue", "Pine Road", "Elm Boulevard", "Cedar Lane"]
TOWNS = [("Greenfield", "10001"), ("Riverside", "10002"), ("Westdale", "10003"),
         ("Northgate", "10004"), ("Eastport", "10005"), ("Southfield", "10006")]


def pick_status(rng):
    r, acc = rng.random(), 0.0
    for code, desc, p in STATUSES:
        acc += p
        if r <= acc:
            return code, desc
    return STATUSES[0][:2]


def main(n: int, seed: int = 7) -> None:
    rng = random.Random(seed)
    writer = csv.writer(sys.stdout)
    writer.writerow([
        "shipment_id", "timestamp", "status_code", "status_description", "customer_id",
        "delivery_address", "package_type", "package_size", "attempt_number", "is_duplicate_scan",
    ])
    t = datetime(2026, 3, 5, 8, 0)
    for i in range(1, n + 1):
        code, desc = pick_status(rng)
        if "{h}" in desc:
            desc = desc.format(h=rng.choice([2, 3, 5, 6]))
        town, zip_code = rng.choice(TOWNS)
        address = f"{rng.randint(1, 400)} {rng.choice(STREETS)}, {town}, {zip_code}"
        customer = f"CUST-{rng.randint(1, 12):03d}"
        attempt = rng.choice([1, 1, 1, 2, 3]) if code == "ATTEMPTED" else (0 if code == "SCANNED" else 1)
        t += timedelta(minutes=rng.randint(2, 25))
        row = [f"SHP-{i:04d}", t.isoformat(timespec="seconds"), code, desc, customer,
               address, rng.choice(PACKAGE_TYPES), rng.choice(SIZES), attempt, False]
        writer.writerow(row)
        if rng.random() < 0.08:  # duplicate scan a few minutes later
            dup = list(row)
            dup[1] = (t + timedelta(minutes=rng.randint(1, 4))).isoformat(timespec="seconds")
            dup[9] = True
            writer.writerow(dup)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
