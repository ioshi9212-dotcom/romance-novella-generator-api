from __future__ import annotations

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.validators import validate_bootstrap_result
from tests.test_smoke import _valid_bootstrap


def test_normalizer_repairs_text_ages_and_placeholder_scene_state():
    bootstrap = _valid_bootstrap()
    bootstrap["characters"]["pc_01"]["age"] = "25 лет"
    bootstrap["characters"]["coworker_01"]["age"] = "неизвестно"
    bootstrap["current_state"]["scene_state"] = "начало истории"
    bootstrap["current_state"]["scene_goal"] = "Мира задерживается после смены, пока Рен замечает странное мерцание лампы."

    normalized = normalize_bootstrap_json(bootstrap)

    assert normalized["characters"]["pc_01"]["age"] == 25
    assert normalized["characters"]["coworker_01"]["age"] is None
    assert normalized["current_state"]["scene_state"] == bootstrap["current_state"]["scene_goal"]

    errors = validate_bootstrap_result(normalized)
    assert not [error for error in errors if ".age" in error]
    assert not [error for error in errors if "current_state.scene_state" in error]


def test_normalizer_does_not_guess_age_ranges():
    bootstrap = _valid_bootstrap()
    bootstrap["characters"]["pc_01"]["age"] = "25–30 лет"

    normalized = normalize_bootstrap_json(bootstrap)

    assert normalized["characters"]["pc_01"]["age"] is None


def test_scene_state_uses_opening_intent_when_scene_goal_is_generic():
    bootstrap = _valid_bootstrap()
    bootstrap["current_state"]["scene_state"] = "начало истории"
    bootstrap["current_state"]["scene_goal"] = "начать первую сцену"
    bootstrap["story_plan"]["opening_scene_intent"] = "Открыть вечер в закрытом офисе: телефон требует ответа, а свет реагирует на напряжение Миры."

    normalized = normalize_bootstrap_json(bootstrap)

    assert normalized["current_state"]["scene_state"] == bootstrap["story_plan"]["opening_scene_intent"]
