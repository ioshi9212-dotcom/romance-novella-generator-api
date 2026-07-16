from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from fastapi.testclient import TestClient

from app.main import app
from app.session_manager import SessionManager
from tests.test_smoke import _long_scene_response, _valid_bootstrap


PAIR_ID = "coworker_01__pc_01"


def _create_active_session(client: TestClient) -> str:
    created = client.post(
        "/api/v1/sessions",
        json={
            "genre": "mystery drama",
            "setting_request": "rainy night office",
            "protagonist_request": "guarded adult heroine",
            "romance_request": "slow burn",
            "mode": "gpt_actions",
        },
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    assert client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": _valid_bootstrap()},
    ).status_code == 200
    assert client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-confirm",
        json={"confirmation_text": "подтверждаю"},
    ).status_code == 200
    return session_id


def _read_full_prompt(client: TestClient, session_id: str, turn_payload: dict) -> str:
    chunks = [turn_payload["scene_prompt"]]
    for chunk_index in range(1, int(turn_payload["prompt_chunk_count"])):
        response = client.get(
            f"/api/v1/sessions/{session_id}/turn-prompt-chunk",
            params={"turn_id": turn_payload["turn_id"], "chunk_index": chunk_index},
        )
        assert response.status_code == 200, response.text
        chunk = response.json()
        assert chunk["chunk_index"] == chunk_index
        chunks.append(chunk["scene_prompt_chunk"])
    prompt = "".join(chunks)
    expected_hash = turn_payload["diagnostics"]["prompt_transport"]["scene_prompt_sha256"]
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == expected_hash
    return prompt


def _response_for_turn(player_input: str, turn_number: int) -> dict:
    response = deepcopy(_long_scene_response(player_input))
    response["summary"] = f"Compact summary turn {turn_number}: Mira and Ren advance the office anomaly."
    response["important_facts"] = [f"Durable fact turn {turn_number}"]
    response["scene"]["player_options"]["thoughts"][0] = f"VISIBLE_ONLY_OPTION_{turn_number}"
    response["scene"]["header"]["time"] = f"22:{turn_number:02d}"

    updates = response["proposed_updates"]
    updates["scene_state_patch"].update(
        {
            "time": f"22:{turn_number:02d}",
            "scene_state": f"Saved scene state turn {turn_number}",
            "transient_debug_payload": f"MUST_NOT_SAVE_{turn_number}",
        }
    )
    updates["continuity_patch"] = {
        "open_threads": [f"thread-turn-{turn_number}"],
        "notes": [f"compact-note-{turn_number}"],
    }
    updates["relationship_patches"] = [
        {
            "pair_id": PAIR_ID,
            "change_type": "observed_follow_through",
            "entry": f"Relationship event turn {turn_number}",
            "reason": f"Ren saw a concrete action on turn {turn_number}.",
            "source_in_scene": f"Visible exchange turn {turn_number}.",
            "scores": {"trust": min(70, 32 + turn_number), "tension": max(30, 58 - turn_number)},
            "from_character_id": "coworker_01",
            "to_character_id": "pc_01",
            "direction_patch": {
                "current_view": f"Ren updates his view after turn {turn_number}",
                "current_expectation": "Mira may act without explaining herself",
            },
        }
    ]
    updates["knowledge_patches"] = [
        {
            "character_id": "coworker_01",
            "reason": f"Ren witnessed the event on turn {turn_number}.",
            "source_in_scene": f"Visible evidence turn {turn_number}.",
            "add_knows": [f"Durable fact turn {turn_number}"],
            "add_observations": [f"Observed anomaly turn {turn_number}"],
        }
    ]
    updates["npc_state_patches"] = [
        {
            "character_id": "coworker_01",
            "reason": f"The exchange changed Ren's immediate pressure on turn {turn_number}.",
            "source_in_scene": f"Ren reacts visibly on turn {turn_number}.",
            "current_mood": f"controlled concern turn {turn_number}",
            "current_urge": "keep watching instead of accepting the first explanation",
            "behavior_mode": "dry direct pressure without taking Mira's choice",
            "unresolved_emotion": "concern mixed with irritation",
            "next_self_action_if_ignored": "check the corridor camera alone",
            "change_stage": "trying" if turn_number % 3 else "relapsed",
        }
    ]
    updates["new_or_updated_characters"] = []
    if turn_number == 4:
        updates["new_or_updated_characters"] = [
            {
                "id": "coworker_01",
                "name": "Wrong Replacement",
                "role": "coworker",
                "introduced": True,
                "known_to_player": True,
            }
        ]
    return response


def test_thirty_real_turns_preserve_durable_state_and_run_recurring_audits():
    client = TestClient(app)
    session_id = _create_active_session(client)
    checkpoint_prompts: dict[int, str] = {}
    rejection_seen = False

    for turn_number in range(1, 31):
        player_input = f"(выполнить проверочный ход {turn_number}, не принимая крупных решений)"
        turn = client.post(
            f"/api/v1/sessions/{session_id}/turn",
            json={"player_input": player_input, "mode": "gpt_actions"},
        )
        assert turn.status_code == 200, turn.text
        turn_payload = turn.json()
        prompt = _read_full_prompt(client, session_id, turn_payload)
        if turn_number in {11, 16, 21}:
            checkpoint_prompts[turn_number] = prompt

        applied = client.post(
            f"/api/v1/sessions/{session_id}/apply-turn-result",
            json={"turn_id": turn_payload["turn_id"], "scene_response": _response_for_turn(player_input, turn_number)},
        )
        assert applied.status_code == 200, applied.text
        applied_payload = applied.json()
        if turn_number == 4:
            rejection_seen = any(
                item.get("target") == "characters.coworker_01"
                for item in applied_payload.get("rejected", [])
                if isinstance(item, dict)
            )

    final_turn = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": "(проверить состояние после тридцатого хода)", "mode": "gpt_actions"},
    )
    assert final_turn.status_code == 200, final_turn.text
    checkpoint_prompts[31] = _read_full_prompt(client, session_id, final_turn.json())

    manager = SessionManager()
    bundle = manager.get_memory(session_id)
    raw_continuity = manager.storage.read_json(session_id, "continuity.json")
    raw_scene_history = manager.storage.read_json(session_id, "scene_history.json")
    raw_turns = manager.storage.read_json(session_id, "turns.json")
    current_state = bundle["current_state"]
    action_continuity = bundle["continuity"]
    scene_history = bundle["scene_history"]
    turns = bundle["turns"]
    relationship = bundle["relationships"][PAIR_ID]
    knowledge = bundle["knowledge"]["coworker_01"]
    npc_state = bundle["npc_state"]["coworker_01"]

    assert rejection_seen
    assert bundle["characters"]["coworker_01"]["name"] == "Ren Ashford"
    assert current_state["turn_number"] == 30
    assert current_state["last_player_input"].endswith("ход 30, не принимая крупных решений)")
    assert current_state["scene_state"] == "Saved scene state turn 30"
    assert "transient_debug_payload" not in current_state
    assert current_state["status"]["custom"][0]["id"] == "story_slot_1"

    assert relationship["history"][-1]["turn"] == 30
    assert relationship["a_to_b"]["current_view"] == "Ren updates his view after turn 30"
    assert any(item.get("turn") == 30 for item in knowledge["history"])
    assert "Durable fact turn 30" in knowledge["knows"]
    assert npc_state["last_updated_turn"] == 30
    assert npc_state["current_mood"] == "controlled concern turn 30"

    expected_scene_turns = [25, 26, 27, 28, 29, 30]
    expected_turn_turns = [23, 24, 25, 26, 27, 28, 29, 30]
    assert [item["turn"] for item in scene_history] == expected_scene_turns
    assert [item["turn"] for item in raw_scene_history] == expected_scene_turns
    assert [item["turn"] for item in turns] == expected_turn_turns
    assert [item["turn"] for item in raw_turns] == expected_turn_turns
    for raw_entry, action_entry in zip(raw_scene_history, scene_history):
        assert action_entry["summary"] == raw_entry["summary"]
        assert action_entry["important_facts"] == raw_entry["important_facts"]
        assert len(action_entry["body_excerpt"]) <= len(raw_entry["body_excerpt"])
    for raw_entry, action_entry in zip(raw_turns, turns):
        assert action_entry["player_input"] == raw_entry["player_input"]
        assert action_entry["summary"] == raw_entry["summary"]

    assert len(raw_continuity["memory_chunks"]) <= 12
    archived_text = json.dumps(raw_continuity["memory_chunks"], ensure_ascii=False)
    assert "Durable fact turn 1" in archived_text
    assert "Durable fact turn 24" in archived_text

    runtime_text = json.dumps(
        {"scene_history": raw_scene_history, "turns": raw_turns, "continuity": raw_continuity},
        ensure_ascii=False,
    )
    assert "rendered_text" not in runtime_text
    assert "scene_response" not in runtime_text
    assert "player_options" not in runtime_text
    assert "VISIBLE_ONLY_OPTION_1" not in runtime_text
    assert "MUST_NOT_SAVE_1" not in runtime_text

    audits = raw_continuity["persistence_audits"]
    assert [item["turn"] for item in audits] == [10, 15, 20, 30]
    assert all(item["status"] == "passed" for item in audits)
    assert all(all(item["checks"].values()) for item in audits)
    assert audits[-1]["triggers"] == ["state_recovery_audit", "state_compaction_cleanup"]
    assert [item["turn"] for item in action_continuity["persistence_audits"]] == [20, 30]

    maintenance_types = [(item["turn"], item["type"]) for item in raw_continuity["maintenance_events"]]
    assert (10, "state_recovery_audit") in maintenance_types
    assert (15, "state_compaction_cleanup") in maintenance_types
    assert (20, "state_recovery_audit") in maintenance_types
    assert (30, "state_recovery_audit") in maintenance_types
    assert (30, "state_compaction_cleanup") in maintenance_types

    assert '"state_recovery_audit_due":true' in checkpoint_prompts[11]
    assert '"state_compaction_cleanup_due":true' in checkpoint_prompts[16]
    assert '"state_recovery_audit_due":true' in checkpoint_prompts[21]
    assert '"state_recovery_audit_due":true' in checkpoint_prompts[31]
    assert '"state_compaction_cleanup_due":true' in checkpoint_prompts[31]
    assert "Durable fact turn 1" in checkpoint_prompts[31]
    assert '"status":"passed"' in checkpoint_prompts[31]
