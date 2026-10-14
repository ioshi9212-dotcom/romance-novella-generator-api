import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

KEY = {}


@pytest.fixture
def ready(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    client = TestClient(app)
    created = client.post("/sessions", headers=KEY, json={"initial_text": "СТРОГО RAW\n"})
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    url = f"/sessions/{sid}"
    for command in ("подтверждаю", "вопросов_больше_нет", "подтверждаю"):
        r = client.post(url + "/advance", headers=KEY, json={"command": command})
        assert r.status_code == 200, r.text

    docs = {
        "анкета.json": {"название": "История", "правила_новеллы": "Никаких самовольных решений POV"},
        "персонажи.json": {"персонажи": [
            {"id": "pov", "имя": "Елена", "стартовый": True},
            {"id": "aiden", "имя": "Эйден", "стартовый": True, "где_сейчас": "дома", "что_делает": "изучает вейров"},
            {"id": "veronica", "имя": "Вероника", "стартовый": True, "где_сейчас": "кофейня", "что_делает": "отдыхает"},
        ]},
        "хронология.json": {"дни": {"02.09.2026": {"вечер": ["Эйден начал исследование"]}}},
        "отношения.json": {"pov_id": "pov", "персонажи": {"aiden": {"к_POV": {"параметры": {"доверие": 42}}}}},
        "скрытый_лор_и_крючки.json": {
            "скрытый_лор": [
                {"суть": "Эйден тайно связан с исследователями", "связанные_id": ["aiden"]},
                {"суть": "В городе живёт неизвестная сущность", "связанные_id": []},
            ],
            "крючки": [
                {"суть": "Эйден хочет расспросить Елену", "связанные_id": ["aiden"]},
                {"суть": "Другие исследования продолжаются", "связанные_id": []},
            ],
        },
        "локации.json": {"локации": [
            {"id": "cafe", "название": "Кофейня", "планировка": "Два зала"},
            {"id": "archive", "название": "Архив", "планировка": "Длинные коридоры"},
        ]},
        "state.json": {
            "дата": "03.09.2026", "pov_id": "pov", "локация": {"id": "cafe", "название": "Кофейня"},
            "физически": [{"id": "pov", "одежда": "футболка"}],
            "удалённо": [{"id": "veronica", "связь": "сообщения"}],
        },
    }
    for cid in ("pov", "aiden", "veronica"):
        docs[f"карточки/{cid}.json"] = {
            "id": cid, "характер": {"aiden": "одержим вейрами", "veronica": "спокойная", "pov": "обычная"}[cid],
            "скрытый_лор": f"тайный факт о {cid}",
        }
        docs[f"память/{cid}.json"] = {
            "персонаж_id": cid,
            "знания": {"03.09.2026": [f"личное знание {cid}"]},
            "личные_события": {"03.09.2026": [f"личное событие {cid}"]},
        }
    for path, document in docs.items():
        r = client.put(url + "/data", headers=KEY, json={"path": path, "document": document})
        assert r.status_code == 200, (path, r.text)
    verified = client.post(url + "/verify", headers=KEY, json={"audited_against_raw": True})
    assert verified.status_code == 200, verified.text
    return client, url, tmp_path / "sessions" / sid


def request_turn(ready, **options):
    client, url, _ = ready
    return client.post(url + "/prepare-turn", headers=KEY, json={"user_input": "Я пошла на работу", **options})


def test_active_physical_remote_only_and_director_overview(ready):
    response = request_turn(ready)
    assert response.status_code == 200, response.text
    packet = response.json()
    assert packet["номер_хода"] == 1
    assert packet["ввод_игрока"] == "Я пошла на работу"
    assert packet["персонажи_в_сцене"] == ["pov", "veronica"]
    assert set(packet["персонажи_подробно"]) == {"pov", "veronica"}
    assert packet["персонажи_подробно"]["pov"]["память"]["знания"] == {"03.09.2026": ["личное знание pov"]}
    assert packet["режиссёр"]["реестр"]["персонажи"][1]["где_сейчас"] == "дома"
    assert packet["режиссёр"]["отношения"]["персонажи"]["aiden"]["к_POV"]["параметры"]["доверие"] == 42
    assert packet["режиссёр"]["хронология"]["дни"]["02.09.2026"]
    assert "aiden" not in packet["персонажи_подробно"]
    assert packet["режиссёр"]["релевантные_крючки"] == []
    assert list(packet["режиссёр"]["локации_подробно"]) == ["cafe"]
    assert packet["последние_сцены"] == []
    assert "СТРОГО RAW" not in json.dumps(packet, ensure_ascii=False)


def test_expansion_loads_npc_full_memory_motives_lore_and_places(ready):
    packet = request_turn(ready, additional_character_ids=["aiden"], additional_location_ids=["archive"]).json()
    assert packet["дополнительно_выбранные_NPC"] == ["aiden"]
    assert packet["персонажи_подробно"]["aiden"]["карточка"]["характер"] == "одержим вейрами"
    assert packet["персонажи_подробно"]["aiden"]["память"]["личные_события"] == {"03.09.2026": ["личное событие aiden"]}
    assert packet["режиссёр"]["релевантные_крючки"][0]["индекс"] == 0
    assert packet["режиссёр"]["релевантные_тайны"][0]["индекс"] == 0
    assert "archive" in packet["режиссёр"]["локации_подробно"]
    assert all(x["индекс"] != 1 for x in packet["режиссёр"]["релевантные_тайны"])


def test_global_secret_visible_in_index_but_full_only_on_request(ready):
    packet = request_turn(ready, selected_secret_indices=[1], selected_hook_indices=[1]).json()
    assert len(packet["режиссёр"]["тайны_обзор"]) == 2
    assert len(packet["режиссёр"]["крючки_обзор"]) == 2
    assert [x["индекс"] for x in packet["режиссёр"]["релевантные_тайны"]] == [1]
    assert [x["индекс"] for x in packet["режиссёр"]["релевантные_крючки"]] == [1]


def test_no_implicit_loading_by_name_or_duplicates_and_input_stays(ready):
    first = request_turn(ready, user_input="Эйден где-то дома").json()
    assert "aiden" not in first["персонажи_подробно"]
    second = request_turn(ready, additional_character_ids=["aiden", "aiden"]).json()
    assert list(second["персонажи_подробно"]) == ["pov", "veronica", "aiden"]
    assert first["turn_id"] == second["turn_id"]
    assert first["контекст_sha256"] != second["контекст_sha256"]
    assert second["ввод_игрока"] == "Я пошла на работу"


def test_unknown_ids_and_indices_are_errors_not_silent_skips(ready):
    for args in ({"additional_character_ids": ["unknown"]},
                 {"selected_secret_indices": [9]},
                 {"selected_hook_indices": [-1]},
                 {"additional_location_ids": ["unknown"]}):
        r = request_turn(ready, **args)
        assert r.status_code == 422, (args, r.text)


def test_read_only_and_reads_fresh_files_on_every_call(ready):
    _, _, folder = ready
    before = {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*.json")}
    packet = request_turn(ready).json()
    assert request_turn(ready).json() == packet
    after = {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*.json")}
    assert before == after
    memory = folder / "память" / "veronica.json"
    data = json.loads(memory.read_text(encoding="utf-8"))
    data["знания"]["03.09.2026"].append("Вероника узнала о новом письме")
    memory.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    updated = request_turn(ready).json()
    assert updated["контекст_sha256"] != packet["контекст_sha256"]
    assert "Вероника узнала о новом письме" in updated["персонажи_подробно"]["veronica"]["память"]["знания"]["03.09.2026"]


def test_recent_scene_archive_tail_without_raw_reload(ready):
    _, _, folder = ready
    with (folder / "ходы.jsonl").open("w", encoding="utf-8") as output:
        for i in range(1, 7):
            output.write(json.dumps({"номер": i, "ввод": "ход", "сцена": "сцена" + str(i)}, ensure_ascii=False) + "\n")
    packet = request_turn(ready).json()
    assert [x["номер"] for x in packet["последние_сцены"]] == [5, 6]
    assert packet["номер_хода"] == 1  # archive never advances the session


def test_requires_review_without_authentication(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    client = TestClient(app)
    sid = client.post("/sessions", json={}, headers=KEY).json()["session_id"]
    path = f"/sessions/{sid}/prepare-turn"
    assert client.post(path, json={}, headers=KEY).status_code == 409


def test_complete_old_memory_and_chronology_not_silently_dropped(ready):
    _, _, folder = ready
    memory_path = folder / "память" / "pov.json"
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    memory["знания"]["01.01.2025"] = [f"старый факт {i}" for i in range(240)]
    memory_path.write_text(json.dumps(memory, ensure_ascii=False), encoding="utf-8")
    history_path = folder / "хронология.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    history["дни"]["01.01.2025"] = {"утро": ["давний поворот"]}
    history_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    response = request_turn(ready)
    assert response.status_code == 200, response.text
    first = response.json()
    if first.get("chunked"):
        from test_scenario_simulation import consume
        packet, _ = consume(ready[0], first)
    else:
        packet = first
    assert len(packet["персонажи_подробно"]["pov"]["память"]["знания"]["01.01.2025"]) == 240
    assert packet["режиссёр"]["хронология"]["дни"]["01.01.2025"]["утро"] == ["давний поворот"]


def test_duplicate_physical_remote_participation_rejected(ready):
    _, _, folder = ready
    path = folder / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["удалённо"].append({"id": "pov", "связь": "звонок"})
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    result = request_turn(ready)
    assert result.status_code == 409
    assert "twice" in result.text