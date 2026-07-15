from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.director_bible import build_director_guidance, prepare_director_bible
from app.main import app
from app.scene_contract_builder import build_scene_contract
from app.session_manager import SessionManager
from app.turn_processor import COMPACT_SCENE_WRITER_PROMPT
from tests.test_smoke import _long_scene_response, _valid_bootstrap


PAIR_ID = "coworker_01__pc_01"


def _create_active_session(client: TestClient) -> str:
    created = client.post(
        "/api/v1/sessions",
        json={
            "genre": "urban mystery",
            "setting_request": "rainy office",
            "protagonist_request": "guarded adult heroine",
            "romance_request": "slow burn",
            "mode": "gpt_actions",
        },
    )
    assert created.status_code == 200, created.text
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


def _read_full_prompt(client: TestClient, session_id: str, payload: dict) -> str:
    chunks = [payload["scene_prompt"]]
    for chunk_index in range(1, int(payload.get("prompt_chunk_count") or 1)):
        chunk = client.get(
            f"/api/v1/sessions/{session_id}/turn-prompt-chunk",
            params={"turn_id": payload["turn_id"], "chunk_index": chunk_index},
        )
        assert chunk.status_code == 200, chunk.text
        chunks.append(chunk.json()["scene_prompt_chunk"])
    return "".join(chunks)


def _scene_for_turn(player_input: str, turn_number: int) -> dict:
    response = _long_scene_response(player_input)
    unsaved_body_marker = f"UNSAVED_FULL_BODY_TURN_{turn_number}"
    response["scene"]["body"] += "\n\n" + ("Поздняя часть полного текста. " * 40) + unsaved_body_marker
    response["scene"]["player_options"]["thoughts"][0] = f"UNSAVED_PLAYER_OPTION_TURN_{turn_number}"
    response["scene"]["header"]["time"] = f"23:{turn_number:02d}"
    response["scene"]["header"]["scene_state"] = f"видимое состояние сцены после хода {turn_number}"
    response["summary"] = f"Краткое устойчивое резюме хода {turn_number}."
    response["important_facts"] = [f"Устойчивый факт хода {turn_number}"]
    response["safety_checks"]["notes"] = [f"UNSAVED_SAFETY_NOTE_TURN_{turn_number}"]

    updates = response["proposed_updates"]
    updates["scene_state_patch"] = {
        **updates["scene_state_patch"],
        "time": f"23:{turn_number:02d}",
        "scene_state": f"состояние сохранено после хода {turn_number}",
        "scene_goal": f"продолжить последствия хода {turn_number}",
        "active_character_ids": ["pc_01", "coworker_01"],
        "nearby_character_ids": [],
    }
    updates["continuity_patch"] = {
        "open_threads": [f"нить хода {turn_number}"],
        "notes": [f"заметка хода {turn_number}"],
        "rendered_text": f"NEVER_STORE_CONTINUITY_PAYLOAD_{turn_number}",
    }
    updates["relationship_patches"] = [
        {
            "pair_id": PAIR_ID,
            "change_type": "turn_pressure",
            "entry": f"Изменение отношений на ходу {turn_number}",
            "reason": f"Персонажи обменялись значимой реакцией на ходу {turn_number}.",
            "source_in_scene": f"Реплика и видимая реакция Рена в сцене хода {turn_number}.",
            "from_character_id": "coworker_01",
            "to_character_id": "pc_01",
            "direction_patch": {
                "current_view": f"Рен учитывает результат хода {turn_number}",
                "current_need": f"добиться ясности после хода {turn_number}",
                "scores": {"trust": 40 + turn_number, "respect": 45 + turn_number},
            },
            "shared_patch": {
                "status": f"напряжённая динамика после хода {turn_number}",
                "last_major_event": f"ход {turn_number}",
            },
        }
    ]
    updates["knowledge_patches"] = [
        {
            "character_id": "coworker_01",
            "reason": f"Рен лично наблюдал событие хода {turn_number}.",
            "source_in_scene": f"Видимый факт и реплика в сцене хода {turn_number}.",
            "add_knows": [f"Рен знает устойчивый факт хода {turn_number}"],
            "add_observations": [f"наблюдение хода {turn_number}"],
            "add_assumptions": [f"предположение хода {turn_number}"],
            "add_wrong_beliefs": [f"ошибочное убеждение хода {turn_number}"],
            "add_open_questions": [f"вопрос хода {turn_number}"],
        }
    ]
    updates["npc_state_patches"] = [
        {
            "character_id": "coworker_01",
            "reason": f"Сцена изменила текущий импульс Рена на ходу {turn_number}.",
            "source_in_scene": f"Рен реагирует и выбирает следующий шаг в сцене хода {turn_number}.",
            "current_mood": f"собранное раздражение {turn_number}",
            "current_urge": f"проверить новую деталь {turn_number}",
            "behavior_mode": "сухая прямота без лишней мягкости",
            "unresolved_emotion": f"невыраженная тревога {turn_number}",
            "next_self_action_if_ignored": f"самостоятельно проверить коридор после хода {turn_number}",
            "change_stage": "defensive" if turn_number < 8 else "trying",
        }
    ]
    updates["new_or_updated_characters"] = []
    updates["director_bible_patches"] = {}
    if turn_number == 1:
        updates["director_bible_patches"] = {
            "event_updates": [
                {
                    "id": "event_01",
                    "status": "triggered",
                    "reason": "Стартовое давление вошло в сцену.",
                    "source_in_scene": "Рен заметил физическую аномалию рядом с Мирой.",
                }
            ]
        }
    elif turn_number == 2:
        updates["director_bible_patches"] = {
            "event_updates": [
                {
                    "id": "event_01",
                    "status": "completed",
                    "reason": "Стартовое событие дало видимый след и последствие.",
                    "source_in_scene": "Связь помех с состоянием Миры стала общей наблюдаемой проблемой.",
                }
            ]
        }
    return response


def test_fifteen_turns_persist_only_durable_state_and_run_real_maintenance():
    client = TestClient(app)
    session_id = _create_active_session(client)
    manager = SessionManager()
    prompt_after_audit = ""

    for turn_number in range(1, 16):
        player_input = f"(последовательный тестовый ход {turn_number})"
        turn = client.post(
            f"/api/v1/sessions/{session_id}/turn",
            json={"player_input": player_input, "mode": "gpt_actions"},
        )
        assert turn.status_code == 200, turn.text
        turn_payload = turn.json()
        full_prompt = _read_full_prompt(client, session_id, turn_payload)
        if turn_number == 11:
            prompt_after_audit = full_prompt

        applied = client.post(
            f"/api/v1/sessions/{session_id}/apply-turn-result",
            json={"turn_id": turn_payload["turn_id"], "scene_response": _scene_for_turn(player_input, turn_number)},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["status"] == "applied", applied.text

        raw_continuity = manager.storage.read_json(session_id, "continuity.json", default={})
        raw_state = manager.storage.read_json(session_id, "current_state.json", default={})
        if turn_number == 9:
            assert not raw_continuity.get("state_recovery_audits")
        if turn_number == 10:
            audit = raw_continuity["state_recovery_audits"][-1]
            assert audit["turn"] == 10
            assert audit["status"] == "ok", audit
            assert audit["issue_count"] == 0
            assert audit["counts"]["provenance_records_checked"] > 0
            assert raw_state["maintenance"]["state_recovery_audit_due"] is False
            assert raw_state["maintenance"]["state_recovery_audit_completed_turn"] == 10

    assert '"state_recovery_audit_due":false' in prompt_after_audit
    assert '"state_recovery_audit_completed_turn":10' in prompt_after_audit

    current_state = manager.storage.read_json(session_id, "current_state.json")
    scene_history = manager.storage.read_json(session_id, "scene_history.json")
    turns = manager.storage.read_json(session_id, "turns.json")
    continuity = manager.storage.read_json(session_id, "continuity.json")
    knowledge = manager.storage.read_knowledge(session_id)
    relationships = manager.storage.read_relationships(session_id)
    npc_state = manager.storage.read_json(session_id, "npc_state.json")
    director_bible = manager.storage.read_json(session_id, "director_bible.json")

    assert current_state["turn_number"] == 15
    assert current_state["last_player_input"] == "(последовательный тестовый ход 15)"
    assert current_state["scene_state"] == "состояние сохранено после хода 15"
    assert current_state["maintenance"]["state_compaction_cleanup_due"] is False
    assert current_state["maintenance"]["state_compaction_cleanup_completed_turn"] == 15
    assert current_state["maintenance"]["state_compaction_cleanup_status"] == "ok"

    assert len(scene_history) <= 6
    assert len(turns) <= 8
    assert scene_history[-1]["turn"] == 15
    assert turns[-1]["turn"] == 15
    assert continuity["memory_chunks"]
    assert any(chunk.get("type") == "state_compaction_cleanup" for chunk in continuity["memory_chunks"])
    assert continuity["state_compaction_reports"][-1]["turn"] == 15
    assert continuity["state_compaction_reports"][-1]["status"] == "ok"

    coworker_knowledge = knowledge["coworker_01"]
    assert "Рен знает устойчивый факт хода 1" in coworker_knowledge["knows"]
    assert "Рен знает устойчивый факт хода 15" in coworker_knowledge["knows"]
    assert any(item.get("text") == "ошибочное убеждение хода 15" and item.get("turn") == 15 for item in coworker_knowledge["wrong_beliefs"] if isinstance(item, dict))
    assert all(item.get("source_in_scene") for item in coworker_knowledge["known_facts"] if isinstance(item, dict) and item.get("turn"))

    relationship = relationships[PAIR_ID]
    assert relationship["b_to_a"]["current_view"] == "Рен учитывает результат хода 15"
    assert relationship["shared"]["last_major_event"] == "ход 15"
    assert len(relationship["history"]) == 15
    assert [item["turn"] for item in relationship["history"]] == list(range(1, 16))
    assert len(relationship["shared"]["recent_changes"]) == 10

    coworker_runtime = npc_state["coworker_01"]
    assert coworker_runtime["last_updated_turn"] == 15
    assert coworker_runtime["current_mood"] == "собранное раздражение 15"
    assert len(coworker_runtime["history"]) == 12
    assert coworker_runtime["history"][-1]["turn"] == 15
    assert coworker_runtime["history"][0]["turn"] == 4

    event_01 = next(item for item in director_bible["event_queue"] if item["id"] == "event_01")
    assert event_01["status"] == "completed"
    assert [item["turn"] for item in director_bible["history"] if item.get("id") == "event_01"] == [1, 2]

    maintenance_events = {(item.get("turn"), item.get("type"), item.get("status")) for item in continuity["maintenance_events"]}
    assert (10, "state_recovery_audit", "ok") in maintenance_events
    assert (15, "state_compaction_cleanup", "ok") in maintenance_events

    runtime_payload = json.dumps(
        {
            "current_state": current_state,
            "scene_history": scene_history,
            "turns": turns,
            "continuity": continuity,
            "knowledge": knowledge,
            "relationships": relationships,
            "npc_state": npc_state,
            "director_bible": director_bible,
        },
        ensure_ascii=False,
    )
    for turn_number in range(1, 16):
        assert f"UNSAVED_FULL_BODY_TURN_{turn_number}" not in runtime_payload
        assert f"UNSAVED_PLAYER_OPTION_TURN_{turn_number}" not in runtime_payload
        assert f"UNSAVED_SAFETY_NOTE_TURN_{turn_number}" not in runtime_payload
        assert f"NEVER_STORE_CONTINUITY_PAYLOAD_{turn_number}" not in runtime_payload
    assert "rendered_text" not in json.dumps(scene_history, ensure_ascii=False)
    assert "scene_response" not in json.dumps(turns, ensure_ascii=False)

    contract = build_scene_contract(manager.get_memory(session_id))
    assert contract["maintenance"]["state_recovery_audit_due"] is False
    assert contract["maintenance"]["state_recovery_audit_completed_turn"] == 10
    assert contract["maintenance"]["state_compaction_cleanup_due"] is False
    assert contract["maintenance"]["state_compaction_cleanup_completed_turn"] == 15


def test_semantically_invalid_updates_are_rejected_and_not_persisted():
    client = TestClient(app)
    session_id = _create_active_session(client)
    manager = SessionManager()
    player_input = "(проверить отклонение недопустимых патчей)"
    turn = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": player_input, "mode": "gpt_actions"},
    )
    assert turn.status_code == 200, turn.text

    response = _scene_for_turn(player_input, 1)
    response["proposed_updates"]["knowledge_patches"] = [
        {
            "character_id": "ghost_knowledge",
            "reason": "Попытка записать знание несуществующему персонажу.",
            "source_in_scene": "Тестовый источник.",
            "add_knows": ["ЭТО НЕ ДОЛЖНО СОХРАНИТЬСЯ"],
        }
    ]
    response["proposed_updates"]["npc_state_patches"] = [
        {
            "character_id": "pc_01",
            "reason": "Игрок не должен получать npc_state.",
            "source_in_scene": "Тестовый источник.",
            "current_mood": "ЭТО НЕ ДОЛЖНО СОХРАНИТЬСЯ",
        }
    ]
    response["proposed_updates"]["new_or_updated_characters"] = [{"id": "coworker_01", "age": 99}]
    response["proposed_updates"]["relationship_patches"] = [
        {
            "pair_id": "ghost_a__ghost_b",
            "change_type": "invalid_pair",
            "entry": "Несуществующая пара",
            "reason": "Тест неизвестной пары.",
            "source_in_scene": "Тестовый источник.",
            "from_character_id": "ghost_a",
            "to_character_id": "ghost_b",
            "direction_patch": {"current_view": "не должно сохраниться"},
        }
    ]

    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn.json()["turn_id"], "scene_response": response},
    )
    assert applied.status_code == 200, applied.text
    payload = applied.json()
    assert payload["status"] == "partially_applied"
    rejected_targets = {item["target"] for item in payload["rejected"]}
    assert "knowledge.ghost_knowledge" in rejected_targets
    assert "npc_state.pc_01" in rejected_targets
    assert "characters.coworker_01" in rejected_targets
    assert "relationships.ghost_a__ghost_b" in rejected_targets

    assert "ghost_knowledge" not in manager.storage.read_knowledge(session_id)
    assert "pc_01" not in manager.storage.read_json(session_id, "npc_state.json", default={})
    assert manager.storage.read_characters(session_id)["coworker_01"]["age"] == 28
    assert "ghost_a__ghost_b" not in manager.storage.read_relationships(session_id)
    assert manager.storage.read_json(session_id, "current_state.json")["turn_number"] == 1


def test_director_prompt_calibrates_sparse_sarcasm():
    bootstrap = _valid_bootstrap()
    prepare_director_bible(bootstrap)
    guidance = build_director_guidance(bootstrap)

    assert "5–7%" in COMPACT_SCENE_WRITER_PROMPT
    assert "не в каждом абзаце" in COMPACT_SCENE_WRITER_PROMPT
    assert "5–7%" in guidance["rules"]["sarcasm_calibration"]
    assert "не превращай всех персонажей" in guidance["rules"]["sarcasm_calibration"]
