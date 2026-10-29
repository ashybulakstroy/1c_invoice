"""API tests for the invoice endpoints (Etap 5).

Runs the real stdlib server on an ephemeral port with a synthetic processor
that returns a fully verified electronic receipt (the Etap-1 contract).
Checks: model readiness reasons, preview vs saved selections, persistence,
PDF download with revision/token guards, 409 after a receipt edit and the
separate /api/catalog-1c search. No OCR runs here.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from App.web_server import create_server

RECEIPT = {
    "job_id": None,
    "schema_version": "torgsoft-review-1.0",
    "revision": 3,
    "filename": "IMG_0001.jpeg",
    "date": "16.10.2026",
    "order_number": "1234567890",
    "expected_total": "2250.00",
    "expected_total_source": "ocr_total_row",
    "vat_rate_percent": "16",
    "vat_rate_source": "env_file",
    "warnings": [],
    "audit_log": [],
    "rows": [
        {"row": 1, "kind": "header", "name": "МАГАЗИН", "name_raw": "МАГАЗИН"},
        {"row": 2, "kind": "product", "name": "Плёнка полиэтиленовая 100 мкм", "name_raw": "Пленка полиэтилен. 100мк",
         "article": "PL100", "catalog_key": "плёнка полиэтиленовая 100 мкм",
         "quantity": "1", "price": "1200.00", "quantity_raw": "1", "price_raw": "1200.00",
         "line_total": "1200.00", "name_origin": "catalog", "name_confirmed": True,
         "invalid_fields": [], "needs_review": False, "review_reason": None},
        {"row": 3, "kind": "product", "name": "Грунтовка 10 л", "name_raw": "Груновка 10л",
         "article": "", "catalog_key": "",
         "quantity": "5", "price": "150.00", "quantity_raw": "5", "price_raw": "150.00",
         "line_total": "750.00", "name_origin": "ocr", "name_confirmed": True,
         "invalid_fields": [], "needs_review": False, "review_reason": None},
        {"row": 4, "kind": "service", "name": "Доставка", "name_raw": "Доставка",
         "article": "", "catalog_key": "",
         "quantity": "1", "price": "300.00", "quantity_raw": "1", "price_raw": "300.00",
         "line_total": "300.00", "name_origin": "ocr", "name_confirmed": True,
         "invalid_fields": [], "needs_review": False, "review_reason": None},
        {"row": 5, "kind": "total", "name": "Итого", "name_raw": "Итого",
         "quantity": "", "price": "2250.00"},
    ],
    "calculation": {
        "status": "match",
        "validation_status": "match",
        "vat": {"status": "not_applicable", "expected_tax": None, "difference": None,
                "rate_percent": None, "rows": []},
        "products_subtotal": "1950.00",
        "services_subtotal": "300.00",
        "tax_subtotal": "0.00",
        "computed_total": "2250.00",
        "expected_total": "2250.00",
        "difference": "0.00",
        "missing_rows": [],
        "missing_original_total": False,
    },
    "finalized": True,
    "finalized_at": "2026-10-29T09:15:00+00:00",
}

FULL_SELECTIONS = {
    "2": {"name": "Плёнка ПВХ 1С", "unit": "м", "quantity": "3", "service": False,
          "catalog_id": None, "code": None},
    "3": {"name": "Грунтовка 1С Г-21", "unit": "шт", "quantity": "5", "service": False,
          "catalog_id": None, "code": None},
    "4": {"name": "Доставка 1С", "unit": "усл", "quantity": "1", "service": True,
          "catalog_id": None, "code": None},
}


@pytest.fixture
def server(tmp_path):
    def process(job):
        receipt = dict(RECEIPT)
        receipt["job_id"] = job.id
        job.json_file("receipt.json", receipt)
        return receipt

    instance = create_server("127.0.0.1", 0, tmp_path, process, max_upload=1024)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance, f"http://127.0.0.1:{instance.server_port}"
    instance.shutdown()
    instance.server_close()
    instance.store.pool.shutdown(wait=True)
    thread.join(timeout=3)


def submit_done(base, instance):
    request = urllib.request.Request(base + "/api/jobs?filename=receipt.png", data=b"image", method="POST")
    with urllib.request.urlopen(request) as response:
        job_id = json.load(response)["id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        with urllib.request.urlopen(base + f"/api/jobs/{job_id}") as response:
            state = json.load(response)
        if state["status"] == "done":
            return job_id, state
        time.sleep(0.2)
    raise AssertionError("Задание не завершилось вовремя")


def get_json(url, status=200):
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def post_json(url, payload):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def test_catalog_1c_search_matches_real_codes(server):
    _, base = server
    status, data = get_json(base + "/api/catalog-1c?q=00000019603")
    assert status == 200
    hit = data["items"][0]
    assert hit["code"] == "00000019603" and hit["name"].startswith("Бетон М350")
    assert data["errors"] == []


def test_invoice_requires_completed_job(server):
    instance, base = server
    _, done_state = submit_done(base, instance)
    job_id = done_state["id"]
    status, data = get_json(base + "/api/jobs/" + "0" * 32 + "/invoice")
    assert status == 404
    status, data = get_json(base + f"/api/jobs/{job_id}/invoice")
    assert status == 200
    assert data["ready"] is False
    assert any("Выберите номенклатуру 1С" in reason for reason in data["blocked"])
    rows = {row["source_index"]: row for row in data["generation"]["items"]}
    assert rows[0]["match_status"] == "unmatched"
    assert data["document"]["number"] == "OCR-1234567890"


def test_preview_does_not_persist(server):
    instance, base = server
    _, done_state = submit_done(base, instance)
    job_id = done_state["id"]
    status, preview = post_json(base + f"/api/jobs/{job_id}/invoice/preview",
                                {"selections": {"2": FULL_SELECTIONS["2"]}})
    assert status == 200
    manual = [row for row in preview["generation"]["items"] if row["source_index"] == 0]
    assert manual[0]["match_status"] == "manual"
    status, saved_state = get_json(base + f"/api/jobs/{job_id}/invoice")
    assert all(row["match_status"] == "unmatched" for row in saved_state["generation"]["items"])
    assert not (instance.store.jobs[job_id].directory / "invoice_state.json").exists()


def test_print_preview_uses_current_unsaved_choices(server):
    from io import BytesIO
    from pypdf import PdfReader
    instance, base = server
    job_id, _ = submit_done(base, instance)
    url = base + f"/api/jobs/{job_id}/invoice/preview-pdf"
    request = urllib.request.Request(url, data=json.dumps({"selections": FULL_SELECTIONS}).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        assert response.headers["Content-Type"] == "application/pdf"
        payload = response.read()
    text = " ".join(page.extract_text() for page in PdfReader(BytesIO(payload)).pages)
    assert "Плёнка ПВХ 1С" in text and "2 250,00" in text
    assert not (instance.store.jobs[job_id].directory / "invoice_state.json").exists()
    request = urllib.request.Request(url, data=b'{"selections":{}}', method="POST",
                                     headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(request) as response:
        assert response.status == 200 and response.read().startswith(b"%PDF")


def test_selections_persist_and_enable_pdf(server):
    instance, base = server
    _, done_state = submit_done(base, instance)
    job_id = done_state["id"]
    status, model = post_json(base + f"/api/jobs/{job_id}/invoice/selections", {"selections": FULL_SELECTIONS})
    assert status == 200
    statuses = [row["match_status"] for row in model["generation"]["items"]]
    assert statuses == ["manual", "manual", "manual"]
    assert model["ready"] is True
    assert model["blocked"] == []
    stored = json.loads((instance.store.jobs[job_id].directory / "invoice_state.json").read_text(encoding="utf-8"))
    assert stored["schema_version"] == 1 and sorted(stored["selections"]) == ["2", "3", "4"]
    # persisted state returns the same model
    status, again = get_json(base + f"/api/jobs/{job_id}/invoice")
    assert again["ready"] is True and again["token"] == model["token"]
    assert again["revision"] == model["revision"]
    # PDF needs the revision+token pair and is refused otherwise
    status, failure = get_json(base + f"/api/jobs/{job_id}/invoice.pdf?token={model['token']}")
    assert status == 409
    status, payload_bytes = urllib_data(base + f"/api/jobs/{job_id}/invoice.pdf?revision={model['revision']}&token={model['token']}")
    assert status == 200 and payload_bytes.startswith(b"%PDF") and len(payload_bytes) > 4000
    # wrong token → 409
    status, failure = get_json(base + f"/api/jobs/{job_id}/invoice.pdf?revision={model['revision']}&token=" + "0" * 64)
    assert status == 409


def test_stale_revision_after_receipt_edit(server):
    instance, base = server
    _, done_state = submit_done(base, instance)
    job_id = done_state["id"]
    status, model = post_json(base + f"/api/jobs/{job_id}/invoice/selections", {"selections": FULL_SELECTIONS})
    assert model["ready"] is True
    old_revision, old_token = model["revision"], model["token"]
    receipt = instance.store.jobs[job_id].result
    edit = {"revision": receipt["revision"], "row": 3, "quantity": "6"}
    status, data = post_json(base + f"/api/jobs/{job_id}/edits", edit)
    assert status == 200
    status, refreshed = get_json(base + f"/api/jobs/{job_id}/invoice")
    assert refreshed["finalized"] is False
    assert refreshed["ready"] is False
    assert refreshed["selections"] == {}
    assert not any("не подтверждён оператором" in reason for reason in refreshed["blocked"])
    assert refreshed["can_render"] is True
    assert refreshed["revision"] != old_revision or refreshed["token"] != old_token
    status, failure = get_json(base + f"/api/jobs/{job_id}/invoice.pdf?revision={old_revision}&token={old_token}")
    assert status == 409


def test_invalid_selection_payload_rejected(server):
    instance, base = server
    _, done_state = submit_done(base, instance)
    job_id = done_state["id"]
    status, data = post_json(base + f"/api/jobs/{job_id}/invoice/selections",
                             {"selections": {"2": {"name": "X", "unit": "шт", "quantity": "0"}}})
    assert status == 400
    status, data = post_json(base + f"/api/jobs/{job_id}/invoice/selections",
                             {"selections": {"nope": {"name": "X", "unit": "шт", "quantity": "1"}}})
    assert status == 200  # unknown rows are dropped silently, model reports unmatched


def urllib_data(url):
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_training_is_explicit_and_isolated(server, tmp_path, monkeypatch):
    from App.invoicing import invoice_service
    original = invoice_service.train_from_selections
    training_dir = tmp_path / "training"
    knowledge = tmp_path / "knowledge.json"

    def isolated(receipt, selections):
        return original(receipt, selections, training_dir=training_dir,
                        knowledge_path=knowledge)

    monkeypatch.setattr(invoice_service, "train_from_selections", isolated)
    instance, base = server
    job_id, _ = submit_done(base, instance)
    url = base + f"/api/jobs/{job_id}/invoice/train"
    status, _ = post_json(url, {"selections": FULL_SELECTIONS})
    assert status == 400 and not training_dir.exists()
    status, _ = post_json(url, {"confirm": True, "selections": {}})
    assert status == 409 and not training_dir.exists()
    receipt_file = instance.store.jobs[job_id].directory / "receipt.json"
    before = receipt_file.read_bytes()
    status, result = post_json(url, {"confirm": True, "selections": FULL_SELECTIONS})
    assert status == 200, result
    assert result["training"]["remembered"] == 3
    cases = list(training_dir.glob("case_*/expected.json"))
    assert len(cases) == 1 and knowledge.exists()
    case = json.loads(cases[0].read_text(encoding="utf-8"))
    assert case["training_ready"] and case["confirmation"]["links_checked"]
    assert receipt_file.read_bytes() == before
    status, _ = post_json(url, {"confirm": True, "selections": FULL_SELECTIONS})
    assert status == 200 and len(list(training_dir.glob("case_*/expected.json"))) == 1


def test_invoice_allocates_separate_printed_vat_without_changing_receipt():
    import copy
    from decimal import Decimal
    from App.invoicing.invoice_service import invoice_model
    receipt = copy.deepcopy(RECEIPT)
    receipt["job_id"] = "a" * 32
    receipt["expected_total"] = "2610.00"
    receipt["rows"].insert(-1, {"row": 6, "kind": "tax", "name": "НДС",
                                "quantity": "360", "price": "1", "line_total": "360"})
    receipt["calculation"]["tax_subtotal"] = "360.00"
    receipt["calculation"]["computed_total"] = "2610.00"
    receipt["calculation"]["expected_total"] = "2610.00"
    receipt["calculation"]["vat"] = {"status": "match", "expected_tax": "360",
                                        "rate_percent": "16", "rows": [6]}
    before = copy.deepcopy(receipt)
    model = invoice_model(receipt, FULL_SELECTIONS)
    assert model["ready"], model["blocked"]
    assert sum(Decimal(row["amount"]) for row in model["generation"]["items"]) == Decimal("2610")
    assert model["generation"]["vat_amount"] == "360.00"
    assert receipt == before


def test_training_failure_is_reported_and_retry_converges(server, tmp_path, monkeypatch):
    from App.invoicing import invoice_service, invoice_generation
    original_train = invoice_service.train_from_selections
    original_remember = invoice_generation.remember_selections
    training = tmp_path / "training"
    knowledge = tmp_path / "knowledge.json"
    knowledge.write_text('{}', encoding="utf-8")
    monkeypatch.setattr(invoice_service, "train_from_selections",
                        lambda receipt, selections: original_train(receipt, selections,
                            training_dir=training, knowledge_path=knowledge))
    def fail(*args, **kwargs):
        raise OSError("injected second-store failure")
    monkeypatch.setattr(invoice_generation, "remember_selections", fail)
    instance, base = server
    job_id, _ = submit_done(base, instance)
    url = base + f"/api/jobs/{job_id}/invoice/train"
    payload = {"confirm": True, "selections": FULL_SELECTIONS}
    before = (instance.store.jobs[job_id].directory / "receipt.json").read_bytes()
    status, result = post_json(url, payload)
    assert status == 500 and "error" in result
    # Document the actual partial-write behavior; do not call it atomic.
    assert len(list(training.glob("case_*/expected.json"))) == 1
    assert knowledge.read_text(encoding="utf-8") == '{}'
    monkeypatch.setattr(invoice_generation, "remember_selections", original_remember)
    status, result = post_json(url, payload)
    assert status == 200 and result["training"]["remembered"] == 3
    assert len(list(training.glob("case_*/expected.json"))) == 1
    assert len(json.loads(knowledge.read_text(encoding="utf-8"))) == 3
    assert (instance.store.jobs[job_id].directory / "receipt.json").read_bytes() == before


def test_parallel_selection_saves_are_complete_batches(server):
    from concurrent.futures import ThreadPoolExecutor
    import copy
    instance, base = server
    job_id, _ = submit_done(base, instance)
    url = base + f"/api/jobs/{job_id}/invoice/selections"
    batches = []
    for value in range(1, 7):
        selections = copy.deepcopy(FULL_SELECTIONS)
        for row in selections.values():
            row["quantity"] = str(value)
        batches.append(selections)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda selection: post_json(url, {"selections": selection}), batches))
    assert all(status == 200 for status, _ in results)
    state = json.loads((instance.store.jobs[job_id].directory / "invoice_state.json").read_text(encoding="utf-8"))
    assert state["selections"] in batches
    assert len({entry["quantity"] for entry in state["selections"].values()}) == 1


def test_unfinalized_unmapped_receipt_always_has_pdf(server):
    from io import BytesIO
    from pypdf import PdfReader
    instance, base = server
    job_id, _ = submit_done(base, instance)
    instance.store.jobs[job_id].result["finalized"] = False
    _, model = get_json(base + f"/api/jobs/{job_id}/invoice")
    assert model["can_render"] and not model["ready"]
    assert not any("финализация" in reason for reason in model["blocked"])
    status, payload = urllib_data(base + f"/api/jobs/{job_id}/invoice.pdf?revision={model['revision']}&token={model['token']}")
    assert status == 200
    text = " ".join(page.extract_text() for page in PdfReader(BytesIO(payload)).pages)
    assert "Плёнка полиэтиленовая" in text
    assert "Счёт сформирован с замечаниями" not in text
    assert "Выберите номенклатуру 1С" not in text
    assert not (instance.store.jobs[job_id].directory / "invoice_state.json").exists()
