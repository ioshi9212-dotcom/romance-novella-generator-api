"""Free-form relationship axes, max 10, gradual changes and genuine critical exceptions."""
import json

import pytest
from test_prepare_turn import ready, KEY


def prepare(ready):
    client, url, _ = ready
    response = client.post(url + "/prepare-turn", headers=KEY, json={"user_input": "(Посмотреть на него)"})
    assert response.status_code == 200, response.text
    from test_scenario_simulation import consume
    packet, _ = consume(client, response.json())
    return packet


def save(ready, packet, updates, *, scene="Он остановился и посмотрел на неё.", exceptions=None):
    client, url, _ = ready
    return client.post(url + "/commit-turn", headers=KEY, json={
        "turn_id": packet["turn_id"],
        "user_input": packet["ввод_игрока"],
        "context_sha256": packet["контекст_sha256"],
        "scene": scene, "updates": updates,
        "relationship_exceptions": exceptions or [],
    })


def change(metric, value, op="set"):
    return {"op": op, "path": f"/персонажи/aiden/к_POV/параметры/{metric}", "value": value}


def test_freely_named_axes_normal_three_point_changes(ready):
    packet = prepare(ready)
    updates = {"отношения.json": [change("доверие", 39), change("особенная нежность", 3)]}
    r = save(ready, packet, updates)
    assert r.status_code == 200, r.text
    params = json.loads((ready[2] / "отношения.json").read_text(encoding="utf-8"))["персонажи"]["aiden"]["к_POV"]["параметры"]
    assert params == {"доверие": 39, "особенная нежность": 3}


def test_above_three_requires_explicit_critical_event(ready):
    packet = prepare(ready)
    updates = {"отношения.json": [change("доверие", 0), change("недоверие", 3)]}
    denied = save(ready, packet, updates, scene="Он предал её: передал врагу секретную переписку.")
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["code"] == "RELATIONSHIP_CHANGE_TOO_LARGE"
    assert not (ready[2] / "ходы.jsonl").exists()
    r = save(ready, packet, updates,
             scene="Он предал её: передал врагу секретную переписку.",
             exceptions=[{"owner_id": "aiden", "parameter": "доверие",
                          "reason": "Предательство: он лично передал врагу их секретную переписку."}])
    assert r.status_code == 200, r.text
    params = json.loads((ready[2] / "отношения.json").read_text(encoding="utf-8"))["персонажи"]["aiden"]["к_POV"]["параметры"]
    assert params == {"доверие": 0, "недоверие": 3}


def test_four_points_or_unjustified_new_axis_blocked(ready):
    packet = prepare(ready)
    for updates in (
        {"отношения.json": [change("доверие", 46)]},
        {"отношения.json": [change("ревность", 4)]},
        {"отношения.json": [change("доверие", None, "remove")]},
    ):
        r = save(ready, packet, updates)
        assert r.status_code == 409, r.text
    assert not (ready[2] / "ходы.jsonl").exists()


def test_exceptions_must_match_large_change_not_ordinary_scene(ready):
    packet = prepare(ready)
    critical = [{"owner_id": "aiden", "parameter": "доверие",
                 "reason": "Это описание критического события, а не просто обычный разговор."}]
    r = save(ready, packet, {"отношения.json": [change("доверие", 41)]},
             exceptions=critical)
    assert r.status_code == 422
    assert not (ready[2] / "ходы.jsonl").exists()


@pytest.mark.parametrize("value", [-1, 101, True])
def test_invalid_scores_rejected(ready, value):
    packet = prepare(ready)
    r = save(ready, packet, {"отношения.json": [change("неуверенность", value)]})
    assert r.status_code == 409, r.text
    assert "TURN_INVALID" in r.text


def test_maximum_ten_independently_named_axes_per_npc(ready):
    packet = prepare(ready)
    additions = [change(f"моё чувство {n}", 2) for n in range(10)]
    r = save(ready, packet, {"отношения.json": additions})
    assert r.status_code == 409, r.text  # trust + 10 new = 11
    assert "максимум 10" in r.text
    assert not (ready[2] / "ходы.jsonl").exists()
    okay = save(ready, packet, {"отношения.json": additions[:9]})
    assert okay.status_code == 200, okay.text


def test_unpopulated_axis_no_forced_change(ready):
    packet = prepare(ready)
    r = save(ready, packet, {}, scene="Тишина не изменила его отношения.")
    assert r.status_code == 200
    params = json.loads((ready[2] / "отношения.json").read_text(encoding="utf-8"))["персонажи"]["aiden"]["к_POV"]["параметры"]
    assert params == {"доверие": 42}


def test_initial_relationships_of_genuinely_new_npc_are_existing_backstory(ready):
    packet = prepare(ready)
    registry = packet["режиссёр"]["реестр"]["персонажи"] + [
        {"id": "former_friend", "имя": "Знакомый из детства", "стартовый": False}]
    updates = {
        "персонажи.json": [{"op": "set", "path": "/персонажи", "value": registry}],
        "карточки/former_friend.json": [{"op": "set", "path": "",
            "value": {"id": "former_friend", "прошлое": "Давно дружит с POV"}}],
        "память/former_friend.json": [{"op": "set", "path": "",
            "value": {"персонаж_id": "former_friend", "знания": {}, "личные_события": {}}}],
        "отношения.json": [{"op": "set", "path": "/персонажи/former_friend",
            "value": {"к_POV": {"параметры": {"давняя привязанность": 87}}}}],
    }
    r = save(ready, packet, updates)
    assert r.status_code == 200, r.text
