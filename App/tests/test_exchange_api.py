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

    instance = create_server("127.0.0.1", 0, tmp_path, process)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance, f"http://127.0.0.1:{instance.server_port}"
    instance.shutdown()
    instance.server_close()
    instance.store.pool.shutdown(wait=True)
    thread.join(timeout=3)


def post(url, payload):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(request)


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url))


def error_code(action):
    with pytest.raises(urllib.error.HTTPError) as error:
        action()
    return error.value.code, json.loads(error.value.read().decode())


def test_exchange_is_open_in_trusted_network(server):
    _, base = server
    with post(base + "/tasks", dict(database_id=DATABASE, request_id=REQUEST)) as response:
        assert response.status == 201
    code, _ = error_code(lambda: get(base + "/tasks/" + "0" * 32))
    assert code == 404


def test_create_task_is_idempotent_and_has_ui_url(server):
    _, base = server
    with post(base + "/tasks", dict(database_id=DATABASE, request_id=REQUEST)) as response:
        assert response.status == 201
        created = json.load(response)
    assert created["state"] == "waiting_photo"
    assert created["task_id"] and len(created["task_id"]) == 32
    assert created["ui_url"].endswith(f"/tasks/{created['task_id']}/ui")
    with post(base + "/tasks", dict(database_id=DATABASE, request_id=REQUEST.upper())) as response:
        assert response.status == 200
        repeated = json.load(response)
    assert repeated["task_id"] == created["task_id"]
    with get(base + "/tasks/" + created["task_id"]) as response:
        document = json.load(response)
    assert document["state"] == "waiting_photo" and document["result_version"] == 0


def test_document_uuid_conflict_and_validation(server):
    _, base = server
    first = "6a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
    with post(base + "/tasks", dict(database_id=DATABASE, request_id=REQUEST, document_uuid=first)):
        pass
    code, _ = error_code(lambda: post(base + "/tasks",
                                      dict(database_id=DATABASE, request_id=REQUEST,
                                           document_uuid="другой-документ")))
    assert code == 409
    code, _ = error_code(lambda: post(base + "/tasks", dict(database_id=DATABASE)))
    assert code == 400
    request = urllib.request.Request(base + "/tasks", data=b"{not json", method="POST",
                                     headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 400


def test_unknown_task_and_health_is_open(server):
    _, base = server
    code, _ = error_code(lambda: get(base + "/tasks/" + "0" * 32))
    assert code == 404
    with get(base + "/api/health") as response:
        health = json.load(response)
    assert health["ok"] and health["exchange"] is True
