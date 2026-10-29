"""Etap 7: full real-photo regression through the ordinary pipeline and new endpoints.

Copies one legacy real photo (read-only), runs it through the complete OCR
pipeline on an ephemeral server, then verifies the invoice API on the result.
Writes a machine-readable summary to stdout. Usage:
  .venv/Scripts/python.exe -X utf8 tools/regress_real_photo_invoicing.py
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from App.web_server import create_server

PHOTO = ROOT / "web_outputs/771f241fc8674a78a4624a526299058e/upload.bin"
TIMEOUT_SECONDS = 25 * 60


def request_json(url, payload=None, method="GET", raw=False, data=None):
    body = data if data is not None else (json.dumps(payload).encode() if payload is not None else None)
    headers = {"Content-Type": "application/json"} if body and not data else {}
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            if raw:
                return response.status, body
            return response.status, json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            return error.code, json.loads(body.decode("utf-8"))
        except ValueError:
            return error.code, body.decode("utf-8", "replace")


def main() -> int:
    if not PHOTO.exists():
        print("NO_PHOTO", PHOTO)
        return 2
    output_dir = ROOT / "web_outputs/regress_real_photo_check"
    instance = create_server("127.0.0.1", 0, output_dir)
    instance.store.pipeline.knowledge.initialize()
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{instance.server_port}"
    summary: dict[str, object] = {"photo": PHOTO.name, "photo_kb": PHOTO.stat().st_size // 1024}
    try:
        started = time.time()
        status, created = request_json(base + "/api/jobs?filename=legacy_real.png",
                                       data=PHOTO.read_bytes(), method="POST")
        if status != 202:
            summary["submit"] = (status, created)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1
        job_id = created["id"]
        deadline = time.time() + TIMEOUT_SECONDS
        state = None
        while time.time() < deadline:
            _, state = request_json(base + f"/api/jobs/{job_id}")
            if state["status"] in {"done", "failed"}:
                break
            time.sleep(2)
        summary["ocr_seconds"] = round(time.time() - started, 1)
        summary["status"] = (state or {}).get("status")
        result = (state or {}).get("result") or {}
        if state and state["status"] == "done":
            items = [row for row in result.get("rows", []) if row.get("kind") in ("product", "service")]
            summary["rows"] = len(result.get("rows", []))
            summary["items"] = len(items)
            summary["validation_status"] = (result.get("calculation") or {}).get("validation_status")
            summary["finalized"] = result.get("finalized")
            summary["product_count"] = result.get("product_count")
            summary["expected_total"] = result.get("expected_total")
        status, model = request_json(base + f"/api/jobs/{job_id}/invoice")
        summary["invoice_status"] = status
        if status == 200:
            generation = model["generation"]
            line_sum = sum(float(str(row["amount"]).replace(",", "."))
                           for row in generation["items"] if row.get("amount"))
            summary["generation_status"] = generation["status"]
            summary["invoice_total"] = generation["total"]
            summary["items_sum"] = round(line_sum, 2)
            summary["candidates_rows"] = len(model["candidates"])
            summary["blocked_count"] = len(model["blocked"])
            summary["pdf_ready"] = model["ready"]
            for indexed, row in enumerate(generation["items"]):
                candidates = model["candidates"].get(str(row["row_id"]), {})
                summary.setdefault("candidates_sample", []).append(
                    {"row": row["row_id"], "status": candidates.get("status"),
                     "proposals": len(candidates.get("items", [])),
                     "remembered": len(candidates.get("remembered", []))})
        status, catalog = request_json(base + "/api/catalog-1c?q=00000019603")
        summary["catalog_status"] = status
        summary["catalog_hit"] = (catalog.get("items") or [{}])[0].get("name", "")[:32]
        # Static assets served for the new panel:
        for asset in ("/invoice.js", "/invoice.css"):
            file_status, body = request_json(base + asset, raw=True)
            summary.setdefault("static_ok", {})[asset] = file_status == 200 and len(body) > 200
    finally:
        instance.shutdown()
        instance.server_close()
        instance.store.pool.shutdown(wait=True)
        thread.join(timeout=3)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    ok = summary.get("status") == "done" and summary.get("invoice_status") == 200 \
        and summary.get("catalog_status") == 200 and all(summary.get("static_ok", {}).values())
    summary["result_ok"] = ok
    print(json.dumps({key: summary[key] for key in ("result_ok", "status", "invoice_status",
                                                    "catalog_status", "static_ok")},
                     ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
