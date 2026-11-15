import importlib
from pathlib import Path

import pytest

SAMPLES = Path(__file__).parent.parent / "samples"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CLERKAI_LLM", "offline")
    monkeypatch.setenv("CLERKAI_DB", str(tmp_path / "api.db"))
    from fastapi.testclient import TestClient

    import clerkai.api as api

    importlib.reload(api)
    return TestClient(api.app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "llm": "offline-rules"}


def test_process_text_and_stats(client):
    text = (SAMPLES / "01_invoice_overdue.txt").read_text()
    r = client.post("/process", json={"text": text, "source": "inv"})
    assert r.status_code == 200
    assert r.json()["extraction"]["doc_type"] == "invoice"
    assert client.get("/stats").json()["runs"] == 1


def test_upload_file_reaches_review_queue(client):
    data = (SAMPLES / "04_ato_notice.txt").read_bytes()
    r = client.post("/process/file", files={"file": ("ato.txt", data, "text/plain")})
    assert r.status_code == 200 and r.json()["decision"]["team"] == "Tax"
    assert client.get("/review-queue").json()[0]["source"] == "ato.txt"


def test_unsupported_file_type_rejected(client):
    r = client.post("/process/file", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415
