"""Regression tests for sessions disappearing after an Amvera deployment.

No real production data: all test sessions live in pytest tmp_path.
The public /data mount is replaced by a simulated persisted mount.
"""
import os
import uuid
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import storage_paths


@pytest.fixture
def amvera_volume(tmp_path, monkeypatch):
    persistent = tmp_path / "volume" / "data"
    persistent.mkdir(parents=True)
    app_a = tmp_path / "deployment_a"
    app_b = tmp_path / "deployment_b"
    app_a.mkdir()
    app_b.mkdir()
    # Under the old code, absent DATA_DIR used ./data, hence the next
    # client could not find the session after moving to another /app.
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(storage_paths, "DEFAULT_DATA_DIR", persistent)
    real_ismount = os.path.ismount
    monkeypatch.setattr(
        storage_paths.os.path, "ismount",
        lambda path: Path(path) == persistent or real_ismount(path),
    )
    return persistent, app_a, app_b


def test_session_and_raw_survive_new_process_working_directory(amvera_volume, monkeypatch):
    persistent, before, after = amvera_volume
    monkeypatch.chdir(before)
    client = TestClient(app)
    created = client.post("/sessions", json={
        "request_id": "stable-draft-id-34", "initial_text": "ЛИЧНЫЙ RAW. Ни слова не терять."
    })
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    session_path = f"/sessions/{sid}"
    assert (persistent / "sessions" / sid / "сессия.json").is_file()
    assert (persistent / "sessions" / sid / "raw.txt").is_file()
    assert not (before / "data").exists()
    question = client.post(session_path + "/advance", json={"command": "подтверждаю"})
    assert question.status_code == 200, question.text
    raw2 = client.post(session_path + "/raw", json={
        "event_id": "more-1", "text": "Второй фрагмент неизменён."
    })
    assert raw2.status_code == 200, raw2.text
    del client

    monkeypatch.chdir(after)
    client_new = TestClient(app)
    assert client_new.get("/health").json()["storage"]["data_root"] == str(persistent)
    status = client_new.get(session_path)
    assert status.status_code == 200, status.text
    assert status.json()["этап"] == "вопросы"
    assert status.json()["источников"] == 2
    replay = client_new.post("/sessions", json={
        "request_id": "stable-draft-id-34", "initial_text": "ЛИЧНЫЙ RAW. Ни слова не терять."
    })
    assert replay.status_code == 200 and replay.json()["session_id"] == sid
    raw = client_new.get(session_path + "/raw")
    assert raw.status_code == 200
    assert "Второй фрагмент неизменён." in raw.json()["raw"]
    assert "ЛИЧНЫЙ RAW. Ни слова не терять." in raw.json()["raw"]
    assert not (after / "data").exists()
    assert not (after / "sessions").exists()


def test_missing_mount_fails_before_claiming_success(amvera_volume, monkeypatch):
    persistent, _, _ = amvera_volume
    monkeypatch.setattr(storage_paths.os.path, "ismount", lambda p: False)
    client = TestClient(app)
    for method, url, payload in [
        ("GET", "/health", None),
        ("POST", "/sessions", {"request_id": "must-not-be-created", "initial_text": "raw"}),
    ]:
        response = client.request(method, url, json=payload)
        assert response.status_code == 503, response.text
        assert "STORAGE_NOT_MOUNTED" in response.text
    assert not (persistent / "sessions").exists()
    assert not (persistent / ".session_namespace").exists()


@pytest.mark.parametrize("wrong_path", ["./data", "data", "/app/data", "/app"])
def test_unsafe_storage_configuration_is_rejected(tmp_path, monkeypatch, wrong_path):
    monkeypatch.setenv("DATA_DIR", wrong_path)
    response = TestClient(app).post("/sessions", json={
        "request_id": "bad-configuration", "initial_text": "source"
    })
    assert response.status_code == 503, response.text
    assert "STORAGE_MISCONFIGURED" in response.text
    assert not (tmp_path / "sessions").exists()


def test_unknown_session_lookup_does_not_create_phantom_files(amvera_volume):
    persistent, _, _ = amvera_volume
    sid = str(uuid.uuid4())
    missing = TestClient(app).get(f"/sessions/{sid}")
    assert missing.status_code == 404
    assert "SESSION_NOT_FOUND" in missing.text
    assert not (persistent / "sessions" / sid).exists()


def test_missing_metadata_keeps_existing_raw_for_recovery(amvera_volume):
    persistent, _, _ = amvera_volume
    sid = str(uuid.uuid4())
    folder = persistent / "sessions" / sid
    folder.mkdir(parents=True)
    (folder / "raw.txt").write_text("ВАЖНЫЙ КАНОН", encoding="utf-8")
    response = TestClient(app).get(f"/sessions/{sid}")
    assert response.status_code == 503, response.text
    assert "SESSION_METADATA_MISSING" in response.text
    assert (folder / "raw.txt").read_text(encoding="utf-8") == "ВАЖНЫЙ КАНОН"
    assert not (folder / ".lock").exists()
