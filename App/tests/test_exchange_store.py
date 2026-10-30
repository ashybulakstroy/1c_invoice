import json

import pytest

from App.exchange import (ExchangeConflict, ExchangeError, ExchangeNotFound, ExchangeStore,
                          task_document)

DATABASE = "alatau"
REQUEST = "4f2a1c8e-5b7d-4c9e-9a1b-2c3d4e5f6a7b"
DOCUMENT = "6a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


def test_create_is_idempotent_and_survives_restart(tmp_path):
    store = ExchangeStore(tmp_path)
    task, created = store.create(DATABASE, REQUEST)
    assert created and task.state == "waiting_photo"
    again, created_again = store.create(DATABASE, REQUEST.upper())
    assert not created_again and again.task_id == task.task_id
    restarted = ExchangeStore(tmp_path)
    assert restarted.get(task.task_id).request_id == REQUEST
    assert restarted.get(task.task_id).database_id == DATABASE


def test_document_uuid_binds_once_and_conflicts_afterwards(tmp_path):
    store = ExchangeStore(tmp_path)
    task, _ = store.create(DATABASE, REQUEST)
    assert task.document_uuid is None
    bound, created = store.create(DATABASE, REQUEST, DOCUMENT)
    assert not created and bound.document_uuid == DOCUMENT
    with pytest.raises(ExchangeConflict):
        store.create(DATABASE, REQUEST, "другой-документ")


def test_bind_job_moves_state_to_review_and_rejects_another_job(tmp_path):
    store = ExchangeStore(tmp_path)
    task, _ = store.create(DATABASE, REQUEST)
    assert store.bind_job(task.task_id, "a" * 32).state == "review"
    assert store.bind_job(task.task_id, "a" * 32).job_id == "a" * 32
    with pytest.raises(ExchangeConflict):
        store.bind_job(task.task_id, "b" * 32)
    with pytest.raises(ExchangeError):
        store.bind_job(task.task_id, "not-a-job")


def test_unknown_and_invalid_task_ids(tmp_path):
    store = ExchangeStore(tmp_path)
    with pytest.raises(ExchangeNotFound):
        store.get("0" * 32)
    with pytest.raises(ExchangeNotFound):
        store.get("../etc/passwd")


def test_create_requires_text_identifiers(tmp_path):
    store = ExchangeStore(tmp_path)
    for database, request in ((None, REQUEST), (DATABASE, ""), (DATABASE, 42)):
        with pytest.raises(ExchangeError):
            store.create(database, request)


def test_task_document_has_ui_url_and_no_secrets(tmp_path):
    store = ExchangeStore(tmp_path)
    task, _ = store.create(DATABASE, REQUEST)
    document = task_document(task, "http://192.168.1.200:8016")
    assert document["ui_url"] == f"http://192.168.1.200:8016/tasks/{task.task_id}/ui"
    assert document["state"] == "waiting_photo"
    assert json.loads(json.dumps(document))["task_id"] == task.task_id


def test_confirm_versions_result_files_and_invalidation(tmp_path):
    store = ExchangeStore(tmp_path)
    task, _ = store.create(DATABASE, REQUEST)
    store.bind_job(task.task_id, "a" * 32)
    calls = []

    def snapshot(version):
        calls.append(version)
        return {"revision": "r1", "result_version": version, "checksum": "c" * 64,
                "confirmed_at": "2026-10-30T10:00:00Z", "items": [], "total": "0.00"}

    task, created = store.confirm(task.task_id, "r1", "input-1", snapshot)
    assert created and task.result_version == 1 and task.state == "confirmed"
    assert task.confirmed_revision == "r1" and task.result["checksum"] == "c" * 64
    assert calls == [1]
    frozen = json.loads((tmp_path / task.task_id / "result-v1.json").read_text(encoding="utf-8"))
    assert frozen["checksum"] == "c" * 64

    task, created = store.confirm(task.task_id, "r1", "input-1", snapshot)
    assert not created and task.result_version == 1 and calls == [1]

    restarted = ExchangeStore(tmp_path)
    loaded = restarted.get(task.task_id)
    assert loaded.state == "confirmed" and loaded.input_revision == "input-1"
    assert restarted.load_result(loaded)["result_version"] == 1

    invalidated = restarted.invalidate_job("a" * 32, "Чек изменён")
    assert invalidated is not None and invalidated.state == "review"
    assert invalidated.stale_reason == "Чек изменён"
    assert restarted.invalidate_job("a" * 32, "ещё раз") is None
    assert restarted.for_job("a" * 32).task_id == task.task_id

    def snapshot2(version):
        calls.append(version)
        return {"revision": "r2", "result_version": version, "checksum": "d" * 64,
                "confirmed_at": "2026-10-30T10:05:00Z", "items": [], "total": "0.00"}

    task, created = restarted.confirm(task.task_id, "r2", "input-2", snapshot2)
    assert created and task.result_version == 2 and task.state == "confirmed"
    assert task.stale_reason is None and calls == [1, 2]
    assert (tmp_path / task.task_id / "result-v2.json").is_file()

    with pytest.raises(ExchangeConflict):
        restarted.confirm(task.task_id, "r3", "input-3",
                          lambda version: {"revision": "other", "checksum": "e" * 64})


def test_link_document_is_idempotent_and_survives_restart(tmp_path):
    store = ExchangeStore(tmp_path)
    task, _ = store.create(DATABASE, REQUEST)
    linked, created = store.link_document(task.task_id, DOCUMENT)
    assert created and linked.document_uuid == DOCUMENT
    same, created = store.link_document(task.task_id, DOCUMENT.upper())
    assert not created and same.document_uuid == DOCUMENT
    with pytest.raises(ExchangeConflict):
        store.link_document(task.task_id, "другой-документ")
    with pytest.raises(ExchangeError):
        store.link_document(task.task_id, "")

    restarted = ExchangeStore(tmp_path)
    assert restarted.get(task.task_id).document_uuid == DOCUMENT


def test_applied_receipt_is_idempotent_and_restores_after_restart(tmp_path):
    store = ExchangeStore(tmp_path)
    task, _ = store.create(DATABASE, REQUEST)
    store.bind_job(task.task_id, "a" * 32)
    task, _ = store.confirm(
        task.task_id, "r1", "input-1",
        lambda version: {"revision": "r1", "result_version": version,
                         "checksum": "c" * 64,
                         "confirmed_at": "2026-10-30T10:00:00Z",
                         "items": [], "total": "0.00"})
    receipt = {"operation_id": "op-1", "fingerprint": "f" * 64, "status": "applied",
               "document_uuid": DOCUMENT, "result_version": 1, "checksum": "c" * 64,
               "received_at": "2026-10-30T10:01:00Z"}
    task, created = store.add_receipt(task.task_id, receipt)
    assert created and task.state == "applied" and task.document_uuid == DOCUMENT
    assert task_document(task)["applied"] is True
    same, created = store.add_receipt(task.task_id, dict(receipt))
    assert not created and len(same.receipts) == 1
    with pytest.raises(ExchangeConflict):
        store.add_receipt(task.task_id, dict(receipt, fingerprint="d" * 64,
                                             checksum="d" * 64))
    with pytest.raises(ExchangeConflict):
        store.add_receipt(task.task_id, dict(receipt, operation_id="op-2"))
    with pytest.raises(ExchangeConflict):
        store.add_receipt(task.task_id, dict(receipt, operation_id="op-2",
                                             document_uuid="другой-документ"))
    linked, _ = store.create(DATABASE, "another-request")
    store.link_document(linked.task_id, DOCUMENT)
    with pytest.raises(ExchangeConflict):
        store.add_receipt(linked.task_id, dict(receipt, operation_id="op-4",
                                               document_uuid="другой-документ"))
    with pytest.raises(ExchangeError):
        store.add_receipt(task.task_id, dict(receipt, operation_id="op-3",
                                             status="imported"))

    restarted = ExchangeStore(tmp_path)
    loaded = restarted.get(task.task_id)
    assert loaded.state == "applied" and loaded.applied["operation_id"] == "op-1"
    assert loaded.document_uuid == DOCUMENT and loaded.applied["checksum"] == "c" * 64
    assert restarted.invalidate_job("a" * 32, "Чек изменён") is None
    assert loaded.stale_reason is None


def test_error_receipt_does_not_apply_or_bind_document(tmp_path):
    store = ExchangeStore(tmp_path)
    task, _ = store.create(DATABASE, REQUEST)
    error = {"operation_id": "err-1", "fingerprint": "e" * 64, "status": "error",
             "message": "Не удалось записать"}
    task, created = store.add_receipt(task.task_id, error)
    assert created and task.state == "waiting_photo" and task.applied is None
    assert task.document_uuid is None and task.receipts[0]["message"] == "Не удалось записать"
    with pytest.raises(ExchangeConflict):
        store.add_receipt(task.task_id, dict(error, fingerprint="f" * 64,
                                             message="Другая ошибка"))
    assert len(ExchangeStore(tmp_path).get(task.task_id).receipts) == 1
