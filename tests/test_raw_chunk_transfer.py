"""GPT Actions fallback when file references contain local sandbox paths."""
import base64
import hashlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app, session_dir, RawPart, atomic_json, source_digest

FILE_SIZE = 97094
CHUNK = 12288


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return TestClient(app)


def novel_bytes():
    opening = "Пока мир не сгорит.\r\nРината Дейл.\r\n".encode("utf-8")
    return opening + b"x" * (FILE_SIZE - len(opening))


def parts(binary, mode="append", event_id="novel_source"):
    length = (len(binary) + CHUNK - 1) // CHUNK
    for index in range(length):
        yield {
            "event_id": event_id,
            "mode": mode,
            "part_index": index,
            "total_parts": length,
            "chunk_b64": base64.b64encode(binary[index * CHUNK:(index + 1) * CHUNK]).decode("ascii"),
            "expected_bytes": len(binary),
            "expected_sha256": hashlib.sha256(binary).hexdigest(),
            "file_name": "novel.txt",
        }


def new_session(api, key):
    response = api.post("/sessions", json={"request_id": key, "initial_text": ""})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def get_raw_bytes(sid):
    return (session_dir(uuid.UUID(sid)) / "raw.txt").read_bytes()


def send_parts(api, sid, chunks):
    result = None
    for chunk in chunks:
        response = api.post(f"/sessions/{sid}/raw/chunk", json=chunk)
        assert response.status_code == 200, response.text
        result = response.json()
    return result


def advance_to_review(api, sid):
    for cmd in ("подтверждаю", "вопросов_больше_нет", "подтверждаю"):
        resp = api.post(f"/sessions/{sid}/advance", json={"command": cmd})
        assert resp.status_code == 200, resp.text


def legacy_placeholder(api):
    sid = new_session(api, "placeholder-test")
    folder = session_dir(uuid.UUID(sid))
    old = RawPart(event_id="initial", text="PLACEHOLDER")
    receipt = source_digest(old)
    (folder / "raw.txt").write_text(
        f"\n===== RAW initial {receipt} =====\nPLACEHOLDER\n===== END RAW initial =====\n", encoding="utf-8")
    meta = json.loads((folder / "сессия.json").read_text(encoding="utf-8"))
    meta["_raw_receipts"]["initial"] = receipt
    meta["_initial_text_digest"] = hashlib.sha256(b"PLACEHOLDER").hexdigest()
    atomic_json(folder / "сессия.json", meta)
    return sid


def test_chunked_fallback_exact_bytes_and_retries(api):
    sid = new_session(api, "chunk-97094")
    original = novel_bytes()
    assert len(original) == FILE_SIZE
    chunks = list(parts(original))
    # Original contents are not committed until every chunk arrives.
    result = send_parts(api, sid, chunks[:-1])
    assert result["status"] == "receiving"
    assert not (session_dir(uuid.UUID(sid)) / "raw.txt").exists()
    # Repeating the same chunk has no effect.
    first = api.post(f"/sessions/{sid}/raw/chunk", json=chunks[0])
    assert first.status_code == 200
    response = api.post(f"/sessions/{sid}/raw/chunk", json=chunks[-1])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "saved"
    assert result["bytes"] == FILE_SIZE
    assert result["sha256"] == hashlib.sha256(original).hexdigest()
    assert original in get_raw_bytes(sid)
    assert b"\r\n" in get_raw_bytes(sid)
    before = get_raw_bytes(sid)
    again = api.post(f"/sessions/{sid}/raw/chunk", json=chunks[-1]).json()
    assert again == result
    assert get_raw_bytes(sid) == before
    assert api.get(f"/sessions/{sid}").json()["источников"] == 1


def test_fallback_in_existing_review_session_missing_raw(api):
    sid = new_session(api, "review-missing")
    response = api.post(f"/sessions/{sid}/raw", json={"event_id": "comment", "text": "Первое короткое пояснение."})
    assert response.status_code == 200
    advance_to_review(api, sid)
    original = novel_bytes()
    result = send_parts(api, sid, parts(original, mode="recover"))
    assert result["status"] == "restored_review_required"
    assert original in get_raw_bytes(sid)
    assert "Первое короткое пояснение".encode("utf-8") in get_raw_bytes(sid)
    assert api.get(f"/sessions/{sid}").json()["этап"] == "запись_и_сверка"


def test_fallback_repairs_old_placeholder_after_review(api):
    sid = legacy_placeholder(api)
    advance_to_review(api, sid)
    original = novel_bytes()
    result = send_parts(api, sid, parts(original, mode="repair", event_id="initial"))
    assert result["status"] == "restored_review_required"
    assert b"PLACEHOLDER" not in get_raw_bytes(sid)
    assert original in get_raw_bytes(sid)
    meta = json.loads((session_dir(uuid.UUID(sid)) / "сессия.json").read_text(encoding="utf-8"))
    assert meta["_raw_receipts"]["initial"] == source_digest(RawPart(event_id="initial", text=original.decode("utf-8")))
    # repair preserves original event metadata (none here); filename from transfer is not imposed.


def test_bad_checksum_or_changed_chunk_rejected_without_raw(api):
    sid = new_session(api, "bad-sha")
    original = novel_bytes()
    chunks = list(parts(original))
    corrupted = dict(chunks[0])
    corrupted["chunk_b64"] = base64.b64encode(b"X" + original[1:CHUNK]).decode("ascii")
    result = api.post(f"/sessions/{sid}/raw/chunk", json=corrupted)
    assert result.status_code == 200
    assert api.post(f"/sessions/{sid}/raw/chunk", json=chunks[0]).status_code == 409
    for chunk in chunks[1:-1]:
        assert api.post(f"/sessions/{sid}/raw/chunk", json=chunk).status_code == 200
    final = api.post(f"/sessions/{sid}/raw/chunk", json=chunks[-1])
    assert final.status_code == 409 and "RAW_SHA256_MISMATCH" in final.text
    assert not (session_dir(uuid.UUID(sid)) / "raw.txt").exists()


def test_local_path_guides_to_working_fallback(api):
    from app.raw_file_transfer import fetch_openai_file
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        fetch_openai_file([{"name": "story.txt", "download_link": "/mnt/data/story.txt"}])
    assert error.value.detail["code"] == "FILE_REFERENCE_LOCAL_ONLY"
    sid = new_session(api, "legacy-still-works")
    resp = api.post(f"/sessions/{sid}/raw", json={"event_id": "old_method", "text": "Текст оригинала."})
    assert resp.status_code == 200
    assert "Текст оригинала".encode("utf-8") in get_raw_bytes(sid)


def test_no_append_overwrite_and_no_game_stage_chunk(api):
    sid = new_session(api, "non-overwrite")
    original = novel_bytes()
    response = api.post(f"/sessions/{sid}/raw", json={"event_id": "novel_source", "text": "Ранее сохранённое."})
    assert response.status_code == 200
    result = api.post(f"/sessions/{sid}/raw/chunk", json=list(parts(original))[0])
    assert result.status_code == 200
    for chunk in list(parts(original))[1:-1]:
        assert api.post(f"/sessions/{sid}/raw/chunk", json=chunk).status_code == 200
    last = api.post(f"/sessions/{sid}/raw/chunk", json=list(parts(original))[-1])
    assert last.status_code == 409
    assert "Ранее сохранённое".encode("utf-8") in get_raw_bytes(sid)
