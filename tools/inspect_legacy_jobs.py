"""List legacy real-photo jobs: size, status, row counts (read-only probe)."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "web_outputs"
for directory in sorted(root.iterdir()):
    state_file = directory / "state.json"
    upload = directory / "upload.bin"
    if not state_file.exists() or not upload.exists():
        continue
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as error:
        print(directory.name, "state unreadable:", error)
        continue
    result = state.get("result") or {}
    rows = result.get("rows") or []
    items = [row for row in rows if row.get("kind") in ("product", "service")]
    print(f"{directory.name} size={upload.stat().st_size // 1024}KB status={state.get('status')} "
          f"rows={len(rows)} items={len(items)} finalized={result.get('finalized')} "
          f"validation={(result.get('calculation') or {}).get('validation_status')} "
          f"date={result.get('date')} total={result.get('expected_total')}")
