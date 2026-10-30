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
