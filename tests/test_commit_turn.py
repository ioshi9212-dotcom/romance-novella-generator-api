"""Turn commits must survive retries, stale writers and partial disk transactions."""
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.turn_commit import JOURNAL, durable_json, sha
from test_prepare_turn import ready, KEY, request_turn


def packet(ready, **options):
    client, url, _ = ready
    response = client.post(url + '/prepare-turn', headers=KEY,
                           json={'user_input': 'Продолжаю разговор', **options})
    assert response.status_code == 200, response.text
    return response.json()


def commit(ready, prepared, *, scene='Эйден посмотрел на символ.', updates=None, **options):
    client, url, _ = ready
    data = dict(
        turn_id=prepared['turn_id'], user_input=prepared['ввод_игрока'],
        context_sha256=prepared['контекст_sha256'], scene=scene,
        updates=updates or {}, **options,
    )
    return client.post(url + '/commit-turn', headers=KEY, json=data), data


def test_patch_only_changed_personal_data_and_archive(ready):
    p = packet(ready, additional_character_ids=['aiden'])
    updates = {
        'память/aiden.json': [
            {'op':'append','path':'/личные_события/03.09.2026', 'value':'Заинтересовался татуировкой Елены'},
            {'op':'append','path':'/знания/03.09.2026', 'value':'Елена сказала, что это просто абстракция'},
        ],
        'персонажи.json': [
            {'op':'set','path':'/персонажи', 'value':[
                {'id':'pov','имя':'Елена','стартовый':True},
                {'id':'aiden','имя':'Эйден','стартовый':True,'где_сейчас':'дома','что_делает':'изучает вейров','последняя_встреча':'кофейня'},
                {'id':'veronica','имя':'Вероника','стартовый':True,'где_сейчас':'кофейня','что_делает':'отдыхает'},
            ]},
        ],
    }
    result, data = commit(ready, p, updates=updates, additional_character_ids=['aiden'])
    assert result.status_code == 200, result.text
    assert result.json()['номер_хода'] == 1
    client, url, root = ready
    memory = json.loads((root/'память/aiden.json').read_text(encoding='utf-8'))
    assert memory['знания']['03.09.2026'][0] == 'личное знание aiden'
    assert 'Елена сказала' in memory['знания']['03.09.2026'][-1]
    assert memory['личные_события']['03.09.2026'][-1] == 'Заинтересовался татуировкой Елены'
    assert json.loads((root/'память/veronica.json').read_text(encoding='utf-8'))['знания'] == {'03.09.2026':['личное знание veronica']}
    archive = [json.loads(row) for row in (root/'ходы.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(archive) == 1
    assert archive[0]['ввод'] == p['ввод_игрока']
    assert archive[0]['сцена'] == 'Эйден посмотрел на символ.'
    assert archive[0]['изменения']['память/aiden.json']['до']['знания']['03.09.2026'] == ['личное знание aiden']
    next_packet = packet(ready)
    assert next_packet['номер_хода'] == 2
    assert 'Елена сказала' not in json.dumps(next_packet['последние_сцены'], ensure_ascii=False)
    assert next_packet['последние_сцены'][0]['сцена'] == 'Эйден посмотрел на символ.'
    assert client.get(url, headers=KEY).json()['последний_ход'] == 1
    assert not (root/JOURNAL).exists()


def test_retry_exact_same_turn_without_archive_duplicate(ready):
    p = packet(ready)
    first, data = commit(ready, p)
    assert first.status_code == 200
    duplicate, _ = commit(ready, p)
    assert duplicate.status_code == 200
    assert duplicate.json()['status'] == 'already_saved'
    root = ready[2]
    assert len((root/'ходы.jsonl').read_text(encoding='utf-8').splitlines()) == 1
    replacement, _ = commit(ready, p, scene='Другая сцена')
    assert replacement.status_code == 409


def test_stale_context_cannot_commit(ready):
    p = packet(ready)
    root = ready[2]
    old = json.loads((root/'память/pov.json').read_text(encoding='utf-8'))
    old['знания']['03.09.2026'].append('новый факт')
    (root/'память/pov.json').write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8')
    result, _ = commit(ready, p)
    assert result.status_code == 409
    assert not (root/'ходы.jsonl').exists()
    assert not (root/JOURNAL).exists()


def test_offscene_personal_edit_requires_explicit_load(ready):
    p = packet(ready)
    patch = {'память/aiden.json':[{'op':'append','path':'/знания/03.09.2026','value':'новость'}]}
    result, _ = commit(ready, p, updates=patch)
    assert result.status_code == 409
    assert 'not prepared' in result.text
    assert json.loads((ready[2]/'память/aiden.json').read_text(encoding='utf-8'))['знания']['03.09.2026'] == ['личное знание aiden']


def test_bad_multifile_patch_does_not_partially_save(ready):
    p = packet(ready)
    root = ready[2]
    original = (root/'память/pov.json').read_bytes()
    updates = {
        'память/pov.json':[{'op':'append','path':'/знания/03.09.2026','value':'новое'}],
        'state.json':[{'op':'set','path':'/физически','value':[]}],
    }
    result, _ = commit(ready, p, updates=updates)
    assert result.status_code == 409
    assert (root/'память/pov.json').read_bytes() == original
    assert not (root/'ходы.jsonl').exists()
    assert not (root/JOURNAL).exists()


def test_create_new_character_in_one_turn(ready):
    p = packet(ready)
    roster = deepcopy(p['режиссёр']['реестр']['персонажи'])
    roster.append({'id':'new_npc','имя':'Новый','стартовый':False,'где_сейчас':'кафе','что_делает':'разговаривает'})
    changes = {
        'персонажи.json':[{'op':'set','path':'/персонажи','value':roster}],
        'карточки/new_npc.json':[{'op':'set','path':'','value':{'id':'new_npc','характер':'добрый'}}],
        'память/new_npc.json':[{'op':'set','path':'','value':{'персонаж_id':'new_npc','знания':{},'личные_события':{}}}],
    }
    result, _ = commit(ready, p, updates=changes)
    assert result.status_code == 200, result.text
    assert json.loads((ready[2]/'карточки/new_npc.json').read_text(encoding='utf-8'))['id'] == 'new_npc'
    next_turn = packet(ready)
    assert len(next_turn['режиссёр']['реестр']['персонажи']) == 4


def test_recover_after_crash_with_partial_archive_and_partial_files(ready, monkeypatch):
    import app.turn_commit as tc
    p = packet(ready)
    root = ready[2]
    changes = {'память/pov.json':[{'op':'append','path':'/знания/03.09.2026','value':'важное'}]}
    real_durable = tc.durable_json
    def crash_after_writing_journal(path, data):
        real_durable(path, data)
        if path.name == JOURNAL:
            raise RuntimeError('simulated process termination')
    monkeypatch.setattr(tc, 'durable_json', crash_after_writing_journal)
    with pytest.raises(RuntimeError):
        commit(ready, p, updates=changes)
    monkeypatch.setattr(tc, 'durable_json', real_durable)
    assert (root/JOURNAL).exists()
    # Simulate a partial file write and interrupted append that contains no newline.
    (root/'ходы.jsonl').write_bytes(b'{"unfinished":')
    recovered = ready[0].get(ready[1], headers=KEY)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()['последний_ход'] == 1
    assert not (root/JOURNAL).exists()
    archive = (root/'ходы.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(archive) == 1
    assert json.loads(archive[0])['номер'] == 1
    memory = json.loads((root/'память/pov.json').read_text(encoding='utf-8'))
    assert memory['знания']['03.09.2026'][-1] == 'важное'


def test_pure_narrative_turn_and_authentication(ready):
    p = packet(ready)
    client, url, root = ready
    result, request = commit(ready, p, updates={})
    assert result.status_code == 200
    assert client.post(url+'/commit-turn', json=request).status_code == 401
    assert client.post(url+'/commit-turn', json={}).status_code == 401
    assert json.loads((root/'сессия.json').read_text(encoding='utf-8'))['этап'] == 'игра'


def test_append_typed_only_and_no_destructive_old_memory(ready):
    p = packet(ready)
    bad = {'память/pov.json':[{'op':'set','path':'','value':{'персонаж_id':'pov','знания':{},'личные_события':{}}}]}
    resp, _ = commit(ready, p, updates=bad)
    assert resp.status_code == 422
    assert not (ready[2]/'ходы.jsonl').exists()


def test_missing_patch_value_is_rejected(ready):
    p = packet(ready)
    patch = {"память/pov.json": [{"op": "append", "path": "/знания/03.09.2026"}]}
    response, _ = commit(ready, p, updates=patch)
    assert response.status_code == 422
    assert not (ready[2] / "ходы.jsonl").exists()


def test_real_multi_turn_history_remains_small_in_next_context(ready):
    import app.turn_commit as tc
    first = packet(ready)
    patches = {"память/pov.json": [
        {"op": "append", "path": "/знания/03.09.2026", "value": "x" * 120_000}
    ]}
    response, _ = commit(ready, first, updates=patches)
    assert response.status_code == 200, response.text
    second = packet(ready)
    assert second["номер_хода"] == 2
    assert second["последние_сцены"][0]["сцена"] == "Эйден посмотрел на символ."
    assert "x" * 1000 not in json.dumps(second["последние_сцены"])
    assert "x" * 1000 in json.dumps(second["персонажи_подробно"]["pov"])


def test_commit_works_if_amvera_volume_disallows_hardlinks(ready, monkeypatch):
    import app.turn_commit as tc
    p = packet(ready)
    def links_unsupported(*_args):
        raise OSError("Operation not permitted on volume")
    monkeypatch.setattr(tc.os, "link", links_unsupported)
    result, _ = commit(ready, p, updates={"память/pov.json": [
        {"op": "append", "path": "/знания/03.09.2026", "value": "новость"}
    ]})
    assert result.status_code == 200, result.text

def test_registry_single_npc_update_without_resending_entire_roster(ready):
    p = packet(ready)
    result, _ = commit(ready, p, updates={"персонажи.json": [
        {"op": "merge_by_id", "path": "/персонажи",
         "value": {"id": "aiden", "последняя_встреча": "Кофейня", "что_делает": "отдыхает дома"}}
    ]})
    assert result.status_code == 200, result.text
    reg = json.loads((ready[2]/"персонажи.json").read_text(encoding="utf-8"))["персонажи"]
    assert len(reg) == 3
    assert reg[1]["последняя_встреча"] == "Кофейня"
    assert reg[1]["где_сейчас"] == "дома"
    assert reg[2]["что_делает"] == "отдыхает"


def test_registry_update_unknown_id_is_rejected(ready):
    p = packet(ready)
    result, _ = commit(ready, p, updates={"персонажи.json": [
        {"op": "merge_by_id", "path": "/персонажи", "value": {"id": "absent", "что_делает": "ходит"}}
    ]})
    assert result.status_code == 422
    assert not (ready[2]/"ходы.jsonl").exists()
