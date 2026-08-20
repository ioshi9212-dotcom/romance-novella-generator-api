from __future__ import annotations

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.character_profiles import prepare_bootstrap_cast
from app.validators import validate_bootstrap_result
from tests.test_smoke import _valid_bootstrap


ALLOWED_DIRECTIONAL_SCORE_KEYS = {
    "trust",
    "attachment",
    "attraction",
    "respect",
    "resentment",
    "fear",
    "jealousy",
    "dependency",
    "protectiveness",
}


def test_repairs_string_connections_incomplete_social_triggers_and_legacy_directional_scores():
    bootstrap = _valid_bootstrap()

    bootstrap["characters"]["pc_01"]["connections"] = [
        "Ren is her coworker and notices when she avoids going home",
    ]
    bootstrap["characters"]["coworker_01"]["connections"] = [
        "Mira is his coworker",
        {"character_id": "pc_01", "relation": "coworker"},
    ]

    bootstrap["characters"]["pc_01"]["social_triggers"] = [
        {"usual_reaction": "отвечает суше и закрывается"},
        {"behavior": "человек давит и требует немедленного ответа"},
    ]
    bootstrap["characters"]["coworker_01"]["social_triggers"] = [
        {"reaction": "задаёт прямой вопрос"},
        {"trigger": "человек внезапно исчезает посреди проблемы", "meaning": "ему не доверяют"},
    ]

    relationship = bootstrap["relationships"]["coworker_01__pc_01"]
    relationship["a_to_b"] = {
        "scores": {
            "trust": 41,
            "overall": 60,
            "tension": 72,
            "curiosity": 68,
            "romantic_interest": 35,
            "presence_pull": 44,
        }
    }
    relationship["b_to_a"] = {
        "scores": {
            "respect": 52,
            "overall": 55,
            "romantic_interest": 27,
        }
    }

    normalized = normalize_bootstrap_json(bootstrap)
    prepare_bootstrap_cast(normalized)
    errors = validate_bootstrap_result(normalized)

    relevant_errors = [
        error
        for error in errors
        if "connections" in error
        or "social_triggers" in error
        or "additional properties" in error.lower()
        or ".scores" in error
    ]
    assert relevant_errors == []

    for card in normalized["characters"].values():
        assert card["connections"]
        assert all(isinstance(item, dict) for item in card["connections"])
        assert len(card["social_triggers"]) >= 2
        assert all(
            trigger.get("behavior")
            and trigger.get("interpretation")
            and trigger.get("usual_reaction")
            for trigger in card["social_triggers"]
        )

    repaired_relationship = normalized["relationships"]["coworker_01__pc_01"]
    for direction in ("a_to_b", "b_to_a"):
        scores = repaired_relationship[direction]["scores"]
        assert set(scores) <= ALLOWED_DIRECTIONAL_SCORE_KEYS

    assert repaired_relationship["a_to_b"]["scores"]["attraction"] == 35
    assert repaired_relationship["b_to_a"]["scores"]["attraction"] == 27
