from fastapi.testclient import TestClient
from app.main import app


def test_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mode"] == "gpt_actions"


def test_empty_start_returns_questionnaire():
    client = TestClient(app)
    response = client.post("/api/v1/sessions", json={"raw_start_text": "начнем", "mode": "gpt_actions"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_questionnaire"
    assert body["session_id"] is None
    assert "Жанр" in body["questionnaire"]


def test_create_debug_session_and_scene_contract():
    client = TestClient(app)
    response = client.post("/api/v1/sessions", json={
        "genre": "debug",
        "setting_request": "debug",
        "protagonist_request": "debug",
        "mode": "debug_stub"
    })
    assert response.status_code == 200
    session_id = response.json()["session_id"]

    contract = client.get(f"/api/v1/sessions/{session_id}/scene-contract")
    assert contract.status_code == 200
    body = contract.json()
    assert body["contract_version"] == "novella.scene_contract.v1"
    assert "POV" in body["output_requirements"]["visible_scene_format"]["forbidden_header_fields"]
    assert body["current_frame"]["weather"]


def test_debug_turn_returns_header_without_pov():
    client = TestClient(app)
    created = client.post("/api/v1/sessions", json={
        "genre": "debug",
        "setting_request": "debug",
        "protagonist_request": "debug",
        "mode": "debug_stub"
    }).json()
    session_id = created["session_id"]

    response = client.post(f"/api/v1/sessions/{session_id}/turn", json={
        "player_input": "(осмотреться)",
        "mode": "debug_stub"
    })
    assert response.status_code == 200
    scene = response.json()["scene"]
    assert "🎭" in scene
    assert "🕒" in scene
    assert "🌦️" in scene
    assert "POV" not in scene
    assert "Фокус" not in scene
    assert "В сцене" not in scene


def test_apply_turn_result_saves_header_state_fields():
    client = TestClient(app)
    created = client.post("/api/v1/sessions", json={
        "genre": "debug",
        "setting_request": "debug",
        "protagonist_request": "debug",
        "mode": "debug_stub"
    }).json()
    session_id = created["session_id"]

    scene_response = {
        "response_version": "novella.scene_response.v1",
        "player_input": "test",
        "scene": {
            "header": {
                "story_title": "Debug",
                "date": "Day 1",
                "time": "01:00",
                "location": "new debug room",
                "weather": "rain",
                "scene_state": "wet floor",
                "player_name": "Akira Vale",
                "visible_state": "нейтрально",
                "outfit": "new coat",
                "inventory": "debug item, key"
            },
            "body": "*Debug body.*",
            "player_options": {
                "thoughts": ["a", "b", "c"],
                "dialogue": ["a", "b", "c"],
                "actions": ["a", "b", "c"]
            },
            "status_panel": {
                "hunger": "норма",
                "fatigue": "низкая",
                "injuries": "нет",
                "emotional_state": "нейтрально",
                "skills": "debug observation",
                "custom": [
                    {"id": "story_slot_1", "label": "Debug slot 1", "value": "x"},
                    {"id": "story_slot_2", "label": "Debug slot 2", "value": "y"}
                ]
            },
            "relationships_panel": [],
            "rendered_text": "🎭 Debug · Day 1\n🕒 01:00 · 📍 new debug room"
        },
        "summary": "debug summary",
        "important_facts": [],
        "witnesses": ["protagonist"],
        "proposed_updates": {
            "scene_state_patch": {
                "time": "01:00",
                "location": "new debug room",
                "weather": "rain",
                "scene_state": "wet floor",
                "outfit": "new coat",
                "inventory": ["debug item", "key"],
                "nearby_items": ["umbrella"]
            },
            "relationship_patches": [],
            "knowledge_patches": [],
            "new_or_updated_characters": []
        },
        "safety_checks": {
            "used_only_loaded_characters": True,
            "respected_knowledge_boundaries": True,
            "no_hidden_future_reveal": True,
            "no_major_player_character_choice": True,
            "respected_player_input_order": True,
            "showed_only_scene_relationships": True,
            "header_has_no_focus_or_active_list": True,
            "notes": []
        }
    }

    response = client.post(f"/api/v1/sessions/{session_id}/apply-turn-result", json={"scene_response": scene_response})
    assert response.status_code == 200

    memory = client.get(f"/api/v1/sessions/{session_id}/memory").json()
    state = memory["current_state"]
    assert state["weather"] == "rain"
    assert state["scene_state"] == "wet floor"
    assert state["outfit"] == "new coat"
    assert state["inventory"] == ["debug item", "key"]
    assert state["nearby_items"] == ["umbrella"]


def test_latest_session_endpoint_returns_active_session():
    client = TestClient(app)
    created = client.post("/api/v1/sessions", json={
        "genre": "debug",
        "setting_request": "debug",
        "protagonist_request": "debug",
        "mode": "debug_stub"
    }).json()
    response = client.get("/api/v1/sessions/latest")
    assert response.status_code == 200
    assert response.json()["session_id"] == created["session_id"]


def test_bootstrap_rejects_cyrillic_character_names():
    client = TestClient(app)
    created = client.post("/api/v1/sessions", json={
        "genre": "romance",
        "setting_request": "academy near the sea",
        "protagonist_request": "guarded adult heroine",
        "mode": "gpt_actions"
    }).json()
    session_id = created["session_id"]
    bad_bootstrap = {
        "protagonist": {"id": "protagonist", "name": "Марина Мор"},
        "characters": {"protagonist": {"id": "protagonist", "name": "Марина Мор", "role": "protagonist"}},
        "relationships": {},
        "knowledge": {"protagonist": {"knows": [], "does_not_know": [], "must_not_assume": []}},
        "story_plan": {
            "genre": "romance",
            "language": "ru",
            "tone": "tense",
            "main_premise": "test",
            "act_structure": [],
            "status_slots": [
                {"id": "story_slot_1", "label": "Risk", "description": "x", "initial_value": "x"},
                {"id": "story_slot_2", "label": "Trust", "description": "y", "initial_value": "y"}
            ],
            "forbidden_drift": [],
            "current_story_position": "act_1_start"
        },
        "current_state": {
            "turn_number": 0,
            "date": "Day 1",
            "time": "10:00",
            "location": "station",
            "weather": "rain",
            "scene_state": "wet platform",
            "outfit": "coat",
            "inventory": [],
            "nearby_items": [],
            "player_character_id": "protagonist",
            "active_character_ids": ["protagonist"],
            "nearby_character_ids": [],
            "scene_goal": "start",
            "last_player_input": "",
            "environment": {},
            "status": {
                "hunger": "норма",
                "fatigue": "низкая",
                "injuries": [],
                "emotional_state": "нейтрально",
                "skills": [],
                "custom": [
                    {"id": "story_slot_1", "label": "Risk", "value": "x"},
                    {"id": "story_slot_2", "label": "Trust", "value": "y"}
                ]
            }
        },
        "npc_state": {},
        "future_locks": {},
        "continuity": {},
        "scene_history": [],
        "turns": []
    }
    response = client.post(f"/api/v1/sessions/{session_id}/bootstrap-result", json={"bootstrap_json": bad_bootstrap})
    assert response.status_code == 422
    assert "Latin script" in str(response.json()["detail"])


def test_scene_response_rejects_knowledge_patch_without_source():
    client = TestClient(app)
    created = client.post("/api/v1/sessions", json={
        "genre": "debug",
        "setting_request": "debug",
        "protagonist_request": "debug",
        "mode": "debug_stub"
    }).json()
    session_id = created["session_id"]
    scene_response = {
        "response_version": "novella.scene_response.v1",
        "player_input": "test",
        "scene": {
            "header": {
                "story_title": "Debug",
                "date": "Day 1",
                "time": "01:00",
                "location": "room",
                "weather": "rain",
                "scene_state": "wet floor",
                "player_name": "Akira Vale",
                "visible_state": "neutral",
                "outfit": "coat",
                "inventory": "key"
            },
            "body": "*Debug.*",
            "player_options": {"thoughts": ["a", "b", "c"], "dialogue": ["a", "b", "c"], "actions": ["a", "b", "c"]},
            "status_panel": {
                "hunger": "ok",
                "fatigue": "low",
                "injuries": "none",
                "emotional_state": "neutral",
                "skills": "debug",
                "custom": [
                    {"id": "story_slot_1", "label": "A", "value": "x"},
                    {"id": "story_slot_2", "label": "B", "value": "y"}
                ]
            },
            "relationships_panel": [],
            "rendered_text": "🎭 Debug · Day 1"
        },
        "summary": "debug",
        "important_facts": [],
        "witnesses": ["protagonist"],
        "proposed_updates": {
            "scene_state_patch": {},
            "relationship_patches": [],
            "knowledge_patches": [{"character_id": "protagonist", "add_knows": ["secret"]}],
            "new_or_updated_characters": []
        },
        "safety_checks": {
            "used_only_loaded_characters": True,
            "respected_knowledge_boundaries": True,
            "no_hidden_future_reveal": True,
            "no_major_player_character_choice": True,
            "respected_player_input_order": True,
            "showed_only_scene_relationships": True,
            "header_has_no_focus_or_active_list": True,
            "notes": []
        }
    }
    response = client.post(f"/api/v1/sessions/{session_id}/apply-turn-result", json={"scene_response": scene_response})
    assert response.status_code == 422
    assert "source_in_scene" in str(response.json()["detail"])
