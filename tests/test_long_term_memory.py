from app.scene_contract_builder import build_scene_contract
from app.state_updater import _auto_compact_runtime_history, _merge_continuity_patch
from tests.test_smoke import _valid_bootstrap


def test_sixty_turns_keep_non_overlapping_episode_summaries_and_load_them():
    scenes = []
    turns = []
    continuity = {}
    for turn in range(1, 61):
        scenes.append({
            "turn": turn,
            "summary": f"Событие хода {turn}",
            "important_facts": [f"Факт {turn}"],
            "witnesses": ["pc_01"],
        })
        turns.append({"turn": turn, "player_input": f"(действие {turn})", "summary": f"Итог {turn}"})
        scenes, turns, continuity, _ = _auto_compact_runtime_history(scenes, turns, continuity, turn)

    ranges = [(item["turn_start"], item["turn_end"]) for item in continuity["episode_summaries"]]
    assert ranges == [(1, 15), (16, 30), (31, 45), (46, 60)]
    assert continuity["episode_summaries"][0]["scene_summaries"][0]["turn"] == 1
    assert continuity["episode_summaries"][-1]["scene_summaries"][-1]["turn"] == 60

    bundle = _valid_bootstrap()
    bundle["continuity"] = continuity
    contract = build_scene_contract(bundle, player_input="(вспомнить, с чего всё началось)")
    loaded_ranges = [(item["turn_start"], item["turn_end"]) for item in contract["episode_summaries"]]
    assert loaded_ranges == ranges


def test_gpt_memory_compact_uses_one_canonical_key_and_migrates_legacy_data():
    continuity = {"gpt_memory_compacts": [{"turn": 3, "summary": "старое резюме"}]}

    merged = _merge_continuity_patch(
        continuity,
        {"memory_compact": {"summary": "новое резюме"}},
        turn_number=4,
    )

    assert "gpt_memory_compacts" not in merged
    assert [item["summary"] for item in merged["memory_compacts"]] == ["старое резюме", "новое резюме"]
