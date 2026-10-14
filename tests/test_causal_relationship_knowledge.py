"""Roman AI-inspired deltas and attributed observations without a strict dialogue ledger."""
import json

from test_commit_turn import packet, commit
from test_prepare_turn import ready
from test_scenario_simulation import consume


def _put_aiden_in_scene(root):
    path = root / "state.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["физически"].append({"id": "aiden"})
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _relations(root):
    return json.loads((root / "отношения.json").read_text(encoding="utf-8"))["персонажи"]["aiden"]["к_POV"]["параметры"]


def _prepare(ready, spoken):
    client, url, _ = ready
    response = client.post(url + "/prepare-turn", json={"user_input": spoken})
    assert response.status_code == 200, response.text
    data, _ = consume(client, response.json())
    return data


def test_small_relationship_deltas_from_saved_baseline_and_new_first_impression(ready):
    client, url, root = ready
    _put_aiden_in_scene(root)
    prepared = packet(ready)
    committed, _ = commit(ready, prepared, relationship_changes=[
        {"owner_id": "aiden", "parameter": "доверие", "delta": 2},
        {"owner_id": "aiden", "parameter": "удивление", "initial_value": 3},
    ])
    assert committed.status_code == 200, committed.text
    assert _relations(root) == {"доверие": 44, "удивление": 3}
    next_turn = packet(ready)
    assert next_turn["режиссёр"]["отношения"]["персонажи"]["aiden"]["к_POV"]["параметры"] == {
        "доверие": 44, "удивление": 3,
    }
    assert next_turn["отношения_участников_для_футера"]["aiden"]["параметры"] == _relations(root)


def test_zero_boundary_can_move_and_unaffected_axes_remain_unchanged(ready):
    client, url, root = ready
    _put_aiden_in_scene(root)
    rfile = root / "отношения.json"
    r = json.loads(rfile.read_text(encoding="utf-8"))
    r["персонажи"]["aiden"]["к_POV"]["параметры"] = {"сочувствие": 0, "нежность": 60}
    rfile.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    p = packet(ready)
    result, _ = commit(ready, p, relationship_changes=[
        {"owner_id": "aiden", "parameter": "сочувствие", "delta": 1},
    ])
    assert result.status_code == 200, result.text
    assert _relations(root) == {"сочувствие": 1, "нежность": 60}


def test_no_forced_relation_changes_and_unseen_npc_cannot_move(ready):
    client, url, root = ready
    prepared = packet(ready)
    denied, _ = commit(ready, prepared, relationship_changes=[
        {"owner_id": "aiden", "parameter": "доверие", "delta": 1},
    ])
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "RELATIONSHIP_OWNER_NOT_PARTICIPATING"
    result, _ = commit(ready, prepared, scene="Обычная разговорная сцена без отношения и без ledger.")
    assert result.status_code == 200, result.text
    assert _relations(root) == {"доверие": 42}


def test_relation_input_rejects_wrong_axis_mode_and_conflicting_patches(ready):
    _, _, root = ready
    _put_aiden_in_scene(root)
    p = packet(ready)
    wrong, _ = commit(ready, p, relationship_changes=[
        {"owner_id": "aiden", "parameter": "несуществующий", "delta": 1},
    ])
    assert wrong.status_code == 422
    assert wrong.json()["detail"]["code"] == "RELATIONSHIP_DELTA_NEEDS_EXISTING_AXIS"
    collision, _ = commit(ready, p, updates={"отношения.json": [
        {"op": "set", "path": "/персонажи/aiden/к_POV/параметры/доверие", "value": 43}
    ]}, relationship_changes=[
        {"owner_id": "aiden", "parameter": "доверие", "delta": 1},
    ])
    assert collision.status_code == 422
    assert collision.json()["detail"]["code"] == "RELATIONSHIP_UPDATE_CONFLICT"
    assert _relations(root) == {"доверие": 42}


def test_heard_public_fact_but_not_hidden_three_month_timing(ready):
    client, url, root = ready
    user = "Я сделала пирсинг. (Это было три месяца назад. Никто не знает.)"
    prepared = _prepare(ready, user)
    success, _ = commit(ready, prepared,
        scene="**Елена** - Я сделала пирсинг.\n**Вероника** - И давно?",
        heard_statements=[
            {"listener_id": "veronica", "speaker_id": "pov", "quote": "Я сделала пирсинг."}
        ],
    )
    assert success.status_code == 200, success.text
    stored = json.loads((root / "память/veronica.json").read_text(encoding="utf-8"))
    entries = stored["знания"]["03.09.2026"]
    assert "Елена сказал(а): «Я сделала пирсинг.»" in entries
    assert "три месяца" not in str(entries)
    next_turn = _prepare(ready, "Какой сегодня день?")
    assert "Елена сказал(а): «Я сделала пирсинг.»" in next_turn["персонажи_подробно"]["veronica"]["память"]["знания"]["03.09.2026"]


def test_hidden_timing_is_never_a_valid_heard_quote(ready):
    client, url, root = ready
    user = "Я сделала пирсинг. (Это было три месяца назад.)"
    p = _prepare(ready, user)
    r, _ = commit(ready, p, scene="**Вероника** - И давно?",
                  heard_statements=[
                      {"listener_id": "veronica", "speaker_id": "pov", "quote": "три месяца назад"},
                  ])
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "HEARD_STATEMENT_SOURCE_MISSING"
    assert not (root / "ходы.jsonl").exists()
    assert "три месяца" not in (root / "память/veronica.json").read_text(encoding="utf-8")


def test_false_statement_is_recorded_as_report_not_objective_truth(ready):
    _, _, root = ready
    p = _prepare(ready, "Я никогда не делала пирсинг.")
    done, _ = commit(ready, p, heard_statements=[
        {"listener_id": "veronica", "speaker_id": "pov", "quote": "Я никогда не делала пирсинг."}
    ])
    assert done.status_code == 200, done.text
    stored = json.loads((root / "память/veronica.json").read_text(encoding="utf-8"))
    assert stored["знания"]["03.09.2026"][-1] == (
        "Елена сказал(а): «Я никогда не делала пирсинг.»"
    )


def test_heard_npc_dialogue_is_attributed_and_atomic_with_relation_delta(ready):
    _, _, root = ready
    _put_aiden_in_scene(root)
    p = packet(ready)
    result, _ = commit(ready, p,
        scene="**Эйден** - Вчера я уволился.\n**Елена** - Правда?",
        heard_statements=[{
            "listener_id": "pov", "speaker_id": "aiden", "quote": "Вчера я уволился."
        }],
        relationship_changes=[{"owner_id": "aiden", "parameter": "доверие", "delta": -1}],
    )
    assert result.status_code == 200, result.text
    assert _relations(root)["доверие"] == 41
    memory = json.loads((root / "память/pov.json").read_text(encoding="utf-8"))
    assert memory["знания"]["03.09.2026"][-1] == "Эйден сказал(а): «Вчера я уволился.»"
    archive = [json.loads(row) for row in (root / "ходы.jsonl").read_text(encoding="utf-8").splitlines()]
    assert set(archive[0]["изменения"]) == {"отношения.json", "память/pov.json"}


def test_only_actual_spoken_lines_are_sources_not_narrator_notes(ready):
    _, _, root = ready
    p = _prepare(ready, "Я просто смотрю на неё.")
    denied, _ = commit(ready, p, scene="Вероника сказала, будто это произошло вчера.",
                       heard_statements=[{
                           "listener_id": "pov", "speaker_id": "veronica",
                           "quote": "будто это произошло вчера",
                       }])
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "HEARD_STATEMENT_SOURCE_MISSING"
