import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.service import NovellaService


def full_character_card(character_id: str, name: str, hint: str) -> dict[str, Any]:
    return {
        "character_id": character_id,
        "card_level": "player_defined",
        "origin": "player",
        "card_hint": hint,
        "record_status": "active",
        "story_status": "active",
        "player_visibility": "visible",
        "identity": {
            "name": name,
            "age": "25",
            "role": "участник тестовой истории",
            "occupation": "установлено в тестовой карточке",
        },
        "appearance": {
            "height": "средний рост",
            "build": "среднее телосложение",
            "hair": "тёмные",
            "eyes": "карие",
            "face": "выразительные черты",
            "skin_and_features": "без особых примет",
            "movement_and_mannerisms": "двигается спокойно",
            "clothing_style": "повседневный",
            "distinguishing_details": ["узнаваемая манера смотреть"],
            "visual_impression": "сдержанный",
            "visual_noticeability": "pleasant",
        },
        "immediate_scene_goal": "продолжить текущую сцену",
        "personality": {
            "outward_mask": "собранный",
            "inner_character": "самостоятельный и последовательный",
            "strengths": ["наблюдательность"],
            "flaws": ["упрямство"],
            "temperament": "ровный",
            "internal_conflict": "хочет близости, но бережёт независимость",
            "behavior_under_pressure": "становится немногословным",
            "habits": ["следит за временем", "поправляет рукав"],
            "speech": "говорит коротко",
        },
        "preferences": {
            "likes": ["тишина"],
            "dislikes": ["давление"],
            "likes_in_people": ["прямота"],
            "dislikes_in_people": ["неискренность"],
        },
        "biography": ["Прошлое установлено тестовой карточкой."],
        "skills": ["наблюдение"],
        "goals": {
            "personal": "сохранить самостоятельность",
            "immediate": "продолжить текущую сцену",
            "toward_pov": "поддерживать установленную связь",
            "story_function": "проверка постоянства карточки",
            "possible_arc": "отношения меняются через события",
        },
        "hidden_motives": [],
        "secrets": [],
        "constraints": ["не меняет установленные факты без причины"],
    }


@pytest.fixture
def service(tmp_path: Path) -> NovellaService:
    return NovellaService(
        Settings(
            data_dir=tmp_path / "data",
            public_base_url="https://example.test",
            packet_chunk_chars=4000,
        )
    )


@pytest.fixture
def client(service: NovellaService) -> TestClient:
    app.state.service = service
    return TestClient(app)


@pytest.fixture
def session_payload() -> dict[str, Any]:
    return {
        "player_confirmation": "Подтверждаю",
        "novel": {
            "title": "Тестовая новелла",
            "pov_character_id": "char_emily",
            "genre": ["mystery"],
        },
        "hidden_lore": {"facts": [{"fact_id": "secret_1", "value": "hidden"}]},
        "plot_state": {"active_lines": []},
        "director_plan": {
            "active_threads": [],
            "character_agendas": [],
            "event_windows": [],
            "collision_points": [],
            "offscreen_events": [],
            "consequences_without_pov": [],
            "possible_pov_contacts": [],
        },
        "world_state": {"story_datetime": "2025-09-08T10:00:00"},
        "scene_state": {
            "turn_number": 0,
            "scene_id": "scene_0000",
            "present_character_ids": ["char_emily", "char_chloe"],
        },
        "characters": [
            {
                "character_id": "char_emily",
                "card": full_character_card(
                    "char_emily", "Эмили", "POV, действует прямо и не любит пустые разговоры."
                ),
                "current_state": {"current_location_id": "loc_home"},
                "relationships": {"relations": []},
                "knowledge": {"entries": []},
            },
            {
                "character_id": "char_chloe",
                "card": full_character_card(
                    "char_chloe", "Хлоя", "Подруга POV, наблюдательная и разговорчивая."
                ),
                "current_state": {"current_location_id": "loc_home"},
                "relationships": {"relations": []},
                "knowledge": {"entries": []},
            },
        ],
        "locations": [
            {
                "location_id": "loc_home",
                "state": {
                    "canon": {
                        "name": "Дом Эмили",
                        "purpose": "жилой дом",
                        "scale": "небольшой",
                        "layout": "прихожая ведёт в общую комнату",
                        "zones": ["прихожая", "общая комната"],
                        "visual_style": "простой жилой интерьер",
                        "condition": "обжитой",
                        "color_palette": ["серый", "молочный"],
                        "materials": ["дерево", "ткань"],
                        "lighting": "дневной свет и потолочные лампы",
                        "windows_and_view": "окна выходят во двор",
                        "entrances": ["главная дверь"],
                        "permanent_objects": ["стол"],
                        "signature_details": ["узкая прихожая"],
                    },
                    "current_changes": [],
                    "access": ["доступен жильцам"],
                    "damage_or_modifications": [],
                },
            }
        ],
        "objects": [],
    }


def create_session(client: TestClient, payload: dict[str, Any]) -> str:
    response = client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def collect_packet(
    client: TestClient,
    session_id: str,
    first_response: Any,
) -> dict[str, Any]:
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()
    chunks = [first["content"]]
    packet_type = first["packet_type"]
    plural = "turn-packets" if packet_type == "turn" else "audit-packets"
    for index in range(1, first["chunk_count"]):
        response = client.get(
            f"/api/v1/sessions/{session_id}/{plural}/{first['packet_id']}/chunks/{index}"
        )
        assert response.status_code == 200, response.text
        chunks.append(response.json()["content"])
    raw = "".join(chunks)
    assert (
        first["content_sha256"]
        == __import__("hashlib").sha256(raw.encode()).hexdigest()
    )
    return json.loads(raw)


def scene_output(
    turn_number: int, cycle_position: int, body: str = "Сцена продолжается."
) -> str:
    return (
        f"{body}\n\n"
        f"Ход {turn_number} · цикл {cycle_position}/15\n"
        "↻ Перед следующим ходом: прочитать актуальный state. "
        "На 15/15 — провести сверку последних 15 ходов с Railway."
    )


def commit_next_turn(
    client: TestClient,
    session_id: str,
    *,
    player_input: str,
    mode: str = "new",
    event_text: str | None = None,
    state_updates: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    first = client.post(
        f"/api/v1/sessions/{session_id}/turn-packet",
        json={"player_input": player_input, "mode": mode},
    )
    packet = collect_packet(client, session_id, first)
    turn_number = packet["turn_number"]
    cycle_position = packet["cycle_position"]
    event_text = event_text or f"Установленный факт хода {turn_number}"
    response = client.post(
        f"/api/v1/sessions/{session_id}/turns/commit",
        json={
            "turn_id": packet["turn_id"],
            "expected_state_revision": packet["expected_state_revision"],
            "scene_output": scene_output(turn_number, cycle_position),
            "summary": f"Краткое содержание хода {turn_number}",
            "scene_id": f"scene_{turn_number:04d}",
            "story_datetime": f"2025-09-08T10:{turn_number:02d}:00",
            "events": [
                {
                    "scene_id": f"scene_{turn_number:04d}",
                    "story_datetime": f"2025-09-08T10:{turn_number:02d}:00",
                    "location_id": "loc_home",
                    "participants_present": ["char_emily", "char_chloe"],
                    "event": event_text,
                }
            ],
            "state_updates": state_updates
            or {
                "scene_state": {
                    "turn_number": turn_number,
                    "scene_id": f"scene_{turn_number:04d}",
                    "present_character_ids": ["char_emily", "char_chloe"],
                }
            },
        },
    )
    assert response.status_code == 200, response.text
    return packet, response.json()


def complete_checklist() -> dict[str, bool]:
    return {
        "events_and_consequences": True,
        "time_and_movement": True,
        "scene_and_physical_state": True,
        "character_current_states": True,
        "character_continuity": True,
        "minor_npc_lifecycle": True,
        "knowledge_sources": True,
        "knowledge_boundaries": True,
        "directional_relationships": True,
        "plot_threads": True,
        "hidden_lore_and_reveal_timing": True,
        "compaction_and_duplicates": True,
    }
