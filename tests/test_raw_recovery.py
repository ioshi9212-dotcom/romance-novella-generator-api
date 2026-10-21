"""Regression tests: a full original TXT must replace PLACEHOLDER without losing other RAW."""
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return TestClient(app)


def make_text(byte_count=113600):
    # Russian UTF-8 plus exact byte count; never truncate a multibyte character.
    prefix = "По ту сторону Аверна. Рината и Сайлас.\n"
    raw = prefix.encode("utf-8")
    return (raw + b"x" * (byte_count - len(raw))).decode("utf-8")


def create_placeholder(api):
    response = api.post("/sessions", json={"request_id": "restore-source-test", "initial_text": ""})
    assert response.status_code == 200, response.text
    sid = response.json()["session_id"]
    # Simulate an older persisted session: newest backend forbids creating placeholders.
    from app.main import atomic_json, session_dir, source_digest, RawPart
    import uuid
    folder = session_dir(uuid.UUID(sid))
    dummy = RawPart(event_id="initial", text="PLACEHOLDER")
    receipt = source_digest(dummy)
    (folder / "raw.txt").write_text(
        f"\n===== RAW initial {receipt} =====\nPLACEHOLDER\n===== END RAW initial =====\n",
        encoding="utf-8",
    )
    meta = __import__("json").loads((folder / "сессия.json").read_text(encoding="utf-8"))
    meta["_raw_receipts"]["initial"] = receipt
    meta["_initial_text_digest"] = hashlib.sha256(b"PLACEHOLDER").hexdigest()
    atomic_json(folder / "сессия.json", meta)
    return sid


def file_payload(text, event_id=None, expected_bytes=None):
    payload = {
        "openaiFileIdRefs": [{"name": "novel.txt", "id": "file-test", "download_link": "https://files.oaiusercontent.com/file-test"}],
        "expected_bytes": len(text.encode("utf-8")) if expected_bytes is None else expected_bytes,
        "expected_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    if event_id:
        payload["event_id"] = event_id
    return payload


def test_placeholder_is_rejected_for_new_sessions_and_raw(api):
    assert api.post("/sessions", json={"request_id": "forbidden", "initial_text": "PLACEHOLDER"}).status_code == 422
    sid = api.post("/sessions", json={"request_id": "regular", "initial_text": ""}).json()["session_id"]
    assert api.post(f"/sessions/{sid}/raw", json={"event_id": "bad", "text": "PLACEHOLDER"}).status_code == 422


def test_restore_exact_original_and_preserve_neighbor(api, monkeypatch):
    sid = create_placeholder(api)
    original = make_text()
    assert len(original.encode("utf-8")) == 113600
    # A second, valid old raw entry must survive unchanged.
    from app.main import atomic_json, session_dir, source_digest, RawPart
    import uuid, json
    folder = session_dir(uuid.UUID(sid))
    meta = json.loads((folder / "сессия.json").read_text(encoding="utf-8"))
    extra = RawPart(event_id="note", text="Уже сохранённое примечание.")
    digest = source_digest(extra)
    with (folder / "raw.txt").open("a", encoding="utf-8") as out:
        out.write(f"\n===== RAW note {digest} =====\n{extra.text}\n===== END RAW note =====\n")
    meta["_raw_receipts"]["note"] = digest
    atomic_json(folder / "сессия.json", meta)
    before_note = (folder / "raw.txt").read_text(encoding="utf-8").split("\n===== RAW note ")[1]
    monkeypatch.setattr("app.main.fetch_openai_file", lambda refs: (
        original, "novel.txt", 113600, hashlib.sha256(original.encode("utf-8")).hexdigest()
    ))
    # The session may already be in review; no new session or stage rollback.
    for command in ("подтверждаю", "вопросов_больше_нет", "подтверждаю"):
        response = api.post(f"/sessions/{sid}/advance", json={"command": command})
        assert response.status_code == 200, response.text
    url = f"/sessions/{sid}/raw/repair-file"
    recovered = api.post(url, json=file_payload(original))
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["status"] == "restored_review_required"
    assert recovered.json()["bytes"] == 113600
    assert recovered.json()["sha256"] == hashlib.sha256(original.encode("utf-8")).hexdigest()
    raw = (folder / "raw.txt").read_text(encoding="utf-8")
    assert original in raw
    assert "PLACEHOLDER" not in raw
    assert raw.split("\n===== RAW note ")[1] == before_note
    assert api.get(f"/sessions/{sid}").json()["этап"] == "запись_и_сверка"
    again = api.post(url, json=file_payload(original))
    assert again.status_code == 200 and again.json()["status"] == "already_restored"
    assert (folder / "raw.txt").read_text(encoding="utf-8") == raw
    meta2 = json.loads((folder / "сессия.json").read_text(encoding="utf-8"))
    assert meta2["_raw_receipts"]["initial"] == source_digest(RawPart(event_id="initial", text=original))
    assert meta2["_initial_text_digest"] == hashlib.sha256(original.encode("utf-8")).hexdigest()


def test_guard_checksum_and_never_overwrite_valid_source(api, monkeypatch):
    sid = create_placeholder(api)
    original = make_text()
    monkeypatch.setattr("app.main.fetch_openai_file", lambda refs: (
        original, "novel.txt", len(original.encode("utf-8")), hashlib.sha256(original.encode("utf-8")).hexdigest()
    ))
    url = f"/sessions/{sid}/raw/repair-file"
    assert api.post(url, json=file_payload(original, expected_bytes=113599)).status_code == 409
    assert "PLACEHOLDER" in api.get(f"/sessions/{sid}/raw").json()["raw"]
    assert api.post(url, json=file_payload(original)).status_code == 200
    another = make_text(113599)
    monkeypatch.setattr("app.main.fetch_openai_file", lambda refs: (
        another, "novel.txt", len(another.encode("utf-8")), hashlib.sha256(another.encode("utf-8")).hexdigest()
    ))
    assert api.post(url, json=file_payload(another)).status_code == 409
    from app.main import session_dir
    import uuid
    assert original in (session_dir(uuid.UUID(sid)) / "raw.txt").read_text(encoding="utf-8")


def test_verification_rejects_placeholder_even_if_user_claims_review(api):
    sid = create_placeholder(api)
    for command in ("подтверждаю", "вопросов_больше_нет", "подтверждаю"):
        response = api.post(f"/sessions/{sid}/advance", json={"command": command})
        assert response.status_code == 200
    result = api.post(f"/sessions/{sid}/verify", json={"audited_against_raw": True})
    assert result.status_code == 409, result.text
    assert result.json()["detail"]["code"] == "RAW_PLACEHOLDER_NOT_REPAIRED"


def test_repair_refuses_missing_file_url(monkeypatch):
    from app.raw_file_transfer import fetch_openai_file
    from fastapi import HTTPException
    for url in ("http://files.oaiusercontent.com/file", "https://localhost/private",
                "https://files.oaiusercontent.com.evil.test/file"):
        with pytest.raises(HTTPException):
            fetch_openai_file([{"name": "source.txt", "download_link": url}])
