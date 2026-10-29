"""Inspect the real regression job: which rows carry non-numeric quantities."""
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "web_outputs/regress_real_photo_check"
for directory in sorted(root.iterdir()):
    receipt_file = directory / "receipt.json"
    if not receipt_file.exists():
        continue
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    print("JOB", directory.name, "status rows:", len(receipt.get("rows", [])))
    for row in receipt.get("rows", []):
        if row.get("kind") not in ("product", "service"):
            continue
        for field in ("quantity", "price", "line_total"):
            value = row.get(field)
            try:
                Decimal(str(value))
                clean = True
            except (InvalidOperation, ValueError):
                clean = False
            if not clean:
                print(f"  row {row['row']} {row.get('kind')}: {field}={value!r} name={row.get('name')!r} invalid={row.get('invalid_fields')}")
    break
