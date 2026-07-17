from fastapi.testclient import TestClient

from app.main import app
from app.scene_contract_builder import build_scene_contract
from app.session_manager import SessionManager
from tests.test_smoke import _long_scene_response, _valid_bootstrap


def test_thirty_turn_gameplay_keeps_progress_cast_and_episode_memory():
    client = TestClient(app)
    created = client.post(
        "/api/v1/sessions",
        json={"raw_start_text": "Мистическая романтика; остальное придумай сам.", "mode": "gpt_actions"},
    )
    session_id = created.json()["session_id"]
    bootstrap = _valid_bootstrap()
    bootstrap["story_plan"]["act_structure"] = [
        {"id": "act_1", "goal": "завязка"},
        {"id": "act_2", "goal": "цена сближения"},
        {"id": "act_3", "goal": "развязка"},
    ]
    preview = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": bootstrap},
    )
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-confirm",
        json={"confirmation_text": "подтверждаю"},
    )
    assert confirmed.status_code == 200, confirmed.text

    for turn_number in range(1, 31):
        player_input = f"(длинный игровой ход {turn_number})"
        turn = client.post(
            f"/api/v1/sessions/{session_id}/turn",
            json={"player_input": player_input, "mode": "gpt_actions"},
        )
        assert turn.status_code == 200, turn.text
        response = _long_scene_response(player_input)
        response["summary"] = f"Устойчивое событие длинной игры {turn_number}."
        response["important_facts"] = [f"Факт длинной игры {turn_number}"]
        if turn_number in {10, 20}:
            response["proposed_updates"]["continuity_patch"] = {
                "story_progress_patch": {
                    "current_act_index": 1 if turn_number == 10 else 2,
                    "current_beat": f"поворот {turn_number}",
                    "reason": "накопленные последствия изменили фазу истории",
                    "source_in_scene": f"устойчивое событие хода {turn_number}",
                }
            }
        applied = client.post(
            f"/api/v1/sessions/{session_id}/apply-turn-result",
            json={"turn_id": turn.json()["turn_id"], "scene_response": response},
        )
        assert applied.status_code == 200, applied.text

    manager = SessionManager()
    raw_state = manager.storage.read_json(session_id, "current_state.json")
    raw_continuity = manager.storage.read_json(session_id, "continuity.json")
    bundle = manager.get_memory(session_id)
    contract = build_scene_contract(bundle, player_input="(продолжить после длинной игры)")

    assert raw_state["turn_number"] == 30
    assert raw_continuity["story_progress"]["current_act_index"] == 2
    assert [(item["turn_start"], item["turn_end"]) for item in raw_continuity["episode_summaries"]] == [
        (1, 15),
        (16, 30),
    ]
    assert contract["story_compass"]["active_act"][0]["act"] == 3
    assert contract["story_compass"]["active_act"][0]["goal"] == "развязка"
    assert contract["episode_summaries"][0]["scene_summaries"][0]["turn"] == 1
    assert {"pc_01", "coworker_01"}.issubset(bundle["characters"])
    assert bundle["relationships"]
    assert len(bundle["scene_history"]) <= 6
    assert len(bundle["turns"]) <= 8
    assert all("visible_scene_text" not in item for item in bundle["scene_history"])
    assert all("scene_response" not in item for item in bundle["turns"])
