from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.recovery_service import RecoveryNovellaService
from tests.conftest import collect_packet, create_session, scene_output, scene_state_update


def _client(tmp_path) -> TestClient:
    app.state.service = RecoveryNovellaService(
        Settings(
            data_dir=tmp_path / "recovery-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def _commit_body(packet: dict, *, body: str) -> dict:
    turn_number = int(packet["turn_number"])
    return {
        "turn_id": packet["turn_id"],
        "expected_state_revision": packet["expected_state_revision"],
        "scene_output": scene_output(
            turn_number,
            packet["cycle_position"],
            body=body,
        ),
        "summary": "Проверка восстановления pending и реплики POV",
        "scene_id": f"scene_{turn_number:04d}",
        "story_datetime": f"2025-09-08T10:{turn_number:02d}:00",
        "events": [
            {
                "scene_id": f"scene_{turn_number:04d}",
                "story_datetime": f"2025-09-08T10:{turn_number:02d}:00",
                "location_id": "loc_home",
                "participants_present": ["char_emily", "char_chloe"],
                "event": "Продолжена текущая сцена",
            }
        ],
        "state_updates": {
            "scene_state": scene_state_update(
                turn_number,
                present_character_ids=["char_emily", "char_chloe"],
            )
        },
    }


def test_active_pending_is_replayed_instead_of_blocking_new_input(
    tmp_path, session_payload
) -> None:
    client = _client(tmp_path)
    session_id = create_session(client, session_payload)

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={
            "player_input": "Первый незавершённый ход",
            "client_request_id": "request_first",
        },
    )
    assert first.status_code == 200, first.text
    first_packet_id = first.json()["packet_id"]

    recovered = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={
            "player_input": "Новый ввод после сбоя",
            "client_request_id": "request_after_failure",
        },
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["packet_id"] == first_packet_id
    assert recovered.json()["delivered_chunk_count"] == 1

    pending_packet = collect_packet(client, session_id, recovered)
    assert pending_packet["player_input"] == "Первый незавершённый ход"

    committed = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json=_commit_body(
            pending_packet,
            body="**Эмили** — Первый незавершённый ход",
        ),
    )
    assert committed.status_code == 200, committed.text

    next_packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={
                "player_input": "Новый ввод после сбоя",
                "client_request_id": "request_after_failure",
            },
        ),
    )
    assert next_packet["turn_number"] == 2
    assert next_packet["player_input"] == "Новый ввод после сбоя"


def test_spoken_player_input_must_appear_in_main_scene(
    tmp_path, session_payload
) -> None:
    client = _client(tmp_path)
    session_id = create_session(client, session_payload)
    player_input = (
        "Итан, что значит “часть цепи”? "
        "(Быстро проверить свою линию и поискать рядом вторую.)"
    )

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": player_input},
        ),
    )

    missing = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json=_commit_body(packet, body="Эмили быстро проверяет линию рядом с собой."),
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "POV_SPOKEN_INPUT_MISSING"

    option_only = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json=_commit_body(
            packet,
            body=(
                "Эмили быстро проверяет линию рядом с собой.\n\n"
                "Что я могу сделать:\n1. Осмотреться\n2. Подойти ближе\n3. Замереть\n\n"
                "Что я могу сказать:\n1. Итан, что значит “часть цепи”?\n2. Подожди.\n3. Я вижу её."
            ),
        ),
    )
    assert option_only.status_code == 422
    assert option_only.json()["error"]["code"] == "POV_SPOKEN_INPUT_MISSING"

    valid = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json=_commit_body(
            packet,
            body=(
                "Эмили быстро проверяет линию рядом с собой.\n\n"
                "**Эмили** — Итан, что значит “часть цепи”?"
            ),
        ),
    )
    assert valid.status_code == 200, valid.text
