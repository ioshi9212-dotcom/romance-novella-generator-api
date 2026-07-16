from __future__ import annotations

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.character_profiles import prepare_bootstrap_cast
from app.director_bible import build_director_guidance, prepare_director_bible
from app.scene_rules_compiler import compile_scene_rules
from tests.test_smoke import _valid_bootstrap


def test_director_guidance_keeps_sarcasm_rare_and_character_specific():
    data = normalize_bootstrap_json(_valid_bootstrap())
    prepare_bootstrap_cast(data)
    prepare_director_bible(data)

    control = build_director_guidance(data)["tone_control"]

    assert "5–7%" in control["dry_sarcasm_target_share"]
    assert "иногда ноль" in control["preferred_dose"]
    assert "не одинаковая язвительность всех NPC" in control["source"]
    assert "не ставить в каждый абзац" in control["avoid"]


def test_scene_rules_compile_restrained_sarcasm_budget():
    compiled = compile_scene_rules()

    assert "5–7% видимого текста" in compiled
    assert "Это не квота" in compiled
    assert "иногда ни одной" in compiled
    assert "не вставляй их в каждый абзац" in compiled
