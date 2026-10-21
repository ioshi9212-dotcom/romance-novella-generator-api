"""Evidence-based memory audit and journaled last-turn rollback."""
import json

import pytest

from app.turn_maintenance import AUDIT_LOG, MAINTENANCE
from test_prepare_turn import KEY, ready


def prep(ready, **extra):
    client, url, _ = ready
    r = client.post(url + '/prepare-turn', headers=KEY, json={'user_input':'продолжаю', **extra})
    assert r.status_code == 200, r.text
    from test_scenario_simulation import consume
    decoded, _ = consume(client, r.json())
    return decoded


def save(ready, prepared, updates=None, **additional):
    client, url, _ = ready
    body = {
        'turn_id':prepared['turn_id'], 'context_sha256':prepared['контекст_sha256'],
        'user_input':prepared['ввод_игрока'], 'scene':f"Сцена {prepared['номер_хода']}",
        'updates':updates or {}, **additional,
    }
    r = client.post(url + '/commit-turn', headers=KEY, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def rollback(ready, turn_id):
    client,url,_=ready
    return client.post(url+'/rollback-last-turn',headers=KEY,json={'expected_turn_id':turn_id})


def seed(ready, turns=15, change_at=None):
    for i in range(1, turns+1):
        p=prep(ready)
        updates={'память/pov.json':[
            {'op':'append','path':'/личные_события/03.09.2026','value':f'событие {i}'}
        ]} if change_at is None or i in change_at else {}
        save(ready,p,updates)
    return p


def audit(ready, character_ids=None):
    client,url,_=ready
    r=client.post(url+'/prepare-audit',headers=KEY,json={'character_ids':character_ids or []})
    assert r.status_code==200,r.text
    return r.json()


def commit_audit(ready, report,updates=None,evidence=None,**overrides):
    client,url,_=ready
    body={
        'through_turn':report['through_turn'],
        'audit_sha256':report['audit_sha256'],
        'character_ids':[],
        'reviewed_against_archive':True,
        'findings':['Проверены реальные сцены и дневник POV'],
        'evidence_turns':evidence or {},
        'updates':updates or {},
        **overrides,
    }
    return client.post(url+'/commit-audit',headers=KEY,json=body),body


def test_rollback_restores_memory_and_scene_number(ready):
    client,url,folder=ready
    raw=(folder/'raw.txt').read_bytes()
    p=prep(ready)
    changed={'память/pov.json':[{'op':'append','path':'/знания/03.09.2026','value':'из последней сцены'}],
             'персонажи.json':[{'op':'merge_by_id','path':'/персонажи','value':{'id':'aiden','что_делает':'идёт домой'}}]}
    save(ready,p,changed)
    assert 'из последней сцены' in (folder/'память/pov.json').read_text()
    wrong=rollback(ready,'wrong-id')
    assert wrong.status_code==409
    undone=rollback(ready,p['turn_id'])
    assert undone.status_code==200,undone.text
    assert undone.json()['последний_ход']==0
    assert (folder/'raw.txt').read_bytes()==raw
    assert 'из последней сцены' not in (folder/'память/pov.json').read_text()
    assert 'идёт домой' not in (folder/'персонажи.json').read_text()
    assert (folder/'ходы.jsonl').read_bytes()==b''
    assert prep(ready)['номер_хода']==1
    assert rollback(ready,p['turn_id']).status_code==409


def test_rollback_deletes_created_npc_and_restores_registry(ready):
    p=prep(ready)
    changes={
        'персонажи.json':[{'op':'append','path':'/персонажи','value':{'id':'npc_new','имя':'Новый','стартовый':False}}],
        'карточки/npc_new.json':[{'op':'set','path':'','value':{'id':'npc_new'}}],
        'память/npc_new.json':[{'op':'set','path':'','value':{'персонаж_id':'npc_new','знания':{},'личные_события':{}}}],
    }
    save(ready,p,changes)
    folder=ready[2]
    assert (folder/'карточки/npc_new.json').exists()
    assert rollback(ready,p['turn_id']).status_code==200
    assert not (folder/'карточки/npc_new.json').exists()
    assert not (folder/'память/npc_new.json').exists()
    assert 'npc_new' not in (folder/'персонажи.json').read_text()


def test_15_turn_audit_reads_exact_evidence_and_blocks_next_turn(ready):
    seed(ready,15)
    client,url,folder=ready
    state=client.get(url,headers=KEY).json()
    assert state['аудит_требуется'] is True
    blocked=client.post(url+'/prepare-turn',headers=KEY,json={'user_input':'следующий ход'})
    assert blocked.status_code==409 and blocked.json()['detail']['code']=='AUDIT_REQUIRED'
    packet=audit(ready)
    assert len(packet['архив'])==15
    assert [x['номер'] for x in packet['архив']]==list(range(1,16))
    assert packet['архив'][0]['сцена']=='Сцена 1'
    assert len(packet['память']['pov']['личные_события']['03.09.2026'])==16
    assert packet['checkpoints']['compaction_60_due'] is False
    bad, _=commit_audit(ready,packet, updates={'память/pov.json':[
       {'op':'append','path':'/знания/03.09.2026','value':'найдено в сцене 7'}
    ]})
    assert bad.status_code==422
    assert not (folder/AUDIT_LOG).exists()
    updates={'память/pov.json':[{'op':'append','path':'/знания/03.09.2026','value':'найдено в сцене 7'}]}
    done, body=commit_audit(ready,packet,updates,evidence={'память/pov.json':[7]})
    assert done.status_code==200,done.text
    assert done.json()['changed_files']==['память/pov.json']
    retry=client.post(url+'/commit-audit',headers=KEY,json=body)
    assert retry.status_code==200 and retry.json()['status']=='already_audited'
    assert len((folder/AUDIT_LOG).read_text().splitlines())==1
    assert client.get(url,headers=KEY).json()['аудит_требуется'] is False
    assert prep(ready)['номер_хода']==16


def test_audit_cannot_update_unloaded_memory_or_use_future_evidence(ready):
    seed(ready,15,change_at={1})
    p=audit(ready)
    updates={'память/aiden.json':[{'op':'append','path':'/знания/03.09.2026','value':'новое'}]}
    response,_=commit_audit(ready,p,updates,evidence={'память/aiden.json':[5]})
    assert response.status_code==409
    p=audit(ready,['aiden'])
    updates={'память/aiden.json':[{'op':'append','path':'/знания/03.09.2026','value':'новое'}]}
    response,_=commit_audit(ready,p,updates,evidence={'память/aiden.json':[999] },character_ids=['aiden'])
    assert response.status_code==422


def test_rollback_audited_last_turn_restores_pre_turn_and_audit_changes(ready):
    p=seed(ready,15)
    before=(ready[2]/'память/pov.json').read_text()
    report=audit(ready)
    update={'память/pov.json':[{'op':'append','path':'/личные_события/03.09.2026','value':'пропущенное в сцене 6'}]}
    result,_=commit_audit(ready,report,update,{'память/pov.json':[6]})
    assert result.status_code==200,result.text
    removed=rollback(ready,p['turn_id'])
    assert removed.status_code==200,removed.text
    assert removed.json()['audit_reverted'] is True
    memory=json.loads((ready[2]/'память/pov.json').read_text())['личные_события']['03.09.2026']
    assert 'событие 15' not in memory and 'пропущенное в сцене 6' not in memory
    assert 'событие 14' in memory
    assert (ready[2]/AUDIT_LOG).read_bytes()==b''
    assert len((ready[2]/'ходы.jsonl').read_text().splitlines())==14
    assert ready[0].get(ready[1],headers=KEY).json()['последний_ход']==14
    assert prep(ready)['номер_хода']==15


def test_pending_rollback_recovers_after_simulated_crash(ready,monkeypatch):
    from app import turn_maintenance as tm
    p=prep(ready)
    save(ready,p,{'память/pov.json':[{'op':'append','path':'/знания/03.09.2026','value':'undo me'}]})
    durable=tm.durable_json
    def crash(path,data):
        durable(path,data)
        if path.name==MAINTENANCE:
            raise RuntimeError('simulated power failure')
    monkeypatch.setattr(tm,'durable_json',crash)
    with pytest.raises(RuntimeError):
        rollback(ready,p['turn_id'])
    monkeypatch.setattr(tm,'durable_json',durable)
    assert (ready[2]/MAINTENANCE).exists()
    response=ready[0].get(ready[1],headers=KEY)
    assert response.status_code==200
    assert response.json()['последний_ход']==0
    assert 'undo me' not in (ready[2]/'память/pov.json').read_text()
    assert not (ready[2]/MAINTENANCE).exists()


def test_pending_audit_recovers_after_simulated_crash(ready,monkeypatch):
    from app import turn_maintenance as tm
    seed(ready,15)
    report=audit(ready)
    durable=tm.durable_json
    def crash(path,data):
        durable(path,data)
        if path.name==MAINTENANCE:
            raise RuntimeError('simulated power failure')
    monkeypatch.setattr(tm,'durable_json',crash)
    with pytest.raises(RuntimeError):
        commit_audit(ready,report)
    monkeypatch.setattr(tm,'durable_json',durable)
    check=ready[0].get(ready[1],headers=KEY)
    assert check.status_code==200,check.text
    assert check.json()['аудит_требуется'] is False
    assert len((ready[2]/AUDIT_LOG).read_text().splitlines())==1


def test_audit_is_scoped_not_a_new_game_turn(ready):
    seed(ready,2)
    report=audit(ready)
    assert report['период']==[1,2]
    response,_=commit_audit(ready,report)
    assert response.status_code==200
    assert ready[0].get(ready[1],headers=KEY).json()['последний_ход']==2
    assert prep(ready)['номер_хода']==3


def test_second_checkpoint_repeats_audit_without_losing_first(ready):
    seed(ready,15,change_at={1,15})
    first=audit(ready)
    status,_=commit_audit(ready,first)
    assert status.status_code==200
    for _ in range(15):
        p=prep(ready)
        save(ready,p)
    client,url,folder=ready
    assert client.get(url,headers=KEY).json()['аудит_требуется']
    second=audit(ready)
    assert second['период']==[16,30]
    assert second['архив'][0]['сцена']=='Сцена 16'
    assert second['архив'][-1]['сцена']=='Сцена 30'
    status,_=commit_audit(ready,second)
    assert status.status_code==200
    assert len((folder/AUDIT_LOG).read_text().splitlines())==2
    assert prep(ready)['номер_хода']==31
