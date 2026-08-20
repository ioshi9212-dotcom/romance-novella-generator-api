from fastapi.testclient import TestClient

from app.main import app
from app.scene_contract_builder import build_scene_contract
from app.scene_response_normalizer import normalize_scene_response
from app.session_manager import SessionManager
from tests.test_smoke import _long_scene_response, _valid_bootstrap


def _active_session(client: TestClient) -> str:
    created = client.post(
        "/api/v1/sessions",
        json={"raw_start_text": "Современная мистика, остальное придумай сам.", "mode": "gpt_actions"},
    )
    session_id = created.json()["session_id"]
    preview = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": _valid_bootstrap()},
    )
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-confirm",
        json={"confirmation_text": "подтверждаю"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return session_id


def _pending_turn(client: TestClient, session_id: str, player_input: str = "(осмотреться)") -> str:
    turn = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": player_input, "mode": "gpt_actions"},
    )
    assert turn.status_code == 200, turn.text
    return turn.json()["turn_id"]


def test_unknown_active_character_rejects_the_whole_turn_without_advancing_state():
    client = TestClient(app)
    session_id = _active_session(client)
    player_input = "(осмотреться)"
    turn_id = _pending_turn(client, session_id, player_input)
    response = _long_scene_response(player_input)
    response["proposed_updates"]["scene_state_patch"]["active_character_ids"] = ["pc_01", "ghost_missing"]

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_id, "scene_response": response},
    )

    assert applied.status_code == 422
    assert any("ghost_missing" in error for error in applied.json()["detail"])
    assert SessionManager().storage.read_json(session_id, "current_state.json")["turn_number"] == 0


def test_unknown_witness_rejects_the_whole_turn():
    client = TestClient(app)
    session_id = _active_session(client)
    player_input = "(проверить дверь)"
    turn_id = _pending_turn(client, session_id, player_input)
    response = _long_scene_response(player_input)
    response["witnesses"] = ["pc_01", "ghost_witness"]

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_id, "scene_response": response},
    )

    assert applied.status_code == 422
    assert any("ghost_witness" in error for error in applied.json()["detail"])


def test_visible_header_is_derived_from_post_patch_state_not_model_claims():
    bundle = _valid_bootstrap()
    response = _long_scene_response("(подождать)")
    response["scene"]["header"].update({
        "date": "99 декабря",
        "time": "77:88",
        "location": "несуществующая локация",
        "weather": "погода из головы модели",
    })
    response["proposed_updates"]["scene_state_patch"].update({
        "date": "2026-09-02",
        "time": "23:15",
        "location": "кофейня у канала",
        "weather": "холодный дождь",
    })

    normalized = normalize_scene_response(response, bundle)
    rendered = normalized["scene"]["rendered_text"]

    assert "2026-09-02" in rendered
    assert "23:15" in rendered
    assert "кофейня у канала" in rendered
    assert "холодный дождь" in rendered
    assert "99 декабря" not in rendered
    assert "77:88" not in rendered
    assert "несуществующая локация" not in rendered


def test_scene_contract_selects_active_act_from_mutable_story_progress():
    bundle = _valid_bootstrap()
    bundle["story_plan"]["act_structure"] = [
        {"id": "act_1", "goal": "завязка"},
        {"id": "act_2", "goal": "сближение и цена выбора"},
    ]
    bundle["continuity"] = {
        "story_progress": {"current_act_index": 1, "current_act_id": "act_2", "current_beat": "последствия"}
    }

    contract = build_scene_contract(bundle, player_input="(продолжить)")

    assert contract["story_compass"]["active_act"] == [{"id": "act_2", "goal": "сближение и цена выбора"}]
    assert contract["story_compass"]["story_progress"]["current_act_index"] == 1


def test_story_progress_cannot_jump_over_an_act_or_move_backwards():
    client = TestClient(app)
    session_id = _active_session(client)
    manager = SessionManager()
    story_plan = manager.storage.read_json(session_id, "story_plan.json")
    story_plan["act_structure"] = [
        {"id": "act_1", "goal": "завязка"},
        {"id": "act_2", "goal": "середина"},
        {"id": "act_3", "goal": "финал"},
    ]
    manager.storage.write_json(session_id, "story_plan.json", story_plan)

    player_input = "(продолжить)"
    turn_id = _pending_turn(client, session_id, player_input)
    response = _long_scene_response(player_input)
    response["proposed_updates"]["continuity_patch"] = {
        "story_progress_patch": {
            "current_act_index": 2,
            "reason": "модель решила ускориться",
            "source_in_scene": "одна обычная сцена",
        }
    }

    rejected = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_id, "scene_response": response},
    )

    assert rejected.status_code == 422
    assert any("cannot jump" in error for error in rejected.json()["detail"])
    assert manager.storage.read_json(session_id, "current_state.json")["turn_number"] == 0


def test_valid_story_progress_transition_persists_and_changes_next_contract():
    client = TestClient(app)
    session_id = _active_session(client)
    manager = SessionManager()
    story_plan = manager.storage.read_json(session_id, "story_plan.json")
    story_plan["act_structure"] = [
        {"id": "act_1", "goal": "завязка"},
        {"id": "act_2", "goal": "середина"},
    ]
    manager.storage.write_json(session_id, "story_plan.json", story_plan)

    player_input = "(сделать выбор, завершающий завязку)"
    turn_id = _pending_turn(client, session_id, player_input)
    response = _long_scene_response(player_input)
    response["proposed_updates"]["continuity_patch"] = {
        "story_progress_patch": {
            "current_act_index": 1,
            "current_beat": "первые последствия",
            "reason": "героиня приняла необратимое решение",
            "source_in_scene": "финальное действие сцены",
        }
    }

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_id, "scene_response": response},
    )

    assert applied.status_code == 200, applied.text
    continuity = manager.storage.read_json(session_id, "continuity.json")
    assert continuity["story_progress"]["current_act_index"] == 1
    assert continuity["story_progress"]["entered_turn"] == 1
    contract = build_scene_contract(manager.get_memory(session_id), player_input="(идти дальше)")
    assert contract["story_compass"]["active_act"][0]["id"] == "act_2"
