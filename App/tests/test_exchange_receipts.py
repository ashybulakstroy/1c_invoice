"""Document links, receipts and XML output (MVP-3 / M4).

Runs the real server with a synthetic verified receipt: confirm → link the
recorded 1C document → send an ``applied``/``error`` receipt → read the frozen
result as JSON and XML. Checks idempotency, foreign identifiers, malformed
bodies and the terminal state after an invoice was recorded in 1C.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import pytest

from App.exchange import contract
from App.tests.test_exchange_confirm import (DATABASE, REQUEST, create_task,
                                             get, post, prepared_task, upload,
                                             wait_done)
from App.tests.test_invoicing_invoice_api import FULL_SELECTIONS, RECEIPT
from App.web_server import create_server

DOCUMENT = "6a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
OTHER_DOCUMENT = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
OPERATION = "9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a"
OTHER_OPERATION = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
SECOND_REQUEST = "5e6f7a8b-9c0d-4e1f-8a2b-3c4d5e6f7a8b"


@pytest.fixture
def server(tmp_path):
    def process(job):
        receipt = dict(RECEIPT)
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


def fetch(url):
    """GET returning ``(status, content type, raw body)`` even for errors."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url)) as response:
            return response.status, response.headers.get_content_type(), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get_content_type(), error.read()


def confirmed_task(base, instance, request=REQUEST):
    if request == REQUEST:
        task = prepared_task(base, instance)
    else:
        status, created = post(base + "/tasks", dict(database_id=DATABASE,
                                                    request_id=request))
        assert status == 201, created
        task = upload(base, created["task_id"])
        wait_done(base, instance, task["job_id"])
    status, model = post(f"{base}/api/jobs/{task['job_id']}/invoice/selections",
                         {"selections": FULL_SELECTIONS})
    assert status == 200 and model["ready"], model["blocked"]
    status, confirmed = post(f"{base}/tasks/{task['task_id']}/confirm",
                             {"revision": model["revision"]})
    assert status == 200, confirmed
    return task, model, confirmed


def receipt_payload(confirmed, **overrides):
    payload = {
        "database_id": DATABASE,
        "request_id": REQUEST,
        "operation_id": OPERATION,
        "status": "applied",
        "result_version": confirmed["result_version"],
        "checksum": confirmed["checksum"],
        "document_uuid": DOCUMENT,
        "document_number": "РТ-000123",
        "stock_warnings": [],
    }
    payload.update(overrides)
    return payload


def test_document_link_binds_once_and_keeps_confirmation(server):
    instance, base = server
    task, _, confirmed = confirmed_task(base, instance)
    url = f"{base}/tasks/{task['task_id']}/document-link"

    status, data = post(url, {"database_id": DATABASE, "request_id": REQUEST,
                              "document_uuid": DOCUMENT})
    assert status == 200 and data["linked"] is True
    assert data["document_uuid"] == DOCUMENT
    assert data["state"] == "confirmed"
    assert data["result_version"] == confirmed["result_version"]

    status, again = post(url, {"document_uuid": DOCUMENT.upper()})
    assert status == 200 and again["linked"] is False
    assert again["document_uuid"] == DOCUMENT

    status, conflict = post(url, {"document_uuid": OTHER_DOCUMENT})
    assert status == 409 and "друг" in conflict["error"].lower()
    status, _ = post(url, {"database_id": "other", "document_uuid": DOCUMENT})
    assert status == 409
    status, _ = post(url, {"request_id": "other", "document_uuid": DOCUMENT})
    assert status == 409
    status, _ = post(url, {})
    assert status == 400
    status, _ = post(f"{base}/tasks/{'0' * 32}/document-link",
                     {"document_uuid": DOCUMENT})
    assert status == 404

    status, state = get(f"{base}/tasks/{task['task_id']}")
    assert status == 200 and state["document_uuid"] == DOCUMENT


def test_applied_receipt_marks_task_and_is_idempotent(server):
    instance, base = server
    task, _, confirmed = confirmed_task(base, instance)
    url = f"{base}/tasks/{task['task_id']}/import-receipt"
    result_url = f"{base}/tasks/{task['task_id']}/result"

    payload = receipt_payload(confirmed)
    status, data = post(url, payload)
    assert status == 200
    assert data["state"] == "applied" and data["applied"] is True
    assert data["document_uuid"] == DOCUMENT
    assert data["created"] is True and data["receipts"] == 1
    assert data["receipt_status"] == "applied"
    assert data["operation_id"] == OPERATION

    status, repeated = post(url, payload)
    assert status == 200 and repeated["created"] is False
    assert repeated["receipts"] == 1 and repeated["state"] == "applied"

    status, conflict = post(url, dict(payload, document_number="РТ-999"))
    assert status == 409 and "operation_id" in conflict["error"]
    status, conflict = post(url, receipt_payload(confirmed, operation_id=OTHER_OPERATION))
    assert status == 409 and "другой операцией" in conflict["error"]

    status, state = get(f"{base}/tasks/{task['task_id']}/ui/state")
    assert status == 200 and state["state"] == "applied"
    assert state["applied"] is True and state["receipts"] == 1
    status, state = get(f"{base}/tasks/{task['task_id']}")
    assert status == 200 and state["document_uuid"] == DOCUMENT

    # The frozen snapshot stays available after the document was recorded.
    status, snapshot = get(result_url)
    assert status == 200 and snapshot["checksum"] == confirmed["checksum"]
    assert snapshot["result_version"] == confirmed["result_version"]


def test_receipt_validation_before_and_after_confirmation(server):
    instance, base = server
    unconfirmed = prepared_task(base, instance)
    url = f"{base}/tasks/{unconfirmed['task_id']}/import-receipt"
    payload = {"database_id": DATABASE, "request_id": REQUEST,
               "operation_id": OPERATION, "status": "applied",
               "result_version": 1, "checksum": "0" * 64,
               "document_uuid": DOCUMENT}
    status, data = post(url, payload)
    assert status == 409 and "не подтверждён" in data["error"].lower()

    task, _, confirmed = confirmed_task(base, instance, SECOND_REQUEST)
    url = f"{base}/tasks/{task['task_id']}/import-receipt"
    base_payload = receipt_payload(confirmed)
    base_payload["request_id"] = SECOND_REQUEST
    cases = [
        (dict(base_payload, result_version=confirmed["result_version"] + 1), 409),
        (dict(base_payload, checksum="0" * 64), 409),
        (dict(base_payload, database_id="other"), 409),
        (dict(base_payload, request_id="other"), 409),
        (dict(base_payload, status="imported"), 400),
        ({key: value for key, value in base_payload.items() if key != "operation_id"}, 400),
        ({key: value for key, value in base_payload.items() if key != "result_version"}, 400),
        ({key: value for key, value in base_payload.items() if key != "checksum"}, 400),
        ({key: value for key, value in base_payload.items() if key != "document_uuid"}, 400),
    ]
    for body, expected in cases:
        status, _ = post(url, body)
        assert status == expected, body
    status, _ = post(url, raw=b"{not json")
    assert status == 400
    status, _ = post(url, raw=b"[]")
    assert status == 400
    status, _ = post(f"{base}/tasks/{'0' * 32}/import-receipt", base_payload)
    assert status == 404

    status, state = get(f"{base}/tasks/{task['task_id']}")
    assert status == 200 and state["state"] == "confirmed"
    assert state["receipts"] == 0 and state["applied"] is False


def test_error_receipt_is_stored_without_applying(server):
    instance, base = server
    task, _, confirmed = confirmed_task(base, instance)
    url = f"{base}/tasks/{task['task_id']}/import-receipt"
    error = {"database_id": DATABASE, "request_id": REQUEST,
             "operation_id": OTHER_OPERATION, "status": "error",
             "message": "Запись отменена оператором"}

    status, data = post(url, error)
    assert status == 200 and data["state"] == "confirmed"
    assert data["applied"] is False and data["receipts"] == 1
    assert data["document_uuid"] is None and data["receipt_status"] == "error"

    status, repeated = post(url, error)
    assert status == 200 and repeated["created"] is False and repeated["receipts"] == 1
    status, _ = post(url, dict(error, message="Другая ошибка"))
    assert status == 409

    status, data = post(url, receipt_payload(confirmed))
    assert status == 200 and data["state"] == "applied"
    assert data["receipts"] == 2 and data["applied"] is True


def test_applied_task_is_terminal_for_confirmation(server):
    instance, base = server
    task, _, confirmed = confirmed_task(base, instance)
    url = f"{base}/tasks/{task['task_id']}/import-receipt"
    status, _ = post(url, receipt_payload(confirmed))
    assert status == 200

    status, data = post(f"{base}/tasks/{task['task_id']}/confirm",
                        {"revision": confirmed["revision"]})
    assert status == 409 and "применён" in data["error"].lower()

    receipt = instance.store.jobs[task["job_id"]].result
    status, edited = post(f"{base}/api/jobs/{task['job_id']}/edits",
                          {"revision": receipt["revision"], "row": 3,
                           "name": "Грунтовка 10 л улучшенная",
                           "confirm_name": True, "finalize": True})
    assert status == 200, edited
    status, state = get(f"{base}/tasks/{task['task_id']}")
    assert status == 200 and state["state"] == "applied"
    assert state["stale_reason"] is None
    status, snapshot = get(f"{base}/tasks/{task['task_id']}/result")
    assert status == 200 and snapshot["result_version"] == confirmed["result_version"]


def test_result_xml_matches_frozen_json(server):
    instance, base = server
    task, _, confirmed = confirmed_task(base, instance)
    url = (f"{base}/tasks/{task['task_id']}/result.xml"
           f"?database_id={DATABASE}&request_id={REQUEST}")
    status, content_type, body = fetch(url)
    assert status == 200 and content_type == "application/xml"
    root = ET.fromstring(body)
    assert root.tag == "TorgsoftInvoice" and root.get("schemaVersion") == "1.1"
    assert root.findtext("status") == "confirmed"
    assert root.findtext("task_id") == task["task_id"]
    assert root.findtext("checksum") == confirmed["checksum"]
    assert root.findtext("result_version") == str(confirmed["result_version"])
    assert root.findtext("currency") == "KZT"
    assert root.findtext("prices_include_vat") == "true"
    items = root.findall("./items/item")
    assert len(items) == 3
    assert items[0].findtext("row_id") == "2"
    assert items[0].findtext("source/name") == "Плёнка полиэтиленовая 100 мкм"
    assert items[0].findtext("source/article") == "PL100"
    assert items[0].findtext("target/name") == "Плёнка ПВХ 1С"
    assert items[0].findtext("target/unit") == "м"
    assert items[0].findtext("target/quantity") == "3"
    assert items[0].findtext("target/amount") == "1200.00"

    status, snapshot = get(f"{base}/tasks/{task['task_id']}/result")
    assert status == 200 and root.findtext("total") == snapshot["total"]


def test_result_xml_status_codes_and_foreign_identifiers(server):
    instance, base = server
    empty = create_task(base)
    url = f"{base}/tasks/{empty['task_id']}/result.xml"
    status, content_type, body = fetch(url)
    assert status == 202 and content_type == "application/json"
    assert json.loads(body)["state"] == "waiting_photo"
    url = f"{base}/tasks/{empty['task_id']}/result.xml?database_id=other"
    status, _, body = fetch(url)
    assert status == 409 and "другой" in json.loads(body)["error"].lower()
    status, _, _ = fetch(f"{base}/tasks/{'0' * 32}/result.xml")
    assert status == 404

    task, _, _ = confirmed_task(base, instance, SECOND_REQUEST)
    receipt = instance.store.jobs[task["job_id"]].result
    status, _ = post(f"{base}/api/jobs/{task['job_id']}/edits",
                     {"revision": receipt["revision"], "expected_total": "2250.00"})
    assert status == 200
    url = f"{base}/tasks/{task['task_id']}/result.xml"
    status, content_type, body = fetch(url)
    assert status == 200 and content_type == "application/xml"
    assert ET.fromstring(body).findtext("result_version") == "2"


def test_xml_conditions_and_fingerprint_are_canonical():
    snapshot = {"schema_version": "1.1", "status": "confirmed",
                "items": [{"row_id": "1", "allowed_targets": [
                    {"code": "0001", "conditions": {"unit": "кг", "factor": "2"}}]}]}
    snapshot["checksum"] = contract.checksum(snapshot)
    root = ET.fromstring(contract.to_xml(snapshot))
    conditions = root.find("./items/item/allowed_targets/item/conditions")
    assert json.loads(conditions.text) == {"factor": "2", "unit": "кг"}
    assert root.findtext("checksum") == snapshot["checksum"]
    assert contract.fingerprint({"a": 1, "b": "я"}) == \
        contract.fingerprint({"b": "я", "a": 1})
    assert contract.fingerprint({"a": 1, "b": "я"}) != \
        contract.fingerprint({"a": 1, "b": "я", "c": 0})
