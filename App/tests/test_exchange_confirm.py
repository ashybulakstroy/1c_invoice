"""Confirmation and frozen result snapshot (MVP-2 / M3).

Runs the real server with a synthetic verified receipt, confirms only after
explicit 1C links are saved, and checks the JSON 1.1 contract, checksum,
idempotency, database/request checks and invalidation after receipt edits.
"""
from __future__ import annotations

import copy
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from App.exchange import ExchangeTask, contract
from App.invoicing.invoice_service import invoice_model
from App.tests.test_invoicing_invoice_api import FULL_SELECTIONS, RECEIPT
from App.web_server import create_server

DATABASE = "local"
REQUEST = "4f2a1c8e-5b7d-4c9e-9a1b-2c3d4e5f6a7b"
BOUNDARY = "----receipt-photo-boundary"


@pytest.fixture
def server(tmp_path):
    def process(job):
        receipt = copy.deepcopy(RECEIPT)
        receipt["job_id"] = job.id
        job.json_file("receipt.json", receipt)
        return receipt

    instance = create_server("127.0.0.1", 0, tmp_path, process)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance, f"http://127.0.0.1:{instance.server_port}"
    instance.shutdown()
    instance.server_close()
    instance.store.pool.shutdown(wait=True)
    thread.join(timeout=3)


def multipart(photo=b"\xff\xd8\xff\xd9", filename="receipt.jpg"):
    body = (f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: image/jpeg\r\n\r\n").encode() + photo
    body += f"\r\n--{BOUNDARY}--\r\n".encode()
    return body, f"multipart/form-data; boundary={BOUNDARY}"


def post(url, payload=None, raw=None, content_type="application/json"):
    data = raw if raw is not None else json.dumps(payload or {}).encode()
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url)) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def create_task(base):
    status, task = post(base + "/tasks", dict(database_id=DATABASE, request_id=REQUEST))
    assert status == 201
    return task


def upload(base, task_id):
    body, content_type = multipart()
    status, task = post(f"{base}/tasks/{task_id}/photos", raw=body, content_type=content_type)
    assert status == 202
    return task


def wait_done(base, instance, job_id):
    deadline = time.time() + 10
    while time.time() < deadline:
        _, job = get(base + f"/api/jobs/{job_id}")
        if job["status"] == "done":
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def prepared_task(base, instance):
    task = upload(base, create_task(base)["task_id"])
    wait_done(base, instance, task["job_id"])
    return task


def test_result_is_202_before_confirmation(server):
    instance, base = server
    task = prepared_task(base, instance)
    status, data = get(f"{base}/tasks/{task['task_id']}/result"
                       f"?database_id={DATABASE}&request_id={REQUEST}")
    assert status == 202 and data["state"] == "review"
    status, data = get(f"{base}/tasks/{task['task_id']}/result")
    assert status == 202


def test_confirm_requires_ready_invoice_and_matching_revision(server):
    instance, base = server
    task = prepared_task(base, instance)
    status, data = post(f"{base}/tasks/{task['task_id']}/confirm", {})
    assert status == 409 and data["reasons"]
    # Save explicit links, then a stale revision from an older page is refused.
    status, model = post(f"{base}/api/jobs/{task['job_id']}/invoice/selections",
                         {"selections": FULL_SELECTIONS})
    assert status == 200 and model["ready"]
    status, data = post(f"{base}/tasks/{task['task_id']}/confirm",
                        {"revision": "0" * 64})
    assert status == 409 and "изменился" in data["error"].lower()


def test_confirm_freezes_json_1_1_and_is_idempotent(server):
    instance, base = server
    task = prepared_task(base, instance)
    status, model = post(f"{base}/api/jobs/{task['job_id']}/invoice/selections",
                         {"selections": FULL_SELECTIONS})
    assert status == 200 and model["ready"], model["blocked"]
    status, confirmed = post(f"{base}/tasks/{task['task_id']}/confirm",
                             {"revision": model["revision"]})
    assert status == 200, confirmed
    assert confirmed["state"] == "confirmed" and confirmed["result_version"] == 1
    checksum = confirmed["checksum"]
    assert len(checksum) == 64

    status, repeated = post(f"{base}/tasks/{task['task_id']}/confirm",
                            {"revision": model["revision"]})
    assert status == 200 and repeated["result_version"] == 1
    assert repeated["checksum"] == checksum and repeated["created"] is False

    status, snapshot = get(f"{base}/tasks/{task['task_id']}/result"
                           f"?database_id={DATABASE.upper()}&request_id={REQUEST.upper()}")
    assert status == 200
    assert snapshot["schema_version"] == "1.1" and snapshot["status"] == "confirmed"
    assert snapshot["task_id"] == task["task_id"]
    assert snapshot["database_id"] == DATABASE and snapshot["request_id"] == REQUEST
    assert snapshot["currency"] == "KZT" and snapshot["prices_include_vat"] is True
    assert snapshot["result_version"] == 1 and snapshot["revision"] == model["revision"]
    assert snapshot["document_uuid"] is None
    assert snapshot["source_order_number"] == "1234567890"
    assert snapshot["date"] == "16.10.2026"
    assert snapshot["total"] == model["document"]["total"]
    assert len(snapshot["items"]) == 3
    first = snapshot["items"][0]
    assert first["row_id"] == "2" and first["photo_id"] == task["job_id"]
    assert first["source"]["name"] == "Плёнка полиэтиленовая 100 мкм"
    assert first["source"]["article"] == "PL100"
    assert first["target"]["name"] == "Плёнка ПВХ 1С"
    assert first["target"]["unit"] == "м" and first["target"]["uuid"] is None
    assert first["target"]["quantity"] == "3" and first["target"]["amount"] == "1200.00"
    assert first["selection_policy"] == "explicit"
    assert second_snapshot_checksum(snapshot) == snapshot["checksum"]

    status, from_disk = get(f"{base}/tasks/{task['task_id']}")
    assert from_disk["state"] == "confirmed" and from_disk["stale_reason"] is None


def second_snapshot_checksum(snapshot):
    body = {key: value for key, value in snapshot.items() if key != "checksum"}
    import hashlib
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_foreign_database_or_request_is_refused(server):
    instance, base = server
    task = prepared_task(base, instance)
    post(f"{base}/api/jobs/{task['job_id']}/invoice/selections",
         {"selections": FULL_SELECTIONS})
    post(f"{base}/tasks/{task['task_id']}/confirm", {})
    status, data = get(f"{base}/tasks/{task['task_id']}/result?database_id=other")
    assert status == 409 and "другой" in data["error"].lower()
    status, data = get(f"{base}/tasks/{task['task_id']}/result?request_id=other")
    assert status == 409
    status, data = post(f"{base}/tasks/{task['task_id']}/confirm",
                        {"request_id": "other"})
    assert status == 409


def test_edit_makes_confirmation_stale_and_new_version_is_frozen(server):
    instance, base = server
    task = prepared_task(base, instance)
    status, model = post(f"{base}/api/jobs/{task['job_id']}/invoice/selections",
                         {"selections": FULL_SELECTIONS})
    status, confirmed = post(f"{base}/tasks/{task['task_id']}/confirm",
                             {"revision": model["revision"]})
    assert status == 200 and confirmed["result_version"] == 1

    receipt = instance.store.jobs[task["job_id"]].result
    status, edited = post(f"{base}/api/jobs/{task['job_id']}/edits",
                          {"revision": receipt["revision"], "row": 3,
                           "name": "Грунтовка 10 л улучшенная", "confirm_name": True,
                           "finalize": True})
    assert status == 200, edited
    status, state = get(f"{base}/tasks/{task['task_id']}/ui/state")
    assert state["state"] == "review" and state["stale_reason"]
    status, data = get(f"{base}/tasks/{task['task_id']}/result")
    assert status == 409 and data["state"] == "review"

    # The edited row needs a new explicit link; the old selection is stale.
    selections = copy.deepcopy(FULL_SELECTIONS)
    selections["3"]["name"] = "Грунтовка 1С Г-22"
    status, model = post(f"{base}/api/jobs/{task['job_id']}/invoice/selections",
                         {"selections": selections})
    assert status == 200 and model["ready"], model["blocked"]
    status, reconfirmed = post(f"{base}/tasks/{task['task_id']}/confirm",
                               {"revision": model["revision"]})
    assert status == 200 and reconfirmed["result_version"] == 2
    status, snapshot = get(f"{base}/tasks/{task['task_id']}/result")
    assert status == 200 and snapshot["result_version"] == 2
    assert snapshot["items"][1]["target"]["name"] == "Грунтовка 1С Г-22"
    # Version 1 is preserved on disk as evidence of the previous confirmation.
    versions = sorted(path.name for path in
                      (instance.store.root / "exchange" / task["task_id"]).glob("result-v*.json"))
    assert versions == ["result-v1.json", "result-v2.json"]


def test_confirm_unknown_task_and_invalid_body(server):
    _, base = server
    status, _ = post(f"{base}/tasks/{'0' * 32}/confirm", {})
    assert status == 404
    task = create_task(base)
    status, _ = post(f"{base}/tasks/{task['task_id']}/confirm", raw=b"{not json")
    assert status == 400
    status, _ = post(f"{base}/tasks/{task['task_id']}/confirm", {"revision": 5})
    assert status == 400


def test_snapshot_contract_maps_confirmed_fields():
    receipt = copy.deepcopy(RECEIPT)
    receipt["job_id"] = "a" * 32
    model = invoice_model(receipt, FULL_SELECTIONS)
    assert model["ready"], model["blocked"]
    task = ExchangeTask(task_id="b" * 32, database_id=DATABASE, request_id=REQUEST,
                        created_at=time.time(), job_id="a" * 32)
    snapshot = contract.build_snapshot(task, model, receipt, 7, now=1_700_000_000)
    assert snapshot["result_version"] == 7
    assert snapshot["confirmed_at"] == "2023-11-14T22:13:20Z"
    assert snapshot["vat_amount"] is None and snapshot["vat_rate"] == "16"
    assert snapshot["checksum"] == contract.checksum(snapshot)
    assert contract.input_revision(receipt, FULL_SELECTIONS) != \
        contract.input_revision(receipt, {})
    assert [item["row_id"] for item in snapshot["items"]] == ["2", "3", "4"]
    assert snapshot["items"][1]["target"]["quantity_mode"] == "factor"
    assert snapshot["items"][2]["target"]["quantity_mode"] == "service"
    assert snapshot["items"][2]["target"]["quantity_factor"] == "1"
