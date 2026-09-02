from copy import deepcopy

from fastapi.testclient import TestClient

from app.config import Settings
from app.fast_audit_service import FastAuditNovellaService
from app.main import app
from app.runtime_documents import read_runtime_rules
from tests.conftest import collect_packet, create_session


def _production_client(tmp_path) -> tuple[TestClient, FastAuditNovellaService]:
    service = FastAuditNovellaService(
        Settings(
            data_dir=tmp_path / "foundation-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4_000,
        )
    )
    app.state.service = service
    return TestClient(app), service


def test_foundation_archive_is_preserved_without_bloating_writer_packet(
    tmp_path, session_payload
) -> None:
    client, service = _production_client(tmp_path)
    payload = deepcopy(session_payload)
    payload["runtime_contract_version"] = "2.0"
    player_fact = "Хлоя в детстве пережила пожар и до сих пор всегда замечает запах дыма."
    payload["characters"][1]["card"]["biography"].append(player_fact)
    payload["world_state"]["foundation_archive"] = [
        {
            "fact_id": "foundation_chloe_fire",
            "text": player_fact,
            "source": "player",
            "character_ids": ["char_chloe"],
            "status": "active",
            "stored_in": ["characters.char_chloe.card.biography"],
        }
    ]
    payload["director_plan"]["foundation_hooks"] = [
        {
            "hook_id": "hook_chloe_smoke",
            "fact_ids": ["foundation_chloe_fire"],
            "use_when": "дым, пожар, запах гари или похожая ассоциация естественно входят в сцену",
            "status": "latent",
        }
    ]

    session_id = create_session(client, payload)

    stored_world = service.storage.read_json(session_id, "state/world_state.json")
    assert stored_world["foundation_archive"][0]["text"] == player_fact
    assert stored_world["foundation_archive"][0]["stored_in"] == [
        "characters.char_chloe.card.biography"
    ]

    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={"player_input": "Продолжить сцену", "mode": "new"},
        ),
    )

    assert "foundation_archive" not in packet["state"]["world"]
    assert packet["story_bible"]["story_direction"]["foundation_hooks"][0][
        "hook_id"
    ] == "hook_chloe_smoke"
    chloe = next(
        item for item in packet["state"]["characters"] if item["character_id"] == "char_chloe"
    )
    assert player_fact in chloe["card"]["biography"]


def test_per_turn_runtime_rules_are_compact_but_keep_memory_contract() -> None:
    rules = read_runtime_rules()
    assert len(rules) < 8_000
    assert "Railway хранит память" in rules
    assert "knowledge" in rules
    assert "foundation_hooks" in rules
    assert "commitTurn" in rules
