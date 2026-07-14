from __future__ import annotations

import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def _schema(name: str) -> dict:
    return json.loads((ROOT_DIR / "schemas" / name).read_text(encoding="utf-8"))


def test_bootstrap_schema_exposes_shared_and_both_relationship_directions():
    bootstrap = _schema("bootstrap_output.schema.json")
    relation = bootstrap["properties"]["relationships"]["additionalProperties"]
    properties = relation["properties"]

    assert {"relationship_version", "shared", "a_to_b", "b_to_a"} <= set(properties)
    assert properties["relationship_version"]["enum"] == ["directed.v1"]

    shared_scores = properties["shared"]["properties"]["scores"]["properties"]
    assert {"tension", "closeness", "conflict_pressure"} == set(shared_scores)

    for key in ("a_to_b", "b_to_a"):
        direction = properties[key]["properties"]
        assert {
            "source_character_id",
            "target_character_id",
            "scores",
            "summary",
            "current_assumption",
            "current_need",
            "access_expectation",
            "unresolved_grievance",
        } <= set(direction)
        assert {
            "trust",
            "attachment",
            "attraction",
            "resentment",
            "respect",
            "fear",
            "jealousy",
            "dependency",
            "curiosity",
            "protectiveness",
        } == set(direction["scores"]["properties"])


def test_scene_schema_exposes_directed_patch_and_player_input_evidence():
    scene = _schema("scene_response.schema.json")
    patch = scene["properties"]["proposed_updates"]["properties"]["relationship_patches"]["items"]
    properties = patch["properties"]

    assert properties["scope"]["enum"] == ["directed", "shared", "legacy_symmetric"]
    assert {
        "source_character_id",
        "target_character_id",
        "player_input_evidence",
        "attraction",
        "resentment",
        "jealousy",
        "dependency",
        "protectiveness",
        "closeness",
        "conflict_pressure",
        "current_assumption",
        "current_need",
        "access_expectation",
        "unresolved_grievance",
    } <= set(properties)


def test_custom_gpt_instruction_keeps_directed_relationship_rules_under_limit():
    instructions = (ROOT_DIR / "gpt" / "custom_gpt_instructions.md").read_text(encoding="utf-8")

    assert len(instructions) <= 8000
    for marker in (
        "a_to_b",
        "b_to_a",
        "source_character_id",
        "target_character_id",
        "player_input_evidence",
        "Не зеркаль patch",
        "Давняя любовь NPC не означает взаимное влечение героини",
    ):
        assert marker in instructions
