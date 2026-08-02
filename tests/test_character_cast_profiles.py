from __future__ import annotations

from copy import deepcopy

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.bootstrap_setup import build_setup_preview
from app.character_profiles import prepare_bootstrap_cast
from app.id_utils import pair_id
from app.validators import validate_bootstrap_result



def _appearance(hair: str) -> dict:
    return {
        "height": "средний рост",
        "build": "стройное телосложение",
        "hair": hair,
        "eyes": "тёмные глаза",
        "face": "живое выразительное лицо",
        "style": "современная повседневная одежда",
    }



def _bootstrap() -> dict:
    return {
        "protagonist": {"id": "pc_01", "name": "Mara Ellison", "role": "player_character"},
        "characters": {
            "pc_01": {
                "id": "pc_01",
                "name": "Mara Ellison",
                "display_name": "Мара",
                "role": "player_character",
                "age": 25,
                "cast_status": "player",
                "appearance": _appearance("тёмное каре"),
                "goal": "сохранить работу и разобраться, почему привычная жизнь начала распадаться",
                "past_short": "живёт самостоятельно и привыкла скрывать перегрузку за сухими ответами",
            },
            "chloe_01": {
                "id": "chloe_01",
                "name": "Chloe Mercer",
                "display_name": "Хлоя",
                "role": "best friend",
                "age": 26,
                "cast_status": "known_core",
                "appearance": _appearance("рыжие волнистые волосы"),
                "goal": "не дать подруге снова исчезнуть в проблемах и одновременно удержать собственную работу",
                "past_short": "дружит с Марой со школы и привыкла замечать её ложное спокойствие",
            },
            "hidden_01": {
                "id": "hidden_01",
                "name": "Adrian Vale",
                "display_name": "Адриан",
                "role": "future romantic lead",
                "age": 29,
                "cast_status": "hidden_core",
                "known_to_player": False,
                "introduced": False,
                "appearance": _appearance("чёрные волосы"),
                "goal": "закончить собственное расследование связи между двумя городскими событиями",
                "past_short": "уже связан со скрытым конфликтом, но ещё не встречался с Марой",
            },
        },
        "relationships": {},
        "knowledge": {},
        "story_plan": {
            "genre": "romantic mystery",
            "language": "ru",
            "tone": "взрослый, напряжённый, местами ироничный",
            "setting_summary": "современный прибрежный город, где обычная жизнь постепенно трескается от странных совпадений",
            "main_premise": "усталая администратор замечает, что чужие тайны начинают пересекаться с её близкими",
            "protagonist_start": "Мара перегружена работой и избегает разговоров о собственном состоянии",
            "player_goal": "сохранить контроль над жизнью и понять, кому можно доверять",
            "central_conflict": "желание остаться в стороне сталкивается с людьми, которые не собираются ждать её готовности",
            "central_question": "сможет ли Мара выбрать близость, не отдав другим право решать за неё",
            "opening_scene_intent": "показать работу, усталость и неудобную заботу Хлои до сильной мистики",
            "opening_pacing": "медленное нарастание через отношения",
            "scene_focus_rules": ["отношения важнее процедурной загадки"],
            "act_structure": [{"act": 1, "goal": "нарушить привычный порядок", "must_happen": ["обострить дружбу"]}],
            "character_arcs": {"pc_01": {"start_point": "закрыта", "pressure": "близкие не принимают молчание", "possible_direction": "границы без мгновенного исцеления"}},
            "relationship_focus": [{"pair_id": "chloe_01__pc_01", "starting_dynamic": "близость через контроль"}],
            "open_threads": ["Хлоя замечает, что улыбка Мары не совпадает со взглядом"],
            "forbidden_drift": ["не делать всех персонажей удобными и терапевтичными"],
            "current_story_position": "act_1_start",
            "status_slots": [
                {"id": "story_slot_1", "label": "Давление", "description": "внешнее и внутреннее давление", "initial_value": "20/100"},
                {"id": "story_slot_2", "label": "Странности", "description": "приближение скрытого слоя", "initial_value": "5/100"},
            ],
        },
        "current_state": {
            "turn_number": 0,
            "date": "День 1",
            "time": "18:40",
            "location": "служебная комната кафе",
            "weather": "холодный дождь за окнами",
            "scene_state": "смена закончилась, но Хлоя ещё рядом",
            "player_character_id": "pc_01",
            "active_character_ids": ["pc_01", "chloe_01", "hidden_01"],
            "nearby_character_ids": ["hidden_01"],
            "scene_goal": "показать привычную, но неудобную дружескую динамику",
            "last_player_input": "",
            "outfit": "тёмная рабочая рубашка и джинсы",
            "inventory": ["телефон", "ключи"],
            "nearby_items": ["две кружки", "закрытый ноутбук"],
            "environment": {"light": "тусклый служебный свет", "sound": "дождь", "details": []},
            "status": {
                "hunger": "65/100 — давно не ела",
                "fatigue": "78/100 — тяжёлая смена",
                "injuries": [],
                "emotional_state": "60/100 — держится на автомате",
                "skills": ["наблюдательность"],
                "custom": [
                    {"id": "story_slot_1", "label": "Давление", "value": "20/100"},
                    {"id": "story_slot_2", "label": "Странности", "value": "5/100"},
                ],
            },
        },
        "npc_state": {},
        "future_locks": {"hidden_character_seeds": [], "do_not_reveal_yet": []},
        "continuity": {},
        "scene_history": [],
        "turns": [],
    }



def test_cast_profiles_are_autofilled_and_hidden_cast_is_removed_from_start():
    data = normalize_bootstrap_json(_bootstrap())
    prepare_bootstrap_cast(data)

    assert data["characters"]["pc_01"]["cast_status"] == "player"
    assert data["characters"]["chloe_01"]["cast_status"] == "known_core"
    assert data["characters"]["hidden_01"]["cast_status"] == "hidden_core"

    chloe = data["characters"]["chloe_01"]
    assert chloe["behavior"]["care_style"]
    assert chloe["behavior"]["inconvenient_pattern"]
    assert chloe["speech_profile"]["under_pressure"]
    assert chloe["life_outside_player"]["private_problem"]
    assert len(chloe["social_triggers"]) >= 2

    assert "hidden_01" not in data["current_state"]["active_character_ids"]
    assert "hidden_01" not in data["current_state"]["nearby_character_ids"]
    assert data["characters"]["hidden_01"]["show_in_preview"] is False
    assert data["characters"]["hidden_01"]["available_to_scene"] is False

    assert pair_id("pc_01", "chloe_01") in data["relationships"]
    assert set(data["knowledge"]) >= {"pc_01", "chloe_01", "hidden_01"}
    assert data["npc_state"]["chloe_01"]["next_self_action_if_ignored"]
    assert data["future_locks"]["hidden_character_ids"] == ["hidden_01"]



def test_preview_shows_known_cast_and_never_leaks_hidden_core():
    data = normalize_bootstrap_json(_bootstrap())
    preview = build_setup_preview(data)

    assert "Хлоя" in preview
    assert "Забота и конфликт" in preview
    assert "Собственная цель" in preview
    assert "inner_logic" not in preview
    assert "Адриан" not in preview
    assert "Adrian Vale" not in preview
    assert "hidden_01" not in preview


def test_familiar_roles_are_visible_when_model_omits_cast_flags():
    raw = _bootstrap()
    chloe = raw["characters"]["chloe_01"]
    chloe.pop("cast_status")
    chloe.pop("known_to_player", None)
    ryan = deepcopy(chloe)
    ryan.update({"id": "ryan_01", "name": "Ryan Harper", "display_name": "Райан", "role": "older brother"})
    ethan = deepcopy(chloe)
    ethan.update({"id": "ethan_01", "name": "Ethan Cole", "display_name": "Итан", "role": "childhood friend"})
    raw["characters"]["ryan_01"] = ryan
    raw["characters"]["ethan_01"] = ethan

    data = normalize_bootstrap_json(raw)
    prepare_bootstrap_cast(data)

    assert data["characters"]["chloe_01"]["cast_status"] == "known_core"
    assert data["characters"]["ryan_01"]["cast_status"] == "known_core"
    assert data["characters"]["ethan_01"]["cast_status"] == "known_core"
    preview = build_setup_preview(data)
    assert all(name in preview for name in ("Хлоя", "Райан", "Итан"))
    assert "Адриан" not in preview



def test_user_written_behavior_is_preserved():
    raw = _bootstrap()
    raw["characters"]["chloe_01"]["behavior"] = {
        "conflict_style": "закрывает дверь и требует закончить разговор сейчас",
        "care_style": "приносит еду и проверяет, была ли она съедена",
        "closeness_style": "считает многолетнюю дружбу правом не принимать первое уклончивое нет",
        "touch_style": "может взять подругу за плечи, если та пытается уйти от разговора",
        "stress_response": "повышает голос и начинает перечислять замеченные несостыковки",
        "rejection_response": "обижается и возвращается без предупреждения позже",
        "change_inertia": "понимает претензию, но при новой тревоге снова контролирует",
        "inconvenient_pattern": "проверяет чужие слова действиями, даже когда это раздражает",
    }
    raw["characters"]["chloe_01"]["speech_profile"] = {
        "baseline": "быстро, живо, с прямыми вопросами",
        "under_pressure": "громче, короче и без шуток",
        "verbal_habits": ["называет Мару полным именем"],
        "avoids": ["говорить, что сама напугана"],
    }

    data = normalize_bootstrap_json(raw)
    prepare_bootstrap_cast(data)
    chloe = data["characters"]["chloe_01"]

    assert chloe["behavior"]["conflict_style"] == "закрывает дверь и требует закончить разговор сейчас"
    assert chloe["speech_profile"]["under_pressure"] == "громче, короче и без шуток"



def test_complete_cast_bootstrap_passes_validation():
    data = normalize_bootstrap_json(_bootstrap())
    errors = validate_bootstrap_result(data)
    assert errors == []



def test_duplicate_significant_npc_behavior_is_rejected():
    raw = _bootstrap()
    second_friend = deepcopy(raw["characters"]["chloe_01"])
    second_friend["id"] = "friend_02"
    second_friend["name"] = "Lena Ward"
    second_friend["display_name"] = "Лена"
    raw["characters"]["friend_02"] = second_friend

    data = normalize_bootstrap_json(raw)
    prepare_bootstrap_cast(data)
    data["characters"]["friend_02"]["behavior"] = deepcopy(data["characters"]["chloe_01"]["behavior"])
    data["characters"]["friend_02"]["speech_profile"] = deepcopy(data["characters"]["chloe_01"]["speech_profile"])

    errors = validate_bootstrap_result(data)
    assert any("duplicates the behavioral voice" in error for error in errors)
