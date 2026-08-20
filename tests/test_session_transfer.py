import json
from copy import deepcopy


def _chunks(text: str, size: int = 700) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]


def _start_and_upload(client, payload, *, omit_last: bool = False):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    chunks = _chunks(raw)
    started = client.post(
        "/api/v1/session-transfers", json={"total_chunks": len(chunks)}
    )
    assert started.status_code == 200, started.text
    transfer_id = started.json()["transfer_id"]
    uploaded_chunks = chunks[:-1] if omit_last else chunks
    for index, content in enumerate(uploaded_chunks):
        uploaded = client.post(
            f"/api/v1/session-transfers/{transfer_id}/chunks",
            json={"chunk_index": index, "content": content},
        )
        assert uploaded.status_code == 200, uploaded.text
    return transfer_id, raw, chunks


def _current_payload(session_payload):
    payload = deepcopy(session_payload)
    payload["runtime_contract_version"] = "2.0"
    payload["director_plan"]["active_threads"] = [
        {
            "thread_id": "thread_main",
            "current_question": "Почему обычное утро нарушено?",
            "current_pressure": "Героиня должна отреагировать на новую загадку",
            "status": "active",
        }
    ]
    payload["director_plan"]["character_agendas"] = [
        {
            "character_id": "char_chloe",
            "current_goal": "Добиться честного разговора с Эмили",
            "next_plausible_action": "Задать прямой вопрос",
            "conditions": [],
        }
    ]
    return payload


def test_chunked_session_transfer_persists_and_verifies_every_document(
    client, service, session_payload
):
    payload = _current_payload(session_payload)
    transfer_id, raw, chunks = _start_and_upload(client, payload)

    finalized = client.post(f"/api/v1/session-transfers/{transfer_id}/finalize")

    assert finalized.status_code == 200, finalized.text
    body = finalized.json()
    assert body["session_id"].startswith("sess_")
    assert body["creation_verified"] is True
    assert body["payload_chars"] == len(raw)
    assert body["stored_document_count"] == 20
    receipt = service.storage.read_json(body["session_id"], "creation_receipt.json")
    assert receipt["transfer_id"] == transfer_id
    assert receipt["total_chunks"] == len(chunks)
    assert receipt["creation_verified"] is True
    setup_source = service.storage.read_json(
        body["session_id"], "state/setup_source.json"
    )
    assert setup_source["messages"] == payload["setup_source"]["messages"]

    retry = client.post(f"/api/v1/session-transfers/{transfer_id}/finalize")
    assert retry.status_code == 200, retry.text
    assert retry.json() == body


def test_transfer_rejects_finalize_with_missing_chunk(client, session_payload):
    payload = _current_payload(session_payload)
    transfer_id, _raw, _chunks_value = _start_and_upload(
        client, payload, omit_last=True
    )

    finalized = client.post(f"/api/v1/session-transfers/{transfer_id}/finalize")

    assert finalized.status_code == 409, finalized.text
    assert finalized.json()["error"]["code"] == "TRANSFER_INCOMPLETE"


def test_transfer_requires_order_and_keeps_identical_retry_idempotent(client):
    started = client.post(
        "/api/v1/session-transfers", json={"total_chunks": 2}
    )
    transfer_id = started.json()["transfer_id"]

    out_of_order = client.post(
        f"/api/v1/session-transfers/{transfer_id}/chunks",
        json={"chunk_index": 1, "content": "second"},
    )
    assert out_of_order.status_code == 409
    assert out_of_order.json()["error"]["code"] == "TRANSFER_CHUNK_OUT_OF_ORDER"

    first = client.post(
        f"/api/v1/session-transfers/{transfer_id}/chunks",
        json={"chunk_index": 0, "content": "first"},
    )
    assert first.status_code == 200, first.text

    same = client.post(
        f"/api/v1/session-transfers/{transfer_id}/chunks",
        json={"chunk_index": 0, "content": "first"},
    )
    assert same.status_code == 200, same.text
    assert same.json()["received_chunks"] == 1

    conflict = client.post(
        f"/api/v1/session-transfers/{transfer_id}/chunks",
        json={"chunk_index": 0, "content": "changed"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "TRANSFER_CHUNK_CONFLICT"


def test_current_contract_rejects_abbreviated_setup_after_reassembly(
    client, session_payload
):
    payload = _current_payload(session_payload)
    payload["novel"] = {}
    payload["hidden_lore"] = {}
    payload["plot_state"] = {}
    payload["world_state"] = {}
    payload["scene_state"] = {}
    for character in payload["characters"]:
        character["current_state"] = {}
        character["relationships"] = {}
        character["knowledge"] = {}

    transfer_id, _raw, _chunks_value = _start_and_upload(client, payload)
    finalized = client.post(f"/api/v1/session-transfers/{transfer_id}/finalize")

    assert finalized.status_code == 422, finalized.text
    body = finalized.json()
    assert body["error"]["code"] == "SESSION_SETUP_INCOMPLETE"
    assert "novel.title" in body["error"]["message"]
    assert "scene_state" in body["error"]["message"]


def test_current_contract_requires_exact_setup_source(client, session_payload):
    payload = _current_payload(session_payload)
    payload.pop("setup_source")
    transfer_id, _raw, _chunks_value = _start_and_upload(client, payload)

    finalized = client.post(f"/api/v1/session-transfers/{transfer_id}/finalize")

    assert finalized.status_code == 422, finalized.text
    assert finalized.json()["error"]["code"] == "SESSION_SETUP_INCOMPLETE"
    assert "setup_source is required" in finalized.json()["error"]["message"]
