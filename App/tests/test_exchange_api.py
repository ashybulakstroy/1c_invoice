import json
import threading
import urllib.error
import urllib.request

import pytest

from App.web_server import create_server

DATABASE = "alatau"
REQUEST = "4f2a1c8e-5b7d-4c9e-9a1b-2c3d4e5f6a7b"


@pytest.fixture
def server(tmp_path):
    def process(job):
        return dict(rows=[], product_count=0)

    key_path = tmp_path / "network_api_key.txt"
    instance = create_server("127.0.0.1", 0, tmp_path, process,
                             exchange_key_path=key_path)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance, f"http://127.0.0.1:{instance.server_port}", key_path.read_text(encoding="utf-8").strip()
    instance.shutdown()
    instance.server_close()
    instance.store.pool.shutdown(wait=True)
    thread.join(timeout=3)


def post(url, payload, key=None):
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["X-API-Key"] = key
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers=headers)
    return urllib.request.urlopen(request)


def get(url, key=None):
    headers = {}
    if key is not None:
        headers["X-API-Key"] = key
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers))


def error_code(action):
    with pytest.raises(urllib.error.HTTPError) as error:
        action()
    return error.value.code, json.loads(error.value.read().decode())


def test_exchange_requires_key(server):
    _, base, key = server
    code, body = error_code(lambda: post(base + "/tasks", dict(database_id=DATABASE, request_id=REQUEST)))
    assert code == 401 and "ключ" in body["error"].lower()
    code, _ = error_code(lambda: get(base + "/tasks/" + "0" * 32))
    assert code == 401


def test_create_task_is_idempotent_and_has_ui_url(server):
    _, base, key = server
    with post(base + "/tasks", dict(database_id=DATABASE, request_id=REQUEST), key) as response:
        assert response.status == 201
        created = json.load(response)
    assert created["state"] == "waiting_photo"
    assert created["task_id"] and len(created["task_id"]) == 32
    assert created["ui_url"].endswith(f"/tasks/{created['task_id']}/ui")
    assert key not in json.dumps(created)
    with post(base + "/tasks", dict(database_id=DATABASE, request_id=REQUEST.upper()), key) as response:
        assert response.status == 200
        repeated = json.load(response)
    assert repeated["task_id"] == created["task_id"]
    with get(base + "/tasks/" + created["task_id"], key) as response:
        document = json.load(response)
    assert document["state"] == "waiting_photo" and document["result_version"] == 0


def test_document_uuid_conflict_and_validation(server):
    _, base, key = server
    first = "6a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
    with post(base + "/tasks", dict(database_id=DATABASE, request_id=REQUEST, document_uuid=first), key):
        pass
    code, body = error_code(lambda: post(base + "/tasks",
                                         dict(database_id=DATABASE, request_id=REQUEST,
                                              document_uuid="другой-документ"), key))
    assert code == 409
    code, body = error_code(lambda: post(base + "/tasks", dict(database_id=DATABASE), key))
    assert code == 400
    request = urllib.request.Request(base + "/tasks", data=b"{not json", method="POST",
                                     headers={"X-API-Key": key, "Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 400


def test_unknown_task_and_health_is_open(server):
    _, base, key = server
    code, _ = error_code(lambda: get(base + "/tasks/" + "0" * 32, key))
    assert code == 404
    with get(base + "/api/health") as response:
        health = json.load(response)
    assert health["ok"] and health["exchange"] is True
