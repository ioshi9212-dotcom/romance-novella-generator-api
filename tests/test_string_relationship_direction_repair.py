from app.validators import validate_bootstrap_result


def test_string_relationship_directions_are_repaired_and_russian_text_is_preserved():
    data = {
        "protagonist": {"id": "lina_hart", "name": "Lina Hart", "role": "player_character"},
        "characters": {
            "lina_hart": {
                "id": "lina_hart", "name": "Lina Hart", "role": "player_character",
                "cast_status": "player", "introduced": True, "known_to_player": True,
                "show_in_preview": True, "available_to_scene": True,
            },
            "mason_lee": {
                "id": "mason_lee", "name": "Mason Lee", "role": "close friend",
                "cast_status": "known_core", "introduced": True, "known_to_player": True,
                "show_in_preview": True, "available_to_scene": True,
            },
        },
        "relationships": {
            "lina_hart__mason_lee": {
                "pair_id": "lina_hart__mason_lee",
                "character_a": "lina_hart",
                "character_b": "mason_lee",
                "a_to_b": "ценит",
                "b_to_a": "влюблён",
            }
        },
        "knowledge": {},
        "story_plan": {},
        "current_state": {"player_character_id": "lina_hart"},
    }

    errors = validate_bootstrap_result(data)
    relationship = data["relationships"]["lina_hart__mason_lee"]

    assert isinstance(relationship["a_to_b"], dict)
    assert isinstance(relationship["b_to_a"], dict)
    assert relationship["a_to_b"]["current_view"] == "ценит"
    assert relationship["b_to_a"]["current_view"] == "влюблён"
    assert relationship["a_to_b"]["scores"]
    assert relationship["b_to_a"]["scores"]
    assert not any("a_to_b" in error and "not of type 'object'" in error for error in errors)
    assert not any("b_to_a" in error and "not of type 'object'" in error for error in errors)
