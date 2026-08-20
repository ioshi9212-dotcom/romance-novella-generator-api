import json
from copy import deepcopy


def _chunks(text: str, size: int) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]


def test_chunked_session_transfer_creates_session(client, session_payload):
    payload = deepcopy(session_payload)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    chunks = _chunks(raw, 700)

    started = client.post(
        "/api/v1/session-transfers",
        json={"total_chunks": len(chunks)},
    )
    assert started.status_code == 200, started.text
    transfer_id = started.json()["transfer_id"]
    assert started.json()["next_chunk_index"] == 0

    for index, chunk in enumerate(chunks):
        uploaded = client.post(
            f"/api/v1/session-transfers/{transfer_id}/chunks",
            json={"chunk_index": index, "content": chunk},
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["accepted_chunk_index"] == index

    finalized = client.post(f"/api/v1/session-transfers/{transfer_id}/finalize")
    assert finalized.status_code == 200, finalized.text
    body = finalized.json()
    assert body["transfer_id"] == transfer_id
    assert body["session_id"].startswith("sess_")
    assert body["next_turn_number"] == 1

    retry = client.post(f"/api/v1/session-transfers/{transfer_id}/finalize")
    assert retry.status_code == 200, retry.text
    assert retry.json()["session_id"] == body["session_id"]


def test_transfer_rejects_finalize_with_missing_chunk(client, session_payload):
    raw = json.dumps(session_payload, ensure_ascii=False)
    chunks = _chunks(raw, max(1, len(raw) // 2))
    if len(chunks) < 2:
        chunks = [raw[:1], raw[1:]]

    started = client.post(
        "/api/v1/session-transfers",
        json={"total_chunks": len(chunks)},
    )
    transfer_id = started.json()["transfer_id"]

    uploaded = client.post(
        f"/api/v1/session-transfers/{transfer_id}/chunks",
        json={"chunk_index": 0, "content": chunks[0]},
    )
    assert uploaded.status_code == 200, uploaded.text

    finalized = client.post(f"/api/v1/session-transfers/{transfer_id}/finalize")
    assert finalized.status_code == 409, finalized.text
    assert finalized.json()["error"]["code"] == "TRANSFER_INCOMPLETE"


def test_transfer_chunk_retry_is_idempotent_and_conflict_safe(client):
    started = client.post(
        "/api/v1/session-transfers",
        json={"total_chunks": 1},
    )
    transfer_id = started.json()["transfer_id"]

    first = client.post(
        f"/api/v1/session-transfers/{transfer_id}/chunks",
        json={"chunk_index": 0, "content": "abc"},
    )
    assert first.status_code == 200, first.text

    same = client.post(
        f"/api/v1/session-transfers/{transfer_id}/chunks",
        json={"chunk_index": 0, "content": "abc"},
    )
    assert same.status_code == 200, same.text

    different = client.post(
        f"/api/v1/session-transfers/{transfer_id}/chunks",
        json={"chunk_index": 0, "content": "xyz"},
    )
    assert different.status_code == 409, different.text
    assert different.json()["error"]["code"] == "TRANSFER_CHUNK_CONFLICT"
