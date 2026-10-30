import json
import threading
import urllib.error
import urllib.request

import pytest

from App.web_server import create_server

DATABASE = "alatau"
REQUEST = "4f2a1c8e-5b7d-4c9e-9a1b-2c3d4e5f6a7b"
BOUNDARY = "----receipt-photo-boundary"


@pytest.fixture
def server(tmp_path):
    def process(job):
        job.phase("geometry", 20, "geometry")
        return dict(rows=[], product_count=0)

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


def create_task(base):
    request = urllib.request.Request(
        base + "/tasks", data=json.dumps(dict(database_id=DATABASE, request_id=REQUEST)).encode(),
        method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        assert response.status == 201
        return json.load(response)


def upload(base, task_id, photo=None):
    body, content_type = multipart() if photo is None else multipart(photo)
    request = urllib.request.Request(f"{base}/tasks/{task_id}/photos", data=body, method="POST",
                                     headers={"Content-Type": content_type})
    return urllib.request.urlopen(request)


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url))


def error_code(action):
    with pytest.raises(urllib.error.HTTPError) as error:
        action()
    return error.value.code, json.loads(error.value.read().decode())


def test_photo_upload_binds_task_to_job(server):
    instance, base = server
    task = create_task(base)
    with upload(base, task["task_id"]) as response:
        assert response.status == 202
        document = json.load(response)
    assert document["job_id"] and len(document["job_id"]) == 32
    assert document["state"] == "review"
    job = instance.store.get(document["job_id"])
    assert job is not None and job.filename == "receipt.jpg"
    with get(base + "/tasks/" + task["task_id"]) as response:
        stored = json.load(response)
    assert stored["job_id"] == document["job_id"]


def test_second_photo_for_same_task_is_rejected(server):
    _, base = server
    task = create_task(base)
    with upload(base, task["task_id"]):
        pass
    code, body = error_code(lambda: upload(base, task["task_id"], b"\xff\xd8other"))
    assert code == 409 and "фото" in body["error"].lower()


def test_photo_upload_validates_request(server):
    _, base = server
    task = create_task(base)
    code, _ = error_code(lambda: get_upload(base, task["task_id"], b"not multipart", "text/plain"))
    assert code == 400
    code, _ = error_code(lambda: get_upload(base, task["task_id"], b"", "multipart/form-data; boundary=x"))
    assert code == 400
    code, _ = error_code(lambda: upload(base, "0" * 32))
    assert code == 404


def get_upload(base, task_id, body, content_type):
    request = urllib.request.Request(f"{base}/tasks/{task_id}/photos", data=body, method="POST",
                                     headers={"Content-Type": content_type})
    return urllib.request.urlopen(request)


def test_task_page_is_open_and_restores_job(server):
    _, base = server
    task = create_task(base)
    with get(task["ui_url"]) as response:
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("text/html")
        html = response.read().decode("utf-8")
    assert "/invoice.js" in html
    assert 'id="invoice-confirm"' in html
    with get(f"{base}/tasks/{task['task_id']}/ui/state") as response:
        state = json.load(response)
    assert state["task_id"] == task["task_id"] and state["job_id"] is None
    with upload(base, task["task_id"]):
        pass
    with get(f"{base}/tasks/{task['task_id']}/ui/state") as response:
        state = json.load(response)
    assert state["state"] == "review" and state["job_id"]


def test_unknown_task_page_reports_404(server):
    _, base = server
    code, _ = error_code(lambda: get(base + "/tasks/" + "0" * 32 + "/ui/state"))
    assert code == 404
