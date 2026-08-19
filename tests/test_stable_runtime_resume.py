from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.stable_runtime_service import StableRuntimeNovellaService
from tests.conftest import collect_packet, create_session


def _stable_client(tmp_path) -> TestClient:
    app.state.service = StableRuntimeNovellaService(
        Settings(
            data_dir=tmp_path / "stable-runtime-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def test_fresh_packet_is_compact_json_before_first_action_response(
    tmp_path, session_payload
) -> None:
    client = _stable_client(tmp_path)
    session_id = create_session(client, session_payload)

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Действие", "mode": "new"},
    )
    assert first.status_code == 200, first.text
    pending = app.state.service.storage.read_json(session_id, "pending_turn.json")
    raw = "".join(pending["chunks"])
    assert pending["compact_packet_version"] == 1
    assert max(len(chunk) for chunk in pending["chunks"]) <= 4000
    assert "\n" not in raw
    assert raw.startswith("{") and raw.endswith("}")


def test_different_player_message_resumes_existing_incomplete_turn_packet(
    tmp_path, session_payload
) -> None:
    client = _stable_client(tmp_path)
    session_id = create_session(client, session_payload)

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Первоначальное действие", "mode": "new"},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["chunk_count"] > 1
    assert first_body["delivered_chunk_count"] == 1

    resumed = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Продолжай уже", "mode": "new"},
    )
    assert resumed.status_code == 200, resumed.text
    resumed_body = resumed.json()
    assert resumed_body["packet_id"] == first_body["packet_id"]
    assert resumed_body["chunk_index"] == 1
    assert resumed_body["delivered_chunk_count"] == 2
    assert "earlier player input" in resumed_body["next_required_action"].lower()


def test_completed_pending_turn_packet_is_resumable_instead_of_409(
    tmp_path, session_payload
) -> None:
    client = _stable_client(tmp_path)
    session_id = create_session(client, session_payload)

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Первоначальное действие", "mode": "new"},
    )
    packet = collect_packet(client, session_id, first)

    resumed = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Ещё одна попытка", "mode": "new"},
    )
    assert resumed.status_code == 200, resumed.text
    body = resumed.json()
    assert body["all_chunks_delivered"] is True
    assert body["packet_id"]
    assert "committurn" in body["next_required_action"].lower()
    assert packet["player_input"] == "Первоначальное действие"


def test_same_pending_request_also_advances_to_next_unread_chunk(
    tmp_path, session_payload
) -> None:
    client = _stable_client(tmp_path)
    session_id = create_session(client, session_payload)

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Действие", "mode": "new"},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["chunk_count"] > 1

    resumed = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Действие", "mode": "new"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["packet_id"] == first_body["packet_id"]
    assert resumed.json()["chunk_index"] == 1
