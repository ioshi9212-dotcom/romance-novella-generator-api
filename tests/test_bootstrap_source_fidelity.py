from app.bootstrap_source_fidelity import validate_bootstrap_source_fidelity
from fastapi.testclient import TestClient

from app.main import app
from app.session_manager import SessionManager
from tests.test_smoke import _valid_bootstrap


def _source_request() -> dict:
    return {
        "raw_start_text": """
        Главная героиня — девушка, 21 год. Невысокая, миниатюрная.
        Кудрявые русые волосы, зелёные глаза с янтарным оттенком, много веснушек.
        Предпочитает нежную и удобную одежду.
        Живёт со старшим братом. На старте есть лучшая подруга, друг детства и мать друга детства.
        Будущие значимые персонажи: красноволосый мужчина, темноволосый мужчина, девушка из их компании.
        """,
    }


def test_missing_explicit_source_facts_are_rejected_but_generated_profile_fields_are_allowed():
    data = {
        "protagonist": {"id": "elena_morrow"},
        "characters": {
            "elena_morrow": {
                "id": "elena_morrow",
                "name": "Elena Morrow",
                "role": "player_character",
                "cast_status": "player",
                "past_short": (
                    "До начала истории Elena Morrow уже жил(а) с обязанностью «имеет собственные дела и сроки вне героини». "
                    "Под давлением обычно теряет часть самоконтроля; поэтому текущая проблема возникла не внезапно."
                ),
                "appearance": {
                    "height": "не указано",
                    "build": "не указано",
                    "hair": "кудрявые русые волосы",
                    "eyes": "зелёно-янтарные",
                    "face": "множество веснушек",
                    "style": "не указано",
                },
                "inner_logic": {
                    "main_fear": "оказаться бессильным, ненужным или использованным",
                    "blind_spot": "слишком быстро объясняет чужое поведение через собственный страх",
                    "contradiction": "хочет близости, но защищается способом, который эту близость портит",
                },
                "behavior": {
                    "conflict_style": "не отпускает важную для себя тему и защищает собственную версию происходящего",
                    "care_style": "помогает так, как умеет сам, а не обязательно так, как удобно героине",
                    "closeness_style": "проверяет близость действиями и реакцией на отказ",
                    "touch_style": "физическая дистанция зависит от привычки, статуса отношений и текущего напряжения",
                    "stress_response": "теряет часть самоконтроля и возвращается к привычной защите",
                    "rejection_response": "может спорить, закрыться, обидеться или сделать неверный вывод",
                    "change_inertia": "понимание ошибки не превращается в мгновенно новое поведение",
                    "inconvenient_pattern": "в критический момент выбирает знакомый способ защиты, даже если он уже вредил отношениям",
                },
                "speech_profile": {
                    "baseline": "узнаваемая речь с собственным темпом, словарём и способом уходить от неудобного",
                    "under_pressure": "манера речи заметно меняется: темп, громкость или резкость выдают напряжение",
                },
                "life_outside_player": {
                    "current_obligation": "имеет собственные дела и сроки вне героини",
                    "private_problem": "решает личную проблему, которую не обязан сразу раскрывать",
                    "person_or_place_that_matters": "человек, место или дело из отдельной жизни",
                },
            }
        },
        "current_state": {"player_character_id": "elena_morrow"},
        "story_plan": {
            "act_structure": [
                {"act": 1, "goal": "старт", "must_happen": "развить конфликт"},
                {"act": 2, "goal": "развитие", "must_happen": "развить конфликт"},
                {"act": 3, "goal": "выбор", "must_happen": "развить конфликт"},
            ]
        },
    }

    errors = validate_bootstrap_source_fidelity(data, _source_request())
    joined = "\n".join(errors)

    assert "protagonist.age" in joined
    assert "generic repair prose" not in joined
    assert "generic fallback template" not in joined
    assert "appearance.height" in joined
    assert "appearance.build" in joined
    assert "appearance.style" in joined
    assert "characters.visible_count" in joined
    assert "старший брат" in joined
    assert "лучшая подруга" in joined
    assert "друг детства" in joined
    assert "мать друга детства" in joined
    assert "characters.hidden_count" in joined
    assert "story_plan.act_structure" in joined


def test_complete_cast_and_specific_profile_pass_source_fidelity():
    protagonist = {
        "id": "elena_morrow",
        "name": "Elena Morrow",
        "role": "player_character",
        "cast_status": "player",
        "age": 21,
        "past_short": "Рано потеряла родителей, выросла с бабушкой и теперь живёт со старшим братом.",
        "appearance": {
            "height": "невысокая",
            "build": "миниатюрная, внешне хрупкая",
            "hair": "кудрявые русые волосы ниже лопаток",
            "eyes": "зелёные с янтарным оттенком",
            "face": "много веснушек",
            "style": "нежная и удобная одежда",
        },
        "inner_logic": {
            "main_fear": "что её любят только за удобство",
            "blind_spot": "считает, что всем нужна такая же забота, как ей",
            "contradiction": "мечтает получать заботу, но сама постоянно занимает роль спасателя",
        },
        "behavior": {
            "conflict_style": "долго уступает, а под сильным давлением становится острой и упрямой",
            "care_style": "замечает чужой голод и усталость раньше собственных",
            "closeness_style": "легко проявляет ласку с теми, кому доверяет",
            "touch_style": "очень тактильна с близкими",
            "stress_response": "пытается сначала успокоить всех вокруг и только потом срывается",
            "rejection_response": "соглашается слишком быстро, а позже злится на себя",
            "change_inertia": "неумение отказывать закреплялось годами",
            "inconvenient_pattern": "берёт чужие проблемы на себя даже без просьбы",
        },
        "speech_profile": {
            "baseline": "живая, громкая и эмоциональная речь с мягким юмором",
            "under_pressure": "становится резче и может язвить",
        },
        "life_outside_player": {
            "current_obligation": "работает в кофейне и оплачивает часть съёмной квартиры",
            "private_problem": "скрывает тяжесть давления со стороны брата",
            "person_or_place_that_matters": "кофейня и постоянные посетители",
        },
    }

    characters = {
        "elena_morrow": protagonist,
        "older_brother": {"id": "older_brother", "role": "older brother", "cast_status": "known_core"},
        "best_friend": {"id": "best_friend", "role": "best friend", "cast_status": "known_core"},
        "childhood_friend": {"id": "childhood_friend", "role": "childhood friend", "cast_status": "known_core"},
        "friends_mother": {"id": "friends_mother", "role": "childhood friend's mother", "cast_status": "known_support"},
        "red_haired_man": {"id": "red_haired_man", "role": "future romantic lead", "cast_status": "hidden_core"},
        "dark_haired_man": {"id": "dark_haired_man", "role": "future romantic lead and close friend", "cast_status": "hidden_core"},
        "company_woman": {"id": "company_woman", "role": "future significant woman", "cast_status": "hidden_core"},
    }
    data = {
        "protagonist": protagonist,
        "characters": characters,
        "current_state": {"player_character_id": "elena_morrow"},
        "story_plan": {
            "act_structure": [
                {"act": 1, "goal": "столкнуть повседневную гиперзаботу с первым подозрением вокруг находки", "must_happen": "знакомые усиливают домашнее и эмоциональное давление"},
                {"act": 2, "goal": "постепенно раскрыть природу новых людей через отношения", "must_happen": "каждый романтический интерес действует по собственной морали"},
                {"act": 3, "goal": "довести конфликт близости и самостоятельности до выбора", "must_happen": "решение героини остаётся открытым до действий игрока"},
            ]
        },
    }

    assert validate_bootstrap_source_fidelity(data, _source_request()) == []


def test_staged_finalize_returns_private_repair_plan_instead_of_preview_error():
    client = TestClient(app)
    created = client.post(
        "/api/v1/sessions",
        json={**_source_request(), "mode": "gpt_actions"},
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    bootstrap = _valid_bootstrap()
    base_act = bootstrap["story_plan"]["act_structure"][0]
    bootstrap["story_plan"]["act_structure"] = [
        {**base_act, "act": index, "goal": goal, "must_happen": ["развить конфликт"]}
        for index, goal in enumerate(("старт", "развитие", "выбор"), start=1)
    ]

    for section in ("characters", "story_plan", "current_state"):
        saved = client.post(
            f"/api/v1/sessions/{session_id}/bootstrap-part",
            json={"section": section, "value": bootstrap.get(section, {})},
        )
        assert saved.status_code == 200, saved.text

    finalized = client.post(f"/api/v1/sessions/{session_id}/bootstrap-preview-finalize")

    assert finalized.status_code == 200, finalized.text
    body = finalized.json()
    assert body["status"] == "bootstrap_repair_required"
    assert body["repair_required"] is True
    assert body["must_show_to_user"] is False
    assert body["wait_for_confirmation"] is False
    assert body["can_confirm"] is False
    assert body["preview"] == ""
    assert body["message_to_user"] == ""
    assert body["diagnostics"]["retry_action"] == "finalizeBootstrapPreview"
    assert body["repair_plan"]["sections"] == ["characters"]
    assert "старший брат" in body["repair_plan"]["missing_known_roles"]
    assert any("source_fidelity" in error for error in body["repair_errors"])
    assert not any("story_plan" in error for error in body["repair_errors"])
    assert _source_request()["raw_start_text"].strip() in body["repair_plan"]["source_request"]
    assert "не проси повторить анкету" in body["repair_prompt"]
    storage = SessionManager().storage
    assert not (storage.session_dir(session_id) / "pending_bootstrap.json").exists()
    session = client.get(f"/api/v1/sessions/{session_id}").json()
    assert session["last_error"]["code"] == "BOOTSTRAP_SOURCE_FIDELITY_REPAIR_REQUIRED"
    assert session["last_error"]["operation"] == "finalizeBootstrapPreview"
    assert any(
        item["path"].startswith("source_fidelity.characters")
        for item in session["last_error"]["errors"]
    )
    debug = client.get(f"/api/v1/sessions/{session_id}/debug-dump")
    assert debug.status_code == 200, debug.text
    assert debug.json()["diagnostics"]["bootstrap"]["last_error"]["error_id"] == body["diagnostics"]["error_id"]

    confirm = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-confirm",
        json={"confirmation_text": "подтверждаю"},
    )
    assert confirm.status_code == 409

    player_patch = {
        "age": 21,
        "past_short": "Рано потеряла родителей, выросла с бабушкой и теперь живёт со старшим братом.",
        "appearance": {
            "height": "невысокая",
            "build": "миниатюрная",
            "hair": "кудрявые русые волосы",
            "eyes": "зелёные с янтарным оттенком",
            "face": "много веснушек",
            "style": "нежная и удобная одежда",
        },
    }
    repaired_cards = {
        "pc_01": player_patch,
        "older_brother": {"name": "Adrian Vale", "role": "older brother", "cast_status": "known_core"},
        "best_friend": {"name": "Nora Bell", "role": "best friend", "cast_status": "known_core"},
        "childhood_friend": {"name": "Theo Grant", "role": "childhood friend", "cast_status": "known_core"},
        "friends_mother": {"name": "Evelyn Grant", "role": "childhood friend's mother", "cast_status": "known_support"},
        "red_haired_man": {"name": "Rowan Blake", "role": "red-haired future lead", "cast_status": "hidden_core"},
        "dark_haired_man": {"name": "Silas Reed", "role": "dark-haired future lead", "cast_status": "hidden_core"},
        "company_woman": {"name": "Claire West", "role": "future company member", "cast_status": "hidden_core"},
    }
    for item_id, value in repaired_cards.items():
        saved = client.post(
            f"/api/v1/sessions/{session_id}/bootstrap-part",
            json={"section": "characters", "item_id": item_id, "value": value},
        )
        assert saved.status_code == 200, saved.text

    retried = client.post(f"/api/v1/sessions/{session_id}/bootstrap-preview-finalize")

    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "bootstrap_review_pending"
    assert retried.json()["repair_required"] is False
    assert "невысокая" in retried.json()["preview"]
    assert "Adrian Vale" in retried.json()["preview"]
    assert "last_error" not in client.get(f"/api/v1/sessions/{session_id}").json()
