"""Full-session resume and non-destructive bounded long-history checkpoints."""
import json

import pytest

from test_prepare_turn import KEY, ready
from test_maintenance import prep, save, audit, commit_audit, rollback
from app.session_continuity import CHECKPOINT, MAINTENANCE


def reach_60(ready):
    client, url, folder = ready
    for n in range(1, 61):
        p = prep(ready)
        updates = {'память/pov.json': [
            {'op':'append', 'path':'/знания/03.09.2026', 'value':f'сведения о событии {n}'}
        ]} if n % 10 == 0 else {}
        save(ready, p, updates=updates)
        if n % 15 == 0:
            report = audit(ready)
            result, _ = commit_audit(ready, report)
            assert result.status_code == 200, result.text
    assert folder.joinpath('ходы.jsonl').read_text(encoding='utf-8').count('\n') == 60
    return client, url, folder


def compact(ready, world='События до 60-го хода; исследование продолжается'):
    client, url, _ = ready
    p = client.post(url + '/prepare-compaction', headers=KEY)
    assert p.status_code == 200, p.text
    report = p.json()
    payload = {
        'through_turn': report['through_turn'],
        'review_sha256': report['review_sha256'],
        'reviewed_against_archive': True,
        'world_summary': world,
        'character_summaries': {cid:f'Долговременная память {cid}; сохранены важные причины и вопросы'
                                for cid in report['character_ids']},
    }
    commit = client.post(url + '/commit-compaction', headers=KEY, json=payload)
    assert commit.status_code == 200, commit.text
    return report, payload, commit.json()


def test_new_chat_resume_without_new_session_or_writing(ready):
    client, url, folder = ready
    s = client.get(url+'/resume', headers=KEY)
    assert s.status_code == 200
    assert s.json()['следующий_ход'] == 1
    assert s.json()['реестр']['персонажи'][1]['где_сейчас'] == 'дома'
    save(ready, prep(ready))
    before = {p.relative_to(folder):p.read_bytes() for p in folder.rglob('*') if p.is_file()}
    resumed = client.get(url+'/resume', headers=KEY)
    assert resumed.status_code == 200
    assert resumed.json()['последний_ход'] == 1
    assert resumed.json()['последние_сцены'][-1]['сцена'] == 'Сцена 1'
    assert resumed.json()['дальше'].startswith('Вызвать')
    assert {p.relative_to(folder):p.read_bytes() for p in folder.rglob('*') if p.is_file()} == before
    assert client.get(url+'/resume').status_code == 200


def test_archived_scenes_bounded_lookup_preserves_exact_text(ready):
    client, url, _ = ready
    for _ in range(4):
        save(ready, prep(ready))
    scenes = client.get(url+'/turns', params={'from_turn':2,'to_turn':4}, headers=KEY)
    assert scenes.status_code == 200
    assert [r['сцена'] for r in scenes.json()['сцены']] == ['Сцена 2','Сцена 3','Сцена 4']
    assert 'изменения' not in scenes.text
    for args in [{'from_turn':0,'to_turn':1},{'from_turn':3,'to_turn':2},
                 {'from_turn':1,'to_turn':99},{'from_turn':1,'to_turn':16}]:
        assert client.get(url+'/turns',params=args,headers=KEY).status_code == 422


def test_60_turn_compaction_reviews_then_works_as_delta_and_can_fetch_full(ready):
    client,url,folder = reach_60(ready)
    old_original = folder.joinpath('память/pov.json').read_bytes()
    history_original = folder.joinpath('хронология.json').read_bytes()
    s = client.get(url, headers=KEY).json()
    assert s['сжатие_требуется'] is True
    assert client.post(url+'/prepare-turn',headers=KEY,json={'user_input':'продолжаю'}).status_code == 409
    report,payload,result = compact(ready)
    assert report['period'] == [1, 60]
    assert len(report['archive']) == 60
    assert result['full_memory_preserved'] is True
    assert client.post(url+'/commit-compaction',headers=KEY,json=payload).json()['status']=='already_compacted'
    assert client.get(url,headers=KEY).json()['сжатие_требуется'] is False
    assert folder.joinpath('память/pov.json').read_bytes()==old_original
    assert folder.joinpath('хронология.json').read_bytes()==history_original
    prepared = prep(ready)
    assert prepared['последнее_сжатие']==60
    assert prepared['персонажи_подробно']['pov']['память']['знания']=={}
    assert prepared['персонажи_подробно']['pov']['сводка_личной_памяти'].startswith('Долговременная')
    assert prepared['режиссёр']['хронология']['дни']=={}
    assert 'События до 60' in prepared['режиссёр']['сводка_прошлых_событий']
    assert prepared['персонажи_подробно']['pov']['старые_даты_доступны']['знания']==['03.09.2026']
    full_response = client.post(url+'/prepare-turn',headers=KEY,json={
        'user_input':'продолжаю','full_memory_character_ids':['pov'],'full_chronology':True})
    from test_scenario_simulation import consume
    full, _ = consume(client, full_response.json())
    assert len(full['персонажи_подробно']['pov']['память']['знания']['03.09.2026'])==7
    assert full['режиссёр']['хронология']['дни']['02.09.2026']
    assert full['контекст_sha256']!=prepared['контекст_sha256']
    err=client.post(url+'/prepare-turn',headers=KEY,json={
        'user_input':'продолжаю','full_memory_character_ids':['aiden']})
    assert err.status_code==422
    updates={'память/pov.json':[{'op':'append','path':'/знания/03.09.2026','value':'новое после 60-го хода'}]}
    save(ready,prepared,updates)
    recent=prep(ready)
    assert recent['персонажи_подробно']['pov']['память']['знания']['03.09.2026']==['новое после 60-го хода']
    assert folder.joinpath('память/pov.json').read_text().count('сведения о событии')==6



def test_undated_legacy_memory_sections_are_preserved_at_60_turn_checkpoint(ready):
    client, url, folder = reach_60(ready)
    aiden_path = folder / 'память/aiden.json'
    aiden = json.loads(aiden_path.read_text(encoding='utf-8'))
    aiden['знания'] = ['Старая запись без даты', {'источник': 'личное наблюдение'}]
    aiden['личные_события'] = 'Старые события без структуры дат'
    aiden_path.write_text(json.dumps(aiden, ensure_ascii=False), encoding='utf-8')
    veronica_path = folder / 'память/veronica.json'
    veronica = json.loads(veronica_path.read_text(encoding='utf-8'))
    veronica['знания'] = None
    veronica_path.write_text(json.dumps(veronica, ensure_ascii=False), encoding='utf-8')
    originals = {p: p.read_bytes() for p in (aiden_path, veronica_path)}

    report, _, result = compact(ready)
    assert result['through_turn'] == 60
    assert report['characters']['aiden']['память']['знания'] == aiden['знания']
    assert report['characters']['veronica']['память']['знания'] is None
    assert all(p.read_bytes() == content for p, content in originals.items())
    assert client.get(url).json()['сжатие_требуется'] is False

    packet_response = client.post(url + '/prepare-turn', headers=KEY, json={
        'user_input': 'Продолжить существующую историю без потери памяти',
        'additional_character_ids': ['aiden'],
    })
    assert packet_response.status_code == 200, packet_response.text
    packet = packet_response.json()
    from test_scenario_simulation import consume
    if packet.get('chunked'):
        packet, _ = consume(client, packet)
    aiden_view = packet['персонажи_подробно']['aiden']
    veronica_view = packet['персонажи_подробно']['veronica']
    assert aiden_view['память']['знания'] == aiden['знания']
    assert aiden_view['память']['личные_события'] == aiden['личные_события']
    assert veronica_view['память']['знания'] is None
    assert set(aiden_view['недатированные_разделы_сохранены_полностью']) == {
        'знания', 'личные_события',
    }
    assert 'знания' in veronica_view['недатированные_разделы_сохранены_полностью']
    assert aiden_view['старые_даты_доступны']['знания'] == []

    # A change to an opaque field invalidates the summary rather than losing
    # or hiding new content behind the previous snapshot.
    aiden['знания'].append('Новое наблюдение')
    aiden_path.write_text(json.dumps(aiden, ensure_ascii=False), encoding='utf-8')
    response = client.post(url + '/prepare-turn', headers=KEY, json={
        'user_input': 'Продолжить существующую историю без потери памяти',
        'additional_character_ids': ['aiden'],
    })
    assert response.status_code == 200, response.text
    changed = response.json()
    if changed.get('chunked'):
        changed, _ = consume(client, changed)
    aiden_view = changed['персонажи_подробно']['aiden']
    assert aiden_view['сжатие_недействительно'] is True
    assert aiden_view['память']['знания'] == aiden['знания']


def test_undated_sections_are_indexed_without_destructive_normalization():
    from app.session_continuity import SECTIONS, _index_doc, _tail_doc
    journal = {'знания': ['факт'], 'личные_события': None}
    snapshot = _index_doc(journal, SECTIONS)
    assert _tail_doc(journal, snapshot, SECTIONS) == journal
    changed = {'знания': ['факт', 'ещё факт'], 'личные_события': None}
    assert _tail_doc(changed, snapshot, SECTIONS) is None


def test_stale_compact_prefix_falls_back_to_full_not_missing_data(ready):
    client,url,folder=reach_60(ready)
    compact(ready)
    memory_file=folder/'память/pov.json'
    data=json.loads(memory_file.read_text(encoding='utf-8'))
    data['знания']['03.09.2026'][0]='исправлено из аудита'
    memory_file.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    history_file=folder/'хронология.json'
    history=json.loads(history_file.read_text(encoding='utf-8'))
    history['дни']['02.09.2026']['вечер'][0]='проверенная новая формулировка'
    history_file.write_text(json.dumps(history,ensure_ascii=False),encoding='utf-8')
    packet=prep(ready)
    assert packet['персонажи_подробно']['pov']['сжатие_недействительно'] is True
    assert packet['персонажи_подробно']['pov']['память']['знания']['03.09.2026'][0]=='исправлено из аудита'
    assert packet['режиссёр']['сжатие_недействительно'] is True
    assert packet['режиссёр']['хронология']['дни']['02.09.2026']['вечер']==['проверенная новая формулировка']


def test_rollback_60_removes_checkpoint_and_audit_in_one_transaction(ready):
    client,url,folder=reach_60(ready)
    compact(ready)
    assert (folder/CHECKPOINT).is_file()
    result=rollback(ready,f"{folder.name}:60")
    assert result.status_code==200,result.text
    assert not (folder/CHECKPOINT).exists()
    assert client.get(url,headers=KEY).json()['последнее_сжатие']==0
    assert prep(ready)['номер_хода']==60


def test_compaction_recovery_on_crash(ready,monkeypatch):
    from app import session_continuity as sc
    client,url,folder=reach_60(ready)
    p=client.post(url+'/prepare-compaction',headers=KEY).json()
    body={'through_turn':60,'review_sha256':p['review_sha256'],
          'reviewed_against_archive':True,'world_summary':'Проверенная длинная история',
          'character_summaries':{cid:f'Сводка {cid}' for cid in p['character_ids']}}
    durable=sc.durable_json
    def crash(path,data):
        durable(path,data)
        if path.name==MAINTENANCE:
            raise RuntimeError('simulated restart')
    monkeypatch.setattr(sc,'durable_json',crash)
    with pytest.raises(RuntimeError):
        client.post(url+'/commit-compaction',headers=KEY,json=body)
    monkeypatch.setattr(sc,'durable_json',durable)
    assert (folder/MAINTENANCE).exists()
    assert client.get(url+'/resume',headers=KEY).json()['последнее_сжатие']==60
    assert not (folder/MAINTENANCE).exists()
    assert client.post(url+'/commit-compaction',headers=KEY,json=body).json()['status']=='already_compacted'


def test_resume_reports_due_audit_and_compaction(ready):
    client,url,_=ready
    for turn in range(1,61):
        save(ready,prep(ready))
        if turn%15==0 and turn<60:
            report=audit(ready)
            assert commit_audit(ready,report)[0].status_code==200
    resume=client.get(url+'/resume',headers=KEY).json()
    assert resume['аудит_требуется'] is True
    assert resume['сжатие_требуется'] is True
    assert 'prepare-audit' in resume['дальше']
    report=audit(ready)
    assert commit_audit(ready,report)[0].status_code==200
    resume=client.get(url+'/resume',headers=KEY).json()
    assert 'prepare-compaction' in resume['дальше']


def test_second_compaction_120_uses_previous_reviewed_summary_and_new_60_turns(ready):
    client,url,folder=reach_60(ready)
    first,payload,done=compact(ready,world='Устойчивый общий итог первых 60 ходов')
    assert done['through_turn']==60
    for n in range(61,121):
        p=prep(ready)
        changes={'память/pov.json':[{'op':'append','path':'/личные_события/03.09.2026',
                  'value':f'продолжение {n}'}]} if n==80 else {}
        save(ready,p,changes)
        if n%15==0:
            packet=audit(ready)
            assert commit_audit(ready,packet)[0].status_code==200
    prep_120=client.post(url+'/prepare-compaction',headers=KEY)
    assert prep_120.status_code==200,prep_120.text
    data=prep_120.json()
    assert data['period']==[61,120]
    assert data['previous_checkpoint_turn']==60
    assert data['previous_world_summary']=='Устойчивый общий итог первых 60 ходов'
    assert data['characters']['pov']['память']['личные_события']['03.09.2026']==['продолжение 80']
    assert len(data['archive'])==60 and data['archive'][0]['номер']==61
    _, payload2, status=compact(ready,'Сводка первых 120 ходов с учётом предыдущего итога')
    assert status['through_turn']==120
    new=prep(ready)
    assert new['последнее_сжатие']==120
    assert new['персонажи_подробно']['pov']['память']['личные_события']=={}
    assert len(json.loads((folder/'память/pov.json').read_text())['личные_события']['03.09.2026'])==2
    assert len((folder/'ходы.jsonl').read_text().splitlines())==120