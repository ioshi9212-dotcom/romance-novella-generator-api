from fastapi.testclient import TestClient
from app.main import app


def _valid_bootstrap():
    return {
        "protagonist": {"id": "pc_01", "name": "Mira Vale", "role": "player_character"},
        "characters": {
            "pc_01": {
                "id": "pc_01",
                "name": "Mira Vale",
                "role": "player_character",
                "age": 25,
                "introduced": True,
                "known_to_player": True,
                "locked": True,
                "appearance": {"height": "162 cm", "build": "lean but tired", "hair": "natural blonde bob", "eyes": "dark brown with amber glint", "face": "ordinary, soft, guarded", "style": "jeans, sweater, sneakers"},
                "personality": {"core": ["dry sarcasm outside", "sentimental inside", "afraid to look weak"], "flaws": ["works past exhaustion", "cuts off help"], "speech": "short, sharp, controlled"},
                "goal": "get through the night shift without going home and understand why strange things follow her emotions",
                "past_short": "She has been living inside an exhausting relationship and uses work as an excuse not to return home.",
                "habits": ["checks phone too often", "jokes when cornered", "keeps exits in sight"],
                "likes_in_people": ["directness", "quiet help", "respect for boundaries"],
                "dislikes_in_people": ["pressure", "financial control", "performative pity"],
                "relationship_triggers": {"improves_when": ["given space", "someone notices without pushing"], "worsens_when": ["orders", "mockery", "money pressure"]},
                "skills": ["observation", "endurance under stress"],
                "connections": [{"character_id": "coworker_01", "relation": "coworker", "summary": "They work late in the same building."}],
            },
            "coworker_01": {
                "id": "coworker_01",
                "name": "Ren Ashford",
                "role": "coworker",
                "age": 28,
                "introduced": True,
                "known_to_player": True,
                "locked": True,
                "appearance": {"height": "tall", "build": "spare", "hair": "black", "eyes": "gray", "face": "tired but attentive", "style": "dark work jacket"},
                "personality": {"core": ["practical", "quiet", "observant"], "flaws": ["asks too directly"], "speech": "low, dry, minimal"},
                "goal": "keep the office incident contained and figure out what Mira is hiding",
                "past_short": "Ren has seen Mira stay late too many nights and suspects the problem is not only work.",
                "habits": ["checks hallway cameras", "stands near doors", "notices small changes"],
                "likes_in_people": ["honest answers", "competence", "not panicking"],
                "dislikes_in_people": ["lying badly", "reckless denial"],
                "relationship_triggers": {"improves_when": ["Mira tells the truth"], "worsens_when": ["she vanishes mid-incident"]},
                "skills": ["building security knowledge", "calm under pressure"],
                "connections": [{"character_id": "pc_01", "relation": "coworker", "summary": "Tense concern and unfinished questions."}],
            },
        },
        "relationships": {
            "coworker_01__pc_01": {
                "pair_id": "coworker_01__pc_01",
                "character_a": "coworker_01",
                "character_b": "pc_01",
                "type": "coworkers_with_tension",
                "status": "guarded concern with dry friction",
                "scores": {"trust": 32, "tension": 58, "attachment": 18, "respect": 46, "fear": 0, "curiosity": 62},
                "a_view_of_b": {"summary": "Ren thinks Mira is exhausted and hiding something dangerous", "current_assumption": "she will refuse help if pushed"},
                "b_view_of_a": {"summary": "Mira sees Ren as too observant and inconveniently steady", "current_assumption": "he will ask questions she cannot afford to answer"},
                "shared_history": ["late shifts", "small arguments over safety rules"],
                "recent_changes": [],
                "open_threads": ["what Ren saw on the cameras"],
            }
        },
        "knowledge": {
            "pc_01": {"character_id": "pc_01", "known_facts": [], "observations": [], "assumptions": [], "wrong_beliefs": [], "does_not_know": ["why lights flicker near her"], "must_not_assume": [], "recent_memories": [], "open_questions": [], "knows": ["Ren works late security checks"]},
            "coworker_01": {"character_id": "coworker_01", "known_facts": [], "observations": [], "assumptions": [], "wrong_beliefs": [], "does_not_know": ["what happens at Mira's home"], "must_not_assume": [], "recent_memories": [], "open_questions": [], "knows": ["Mira avoids leaving on time"]},
        },
        "story_plan": {
            "genre": "melodrama with quiet mysticism",
            "language": "ru",
            "tone": "adult, tense, restrained, dry humor in the right places",
            "setting_summary": "A rainy modern city office where emotional stress causes small paranormal distortions that characters notice through physical details.",
            "main_premise": "Mira stays late to avoid home, but a small impossible incident in the office forces someone else to notice the pattern.",
            "protagonist_start": "Mira is exhausted after work, pretending she is fine while delaying the moment she must go home.",
            "player_goal": "keep control, avoid going home too soon, and understand whether the strange distortions are connected to her emotions.",
            "central_conflict": "Mira needs help but treats any attention as pressure, while the mystical layer keeps reacting to what she refuses to say.",
            "central_question": "What will Mira choose when the safest mask becomes the thing attracting danger?",
            "opening_scene_intent": "Start late at the office after closing, show Mira's avoidance, Ren's inconvenient concern, and the first physical hint of mysticism.",
            "act_structure": [{"act": 1, "goal": "late office incident and first unwanted witness", "must_happen": ["Mira delays leaving", "Ren notices a distortion", "home pressure intrudes"], "must_not_resolve_yet": ["source of mysticism", "relationship with abuser"]}],
            "character_arcs": {"pc_01": {"start_point": "controlled and exhausted", "pressure": "home, work, unexplained distortions", "possible_direction": "learn to set boundaries without instantly trusting everyone"}},
            "relationship_focus": [{"pair_id": "coworker_01__pc_01", "starting_dynamic": "dry friction with concern", "slow_burn_rule": "do not soften too early"}],
            "status_slots": [
                {"id": "story_slot_1", "label": "Домашнее давление", "description": "How strongly the abusive home situation presses into the scene.", "initial_value": "среднее"},
                {"id": "story_slot_2", "label": "Мистический отклик", "description": "How visible the paranormal response is.", "initial_value": "низкий"},
            ],
            "open_threads": ["what causes the lights to distort", "why Mira refuses to go home", "what Ren saw"],
            "forbidden_drift": ["instant rescue romance", "horror gore", "solving the mystery in act one"],
            "current_story_position": "act_1_start",
        },
        "current_state": {
            "turn_number": 0,
            "date": "День 1",
            "time": "22:40",
            "location": "закрытый офис на верхнем этаже",
            "weather": "дождь по стеклу, мокрый город внизу",
            "scene_state": "смена закончилась, но Мира тянет время у рабочего стола",
            "player_character_id": "pc_01",
            "active_character_ids": ["pc_01"],
            "nearby_character_ids": ["coworker_01"],
            "scene_goal": "Open with late office tension and the first small distortion.",
            "last_player_input": "",
            "outfit": "джинсы, тёмный свитер, кроссовки; волосы в небрежном каре после длинного дня",
            "inventory": ["телефон", "ключи", "рабочий бейдж", "пустой стакан из-под кофе"],
            "nearby_items": ["выключенный монитор", "сумка", "мигающая лампа", "дверь в коридор"],
            "environment": {"light": "часть ламп уже выключена", "sound": "дождь, вентиляция, редкие шаги в коридоре", "air": "прохладный офисный воздух", "details": ["на стекле дрожит отражение лампы"]},
            "status": {
                "hunger": "пропущен ужин",
                "fatigue": "высокая",
                "injuries": [],
                "emotional_state": "внешне ровная, внутри на грани раздражения",
                "skills": ["наблюдательность", "сдержанность"],
                "custom": [
                    {"id": "story_slot_1", "label": "Домашнее давление", "value": "среднее"},
                    {"id": "story_slot_2", "label": "Мистический отклик", "value": "низкий"},
                ],
            },
        },
        "npc_state": {},
        "future_locks": {"hidden_character_seeds": [], "do_not_reveal_yet": ["Do not reveal the full paranormal source in the first scene."]},
        "continuity": {},
        "scene_history": [],
        "turns": [],
    }


def _long_scene_response(player_input: str):
    body = (
        "*Офис после закрытия не становился тише — он просто менял звук. Днём здесь гудели разговоры, звонки и чужие шаги, а теперь остались вентиляция, дождь по стеклу и короткое мигание лампы над дальним столом. Мира сидела перед выключенным монитором так, будто ещё работала, хотя курсор давно погас вместе с последним письмом.*\n\n"
        "*Телефон на краю стола снова вспыхнул экраном. Имя на уведомлении она успела увидеть раньше, чем сама решила смотреть. Плечи не дрогнули — только пальцы чуть сильнее сжали пустой стакан из-под кофе. Пластик тихо хрустнул. Лампа над столом ответила тонким мерцанием, будто кто-то провёл ногтем по свету.*\n\n"
        "**Рен** — Ты уже сорок минут как ушла домой. *(он остановился у двери, не заходя дальше)* В теории. На практике ты сидишь в темноте и делаешь вид, что это часть рабочего процесса.\n\n"
        "*Мира не подняла голову сразу. В отражении окна Рен был высоким тёмным пятном возле коридора, слишком спокойным для человека, который умеет появляться не вовремя. Дождь размазывал город за стеклом, и в этом мокром отражении лампа над столом мигнула ещё раз — длиннее, ниже, будто свет провалился на полсекунды.*\n\n"
        "*Рен заметил. Конечно заметил. У таких людей это почти профессиональная болезнь: видеть именно то, что другим удобно пропустить. Он перевёл взгляд с лампы на её руку, потом на телефон. Не спросил сразу. Это было хуже вопроса, потому что оставляло ей место самой выбрать, насколько грубо откусить воздух.*\n\n"
        "**Рен** — Камера в коридоре дала помеху ровно в тот момент, когда ты смяла стакан. Я бы списал на проводку, но проводка не реагирует на людей с таким чувством юмора.\n\n"
        "*Телефон снова мигнул. На этот раз коротко, зло, почти требовательно. В стекле за спиной Миры отражение лампы раздвоилось, хотя сама лампа оставалась одна. Рен уже не смотрел на телефон. Он смотрел на отражение — и впервые за вечер его лицо стало не усталым, а внимательным по-настоящему.*"
    )
    return {
        "response_version": "novella.scene_response.v1",
        "player_input": player_input,
        "scene": {
            "header": {
                "story_title": "После закрытия",
                "date": "День 1",
                "time": "22:43",
                "location": "закрытый офис на верхнем этаже",
                "weather": "дождь по стеклу, мокрый город внизу",
                "scene_state": "смена закончилась; лампа над дальним столом начала странно мерцать",
                "player_name": "Мира",
                "visible_state": "внешне ровная, усталая",
                "outfit": "джинсы, тёмный свитер, кроссовки",
                "inventory": "телефон, ключи, рабочий бейдж, пустой стакан из-под кофе",
            },
            "body": body,
            "player_options": {
                "thoughts": ["Он заметил лампу. Плохо.", "Не смотреть на телефон. Хотя бы секунду.", "Можно соврать. Можно устать и не соврать."],
                "dialogue": ["Проводка тоже устала от этой работы.", "Рен, не начинай.", "Ты всегда так романтично обвиняешь людей в поломке ламп?"],
                "actions": ["Погасить экран телефона и проверить отражение в окне.", "Встать из-за стола и забрать сумку.", "Посмотреть на лампу, не выдавая испуг."],
            },
            "status_panel": {
                "hunger": "пропущен ужин",
                "fatigue": "высокая",
                "injuries": "нет",
                "emotional_state": "сдержанное раздражение, тревога под контролем",
                "skills": "наблюдательность, сдержанность",
                "custom": [
                    {"id": "story_slot_1", "label": "Домашнее давление", "value": "растёт"},
                    {"id": "story_slot_2", "label": "Мистический отклик", "value": "заметный"},
                ],
            },
            "relationships_panel": [
                {"pair_id": "coworker_01__pc_01", "label": "Рен ↔ Мира", "value": "напряжение выросло; Рен заметил невозможную деталь"}
            ],
            "rendered_text": "",
        },
        "summary": "После закрытия офиса Рен замечает, что лампа и камера реагируют на состояние Миры.",
        "important_facts": ["Лампа и камера дали помеху рядом с эмоциональной реакцией Миры.", "Рен заметил связь и не списал её на обычную проводку."],
        "witnesses": ["pc_01", "coworker_01"],
        "proposed_updates": {
            "scene_state_patch": {
                "time": "22:43",
                "scene_state": "Рен заметил странную связь между реакцией Миры и помехами в офисе",
                "active_character_ids": ["pc_01", "coworker_01"],
                "nearby_character_ids": [],
                "status": {
                    "hunger": "пропущен ужин",
                    "fatigue": "высокая",
                    "injuries": [],
                    "emotional_state": "сдержанное раздражение, тревога под контролем",
                    "skills": ["наблюдательность", "сдержанность"],
                    "custom": [
                        {"id": "story_slot_1", "label": "Домашнее давление", "value": "растёт"},
                        {"id": "story_slot_2", "label": "Мистический отклик", "value": "заметный"},
                    ],
                },
            },
            "relationship_patches": [
                {
                    "pair_id": "coworker_01__pc_01",
                    "change_type": "visible_anomaly_notice",
                    "entry": "Ren noticed an impossible timing between Mira's stress and office interference.",
                    "reason": "The current scene visibly linked Mira's reaction with the light/camera glitch.",
                    "source_in_scene": "Ren mentions the corridor camera interference and watches the lamp reflection.",
                    "scores": {"tension": 63, "curiosity": 70},
                }
            ],
            "knowledge_patches": [
                {
                    "character_id": "coworker_01",
                    "reason": "Ren personally observed the anomaly during the scene.",
                    "source_in_scene": "Lamp reflection and corridor camera interference happened while Ren was present.",
                    "add_observations": [{"saw": "lamp/reflection behaved impossibly near Mira", "interpreted_as": "not normal wiring", "certainty": "medium"}],
                    "add_open_questions": ["What exactly happens around Mira under stress?"],
                }
            ],
            "new_or_updated_characters": [],
        },
        "safety_checks": {
            "used_only_loaded_characters": True,
            "respected_knowledge_boundaries": True,
            "no_hidden_future_reveal": True,
            "no_major_player_character_choice": True,
            "respected_player_input_order": True,
            "showed_only_scene_relationships": True,
            "header_has_no_focus_or_active_list": True,
            "notes": [],
        },
    }


def test_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_actions_exposes_full_v9_flow():
    client = TestClient(app)
    response = client.get("/openapi-actions.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/start-questionnaire" in paths
    assert "/api/v1/sessions" in paths
    assert "/api/v1/sessions/{session_id}/bootstrap-preview" in paths
    assert "/api/v1/sessions/{session_id}/bootstrap-confirm" in paths
    assert "/api/v1/sessions/{session_id}/turn" in paths
    assert "/api/v1/sessions/{session_id}/apply-turn-result" in paths


def test_empty_start_returns_questionnaire():
    client = TestClient(app)
    response = client.post("/api/v1/sessions", json={"raw_start_text": "начнем", "mode": "gpt_actions"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_questionnaire"
    assert body["session_id"] is None
    assert "Жанр" in body["questionnaire"]


def test_v9_preview_confirm_turn_apply_flow():
    client = TestClient(app)
    created = client.post("/api/v1/sessions", json={
        "genre": "melodrama with mysticism",
        "setting_request": "late modern office",
        "protagonist_request": "guarded adult heroine",
        "mode": "gpt_actions",
    })
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    preview = client.post(f"/api/v1/sessions/{session_id}/bootstrap-preview", json={"bootstrap_json": _valid_bootstrap()})
    assert preview.status_code == 200
    assert preview.json()["status"] == "bootstrap_review_pending"

    confirmed = client.post(f"/api/v1/sessions/{session_id}/bootstrap-confirm", json={"confirmation_text": "начинаем"})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "active"

    empty_turn = client.post(f"/api/v1/sessions/{session_id}/turn", json={"player_input": "   ", "mode": "gpt_actions"})
    assert empty_turn.status_code == 422

    player_input = "(посмотреть на телефон, но не брать его)"
    turn = client.post(f"/api/v1/sessions/{session_id}/turn", json={"player_input": player_input, "mode": "gpt_actions"})
    assert turn.status_code == 200
    turn_body = turn.json()
    assert turn_body["turn_id"]
    assert turn_body["scene_prompt"]

    scene_response = _long_scene_response(player_input)
    applied = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_body["turn_id"], "scene_response": scene_response},
    )
    assert applied.status_code == 200
    assert applied.json()["status"] in {"applied", "partially_applied"}
    assert "После закрытия" in applied.json()["message_to_user"]

    duplicate = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"turn_id": turn_body["turn_id"], "scene_response": scene_response},
    )
    assert duplicate.status_code == 409


def test_apply_turn_result_requires_pending_turn_id():
    client = TestClient(app)
    created = client.post("/api/v1/sessions", json={
        "genre": "melodrama with mysticism",
        "setting_request": "late modern office",
        "protagonist_request": "guarded adult heroine",
        "mode": "gpt_actions",
    }).json()
    session_id = created["session_id"]
    assert client.post(f"/api/v1/sessions/{session_id}/bootstrap-preview", json={"bootstrap_json": _valid_bootstrap()}).status_code == 200
    assert client.post(f"/api/v1/sessions/{session_id}/bootstrap-confirm", json={"confirmation_text": "подтверждаю"}).status_code == 200

    response = client.post(
        f"/api/v1/sessions/{session_id}/apply-turn-result",
        json={"scene_response": _long_scene_response("(тест)")},
    )
    assert response.status_code == 409
