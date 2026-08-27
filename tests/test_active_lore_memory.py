from copy import deepcopy

from fastapi.testclient import TestClient

from app.active_lore_service import ActiveLoreNovellaService
from app.config import Settings
from app.main import app
from tests.conftest import collect_packet, full_character_card


def _client(tmp_path) -> TestClient:
    app.state.service = ActiveLoreNovellaService(
        Settings(
            data_dir=tmp_path / "active-lore-data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )
    return TestClient(app)


def _create(client: TestClient, payload: dict) -> str:
    response = client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _offstage_character(
    character_id: str,
    name: str,
    *,
    knowledge_fact: str,
    current_activity: str,
) -> dict:
    card = full_character_card(
        character_id,
        name,
        f"{name}: важный постоянный персонаж, который живёт и действует вне кадра.",
    )
    card["story_status"] = "offstage"
    card["immediate_scene_goal"] = current_activity
    card["goals"]["immediate"] = current_activity
    card["goals"]["toward_pov"] = "действовать с учётом уже сложившейся связи с POV"
    card["biography"].append(f"Прошлое {name} нельзя сбрасывать при выходе из сцены.")
    return {
        "character_id": character_id,
        "card": card,
        "current_state": {
            "current_location_id": "loc_elsewhere",
            "current_activity": current_activity,
            "pov_familiarity": {
                "status": "acquainted",
                "since_turn": 1,
                "source": "test_setup",
            },
        },
        "relationships": {
            "owner_character_id": character_id,
            "relations": [
                {
                    "target_character_id": "char_emily",
                    "relationship_type": "установленная связь",
                    "relationship_context": "они уже знакомы до текущей сцены",
                    "current_dynamic": "персонаж учитывает POV в собственных решениях",
                    "dimensions": [
                        {"key": "trust", "label": "доверие", "value": 61}
                    ],
                    "beliefs_about_target": ["Эмили не любит давление"],
                    "unresolved_between_them": ["незаконченный разговор"],
                    "dynamic_constraints": ["не вести себя как при первом знакомстве"],
                    "change_reasons": [],
                    "last_changed_turn": 1,
                }
            ],
        },
        "knowledge": {
            "entries": [
                {
                    "knowledge_id": f"knowledge_{character_id}",
                    "fact": knowledge_fact,
                    "source": "confirmed_setup",
                }
            ]
        },
    }


def test_turn_packet_keeps_questionnaire_pov_and_npc_memory_causally_active(
    tmp_path, session_payload
):
    client = _client(tmp_path)
    payload = deepcopy(session_payload)
    payload["novel"]["relationship_focus"] = (
        "Романтические линии и личная динамика важнее симулятора заданий."
    )
    payload["novel"]["world_rule"] = (
        "Прошлое POV и установленные факты анкеты продолжают влиять на новые сцены."
    )
    payload["characters"][0]["card"]["biography"].append(
        "Эмили в прошлом уже пережила событие, которое влияет на её реакцию на грозу."
    )
    payload["characters"][0]["knowledge"] = {
        "entries": [
            {
                "knowledge_id": "emily_knows_archive",
                "fact": "Эмили знает, где спрятан старый архив.",
                "source": "confirmed_setup",
            }
        ]
    }
    payload["characters"][1]["knowledge"] = {
        "entries": [
            {
                "knowledge_id": "chloe_knows_argument",
                "fact": "Хлоя знает о вчерашней ссоре Эмили.",
                "source": "confirmed_setup",
            }
        ]
    }

    ethan = _offstage_character(
        "char_ethan",
        "Итан",
        knowledge_fact="Итан знает, что Эмили уже видела символ цепи.",
        current_activity="решает, нужно ли самому связаться с Эмили",
    )
    nora = _offstage_character(
        "char_nora",
        "Нора",
        knowledge_fact="Нора знает о незакрытом долге перед Эмили.",
        current_activity="ищет возможность вернуть долг без приглашения POV",
    )
    payload["characters"].extend([ethan, nora])
    payload["director_plan"]["character_agendas"].append(
        {
            "character_id": "char_nora",
            "goal": "Нора самостоятельно решает, когда снова выйти на связь с Эмили.",
            "status": "active",
        }
    )

    session_id = _create(client, payload)
    packet = collect_packet(
        client,
        session_id,
        client.post(
            f"/api/v1/sessions/{session_id}/turn-packet",
            json={
                "player_input": "Итан вообще помнит, что было с этой цепью?",
                "mode": "new",
            },
        ),
    )

    memory = packet["active_memory"]
    assert (
        memory["novel_questionnaire"]["relationship_focus"]
        == payload["novel"]["relationship_focus"]
    )
    assert memory["novel_questionnaire"]["world_rule"] == payload["novel"]["world_rule"]

    pov_memory = memory["pov_long_term_memory"]
    assert pov_memory["character_id"] == "char_emily"
    assert any(
        "реакцию на грозу" in item
        for item in pov_memory["full_confirmed_card"]["biography"]
    )
    assert pov_memory["knowledge"]["entries"][0]["knowledge_id"] == "emily_knows_archive"

    scene_lenses = {
        item["character_id"]: item for item in memory["scene_npc_lenses"]
    }
    assert "char_chloe" in scene_lenses
    assert (
        scene_lenses["char_chloe"]["knowledge"]["entries"][0]["knowledge_id"]
        == "chloe_knows_argument"
    )

    cast_ids = {item["character_id"] for item in memory["cast_memory_index"]}
    assert {"char_emily", "char_chloe", "char_ethan", "char_nora"}.issubset(cast_ids)

    activated = {
        item["character"]["character_id"]: item for item in memory["activated_lore"]
    }
    assert "char_ethan" in activated
    assert (
        activated["char_ethan"]["character"]["knowledge"]["entries"][0]["fact"]
        == "Итан знает, что Эмили уже видела символ цепи."
    )

    pulse = {item["character_id"]: item for item in memory["offscreen_cast_pulse"]}
    assert "char_ethan" in pulse
    assert "char_nora" in pulse
    assert pulse["char_nora"]["director_agenda_matches"]
    assert pulse["char_nora"]["knowledge"]["entries"][0]["knowledge_id"] == "knowledge_char_nora"

    assert "MANDATORY CAUSAL MEMORY" in memory["memory_contract"]
    assert "active_memory" in packet["instruction"]


def test_active_lore_service_preserves_pending_turn_recovery(tmp_path, session_payload):
    client = _client(tmp_path)
    session_id = _create(client, deepcopy(session_payload))

    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Первый незавершённый ход", "mode": "new"},
    )
    assert first.status_code == 200, first.text
    first_packet_id = first.json()["packet_id"]

    recovered = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": "Новый ввод после сбоя", "mode": "new"},
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["packet_id"] == first_packet_id

    recovered_packet = collect_packet(client, session_id, recovered)
    assert recovered_packet["player_input"] == "Первый незавершённый ход"
    assert "active_memory" in recovered_packet
