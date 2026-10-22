"""Every current relation metric remains visible and cannot be overwritten."""
import json
from pathlib import Path

from test_commit_turn import packet, commit
from test_prepare_turn import ready
from test_scenario_simulation import consume


def test_prepare_footer_includes_all_present_metrics_even_when_unchanged(ready):
    client, url, folder = ready
    state_file = folder / "state.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["физически"].append({"id": "aiden", "одежда": "пальто"})
    state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    relfile = folder / "отношения.json"
    relations = json.loads(relfile.read_text(encoding="utf-8"))
    scores = {
        "сильное_чувство": 94,
        "усталость": 66,
        "тревога": 51,
        "привязанность": 82,
        "раздражение": 12,
    }
    relations["персонажи"]["aiden"]["к_POV"]["параметры"] = scores
    relfile.write_text(json.dumps(relations, ensure_ascii=False), encoding="utf-8")

    response = client.post(url + "/prepare-turn", json={"user_input": "(Посмотреть на Эйдена)"})
    assert response.status_code == 200, response.text
    prepared, _ = consume(client, response.json())
    footer = prepared["отношения_участников_для_футера"]
    assert set(footer) == {"aiden"}
    assert footer["aiden"]["имя"] == "Эйден"
    assert footer["aiden"]["параметры"] == scores
    assert prepared["режиссёр"]["отношения"]["персонажи"]["aiden"]["к_POV"]["параметры"] == scores


def test_offscreen_loaded_npc_is_not_in_footer(ready):
    client, url, folder = ready
    relfile = folder / "отношения.json"
    rel = json.loads(relfile.read_text(encoding="utf-8"))
    rel["персонажи"]["aiden"]["к_POV"]["параметры"] = {"симпатия": 70, "злость": 13}
    relfile.write_text(json.dumps(rel, ensure_ascii=False), encoding="utf-8")
    p = packet(ready, additional_character_ids=["aiden"])
    assert "aiden" in p["персонажи_подробно"]
    assert "aiden" not in p["отношения_участников_для_футера"]


def test_adding_new_metric_cannot_erase_existing_metrics(ready):
    client, url, folder = ready
    path = folder / "отношения.json"
    relations = json.loads(path.read_text(encoding="utf-8"))
    relations["персонажи"]["aiden"]["к_POV"]["параметры"] = {
        "первое_чувство": 78, "второе_чувство": 46
    }
    path.write_text(json.dumps(relations, ensure_ascii=False), encoding="utf-8")
    p = packet(ready, additional_character_ids=["aiden"])
    good, _ = commit(
        ready, p, additional_character_ids=["aiden"],
        updates={
            "отношения.json": [{
                "op": "set",
                "path": "/персонажи/aiden/к_POV/параметры/новая_ось",
                "value": 2,
            }]
        },
    )
    assert good.status_code == 200, good.text
    actual = json.loads(path.read_text(encoding="utf-8"))
    assert actual["персонажи"]["aiden"]["к_POV"]["параметры"] == {
        "первое_чувство": 78, "второе_чувство": 46, "новая_ось": 2
    }


def test_replacing_all_metrics_with_single_new_axis_is_rejected(ready):
    client, url, folder = ready
    path = folder / "отношения.json"
    relations = json.loads(path.read_text(encoding="utf-8"))
    # Low values previously allowed this destructive replacement: losses of
    # 1-2 points passed the ordinary +/-3 movement validator.
    relations["персонажи"]["aiden"]["к_POV"]["параметры"] = {
        "сохрани_меня": 2, "тоже_сохрани": 1
    }
    path.write_text(json.dumps(relations, ensure_ascii=False), encoding="utf-8")
    p = packet(ready, additional_character_ids=["aiden"])
    bad, _ = commit(
        ready, p, additional_character_ids=["aiden"],
        updates={
            "отношения.json": [{
                "op": "set",
                "path": "/персонажи/aiden/к_POV/параметры",
                "value": {"новое_чувство": 1},
            }]
        },
    )
    assert bad.status_code == 409, bad.text
    assert bad.json()["detail"]["code"] == "RELATIONSHIP_METRICS_DROPPED"
    assert set(bad.json()["detail"]["missing_parameters"]) == {
        "сохрани_меня", "тоже_сохрани"
    }
    assert json.loads(path.read_text(encoding="utf-8")) == relations
    assert not (folder / "ходы.jsonl").exists()


def test_skin_builder_requires_full_footer_not_only_changed_metrics():
    root = Path(__file__).resolve().parents[1] / "runtime"
    builder = (root / "scene_builder.md").read_text(encoding="utf-8")
    rules = (root / "rules.md").read_text(encoding="utf-8")
    # The current Skin Builder uses Markdown section headings; the previous
    # test searched for a retired plain-text footer template.
    section = builder.split("## СОСТОЯНИЕ И ОТНОШЕНИЯ", 1)[1].split(
        "# ПРИНЦИП СИМУЛЯЦИИ", 1
    )[0]
    assert "Показывай действующие показатели отношений NPC к POV" in section
    assert "Изменение указывается относительно прошлого хода: +N, -N или 0" in section
    assert "Отсутствующих персонажей не выводи" in section
    assert "Покажи ВСЕ показатели, включая неизменившиеся (дельта 0)" in rules
