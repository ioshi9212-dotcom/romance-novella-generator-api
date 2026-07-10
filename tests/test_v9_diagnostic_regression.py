from __future__ import annotations


def _base_bundle() -> dict:
    return {
        "current_state": {
            "player_character_id": "pc_01",
            "active_character_ids": ["pc_01"],
            "status": {
                "hunger": "норма",
                "fatigue": "низкая",
                "injuries": [],
                "emotional_state": "ровно",
                "skills": [],
                "custom": [
                    {"id": "story_slot_1", "label": "Давление", "value": "низкое"},
                    {"id": "story_slot_2", "label": "Отклик", "value": "низкий"},
                ],
            },
        },
        "story_plan": {"status_slots": []},
        "characters": {},
        "relationships": {},
    }


def _long_body() -> str:
    return " ".join(["Свет у двери дрожит, и героиня задерживает дыхание." for _ in range(40)])


def test_v9_prompt_headings_match_visible_renderer():
    from app.turn_processor import COMPACT_SCENE_WRITER_PROMPT

    assert "✦ Что можно сделать" in COMPACT_SCENE_WRITER_PROMPT
    assert "✦ Что можно сказать" in COMPACT_SCENE_WRITER_PROMPT
    assert "✦ Мысли" in COMPACT_SCENE_WRITER_PROMPT
    assert "✦ Что <имя героини> могла бы сказать" not in COMPACT_SCENE_WRITER_PROMPT
    assert "✦ Мысли <имя героини>" not in COMPACT_SCENE_WRITER_PROMPT


def test_v9_normalizer_fallback_options_do_not_use_banned_placeholders():
    from app.scene_response_normalizer import normalize_scene_response

    data = {
        "scene": {
            "header": {"player_name": "Мира"},
            "body": _long_body(),
            "player_options": {},
        },
        "proposed_updates": {"scene_state_patch": {}},
    }

    rendered = normalize_scene_response(data, _base_bundle())["scene"]["rendered_text"]
    banned = [
        "Проверить важную деталь",
        "Сделать следующий физический шаг",
        "Удержать безопасную дистанцию",
        "Сказать коротко и прямо",
        "Задать один конкретный вопрос",
        "Отметить, что изменилось",
        "Сдержать первую реакцию",
    ]
    for phrase in banned:
        assert phrase not in rendered


def test_v9_status_patch_is_visible_in_same_turn_footer():
    from app.scene_response_normalizer import normalize_scene_response

    data = {
        "scene": {
            "header": {"player_name": "Мира"},
            "body": _long_body(),
            "player_options": {
                "actions": ["Отойти к стойке.", "Посмотреть на дверь.", "Убрать телефон."],
                "dialogue": ["Что происходит?", "Говорите яснее.", "Я слушаю."],
                "thoughts": ["Это нехорошо.", "Надо не паниковать.", "Кто-то врёт."],
            },
        },
        "proposed_updates": {
            "scene_state_patch": {
                "status": {"fatigue": "высокая усталость"}
            }
        },
    }

    rendered = normalize_scene_response(data, _base_bundle())["scene"]["rendered_text"]
    assert "Усталость: 75/100 — высокая усталость" in rendered
