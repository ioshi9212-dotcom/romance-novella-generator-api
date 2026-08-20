from __future__ import annotations

from pathlib import Path

import pytest

from app.scene_rules_compiler import (
    MAX_COMPILED_RULE_CHARS,
    RULE_SOURCES,
    SceneRulesCompileError,
    compile_scene_rules,
    scene_rules_diagnostics,
)
from app.turn_processor import COMPACT_SCENE_WRITER_PROMPT, build_scene_prompt


def _minimal_rule_tree(root: Path) -> None:
    for source in RULE_SOURCES:
        path = root / source.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Test source\n\n" + "\n".join(f"- {anchor}" for anchor in source.required_anchors),
            encoding="utf-8",
        )


def test_compiler_loads_canonical_sources_in_stable_order():
    compiled = compile_scene_rules()

    positions = []
    for source in RULE_SOURCES:
        marker = f"## {source.section_id}\nSOURCE: {source.relative_path}"
        assert marker in compiled
        positions.append(compiled.index(marker))
    assert positions == sorted(positions)

    required_meaning = [
        "не ставит мир на паузу",
        "не консультанты",
        "не читают мысли",
        "wrong_belief",
        "a_to_b",
        "b_to_a",
        "direction_patch",
        "не зеркал",
        "hidden_core",
        "полная карточка",
        "Психологическая инерция",
        "✦ Что можно сделать",
        "✦ Что можно сказать",
        "✦ Мысли",
        "proposed_updates",
    ]
    for phrase in required_meaning:
        assert phrase in compiled

    assert "заранее сохраняется только seed" not in compiled
    assert len(compiled) <= MAX_COMPILED_RULE_CHARS


def test_backward_compatible_prompt_constant_is_compiled_not_handwritten():
    assert COMPACT_SCENE_WRITER_PROMPT == compile_scene_rules()

    source = Path("app/turn_processor.py").read_text(encoding="utf-8")
    assert "COMPACT_SCENE_WRITER_PROMPT = compile_scene_rules()" in source
    assert "Агентность персонажей/NPC:" not in source
    assert "Романтическая мистика / фэнтези / лёгкий хоррор:" not in source


def test_scene_prompt_has_one_tool_flow_rules_block_and_contract():
    prompt = build_scene_prompt(
        {
            "contract_version": "novella.scene_contract.v1",
            "session_id": "session_test",
            "current_frame": {"player_character_id": "pc_01", "last_player_input": "(молчать)"},
            "loaded_characters": [],
            "loaded_relationships": [],
            "knowledge_boundaries": [],
        }
    )

    assert prompt.count("RUNTIME_SCENE_RULES:") == 1
    assert prompt.count("SCENE_CONTRACT_JSON:") == 1
    assert prompt.index("RUNTIME_SCENE_RULES:") < prompt.index("SCENE_CONTRACT_JSON:")
    assert "SOURCE: prompts/npc_rules.md" in prompt
    assert '"session_id":"session_test"' in prompt


def test_compiler_fails_if_source_is_missing_or_stale(tmp_path: Path):
    _minimal_rule_tree(tmp_path)
    assert compile_scene_rules(tmp_path)

    missing_source = RULE_SOURCES[0]
    (tmp_path / missing_source.relative_path).unlink()
    with pytest.raises(SceneRulesCompileError, match="Missing scene rule source"):
        compile_scene_rules(tmp_path)

    _minimal_rule_tree(tmp_path)
    stale_source = RULE_SOURCES[1]
    (tmp_path / stale_source.relative_path).write_text("# stale\nonly one phrase", encoding="utf-8")
    with pytest.raises(SceneRulesCompileError, match="is stale"):
        compile_scene_rules(tmp_path)


def test_scene_rule_diagnostics_are_traceable_and_bounded():
    diagnostics = scene_rules_diagnostics()

    assert diagnostics["source_count"] == len(RULE_SOURCES)
    assert diagnostics["sources"] == [source.relative_path for source in RULE_SOURCES]
    assert diagnostics["compiled_chars"] == len(COMPACT_SCENE_WRITER_PROMPT)
    assert diagnostics["compiled_chars"] <= diagnostics["max_compiled_chars"]
    assert len(diagnostics["compiled_sha256"]) == 64
    assert set(diagnostics["source_sha256"]) == set(diagnostics["sources"])
    assert all(len(value) == 64 for value in diagnostics["source_sha256"].values())


def test_canonical_relationship_and_hidden_rules_match_current_architecture():
    relationship_rules = Path("prompts/relationship_rules.md").read_text(encoding="utf-8")
    hidden_rules = Path("rules/hidden_character_rules.md").read_text(encoding="utf-8")

    assert all(token in relationship_rules for token in ("shared", "a_to_b", "b_to_a", "direction_patch"))
    assert "не зеркалится" in relationship_rules
    assert all(token in hidden_rules for token in ("hidden_core", "полная карточка", "available_to_scene=false"))
    assert "заранее сохраняется только seed" not in hidden_rules
