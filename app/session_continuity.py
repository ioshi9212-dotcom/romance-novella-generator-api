"""Read-only session resume and non-destructive reviewed 60-turn context checkpoints.

Every original journal and scene stays on disk. The compact working view is used
only if the checkpoint's hashes still match the exact old prefixes. If any
covered record was edited (e.g. by an audit), fall back to full source instead
of silently using a stale summary.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .turn_commit import sha, durable_json
from .turn_maintenance import MAINTENANCE, _recent_turns, audit_due, recover_maintenance

CHECKPOINT = 'сводка_контекста.json'
SECTIONS = ('знания', 'личные_события')


def read_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(obj, dict):
            raise ValueError('Not a document')
        return obj
    except (OSError, ValueError) as exc:
        raise HTTPException(409, f'Damaged or missing session document: {path.name}') from exc


def get_checkpoint(root: Path, meta: dict[str, Any]) -> dict[str, Any] | None:
    path = root / CHECKPOINT
    if not path.exists():
        return None
    cp = read_json(path)
    if cp.get('through_turn') != meta.get('last_compacted_turn') or (
        not isinstance(cp.get('memory_anchors'), dict)
        or not isinstance(cp.get('history_anchor'), dict)
    ):
        raise HTTPException(409, 'Compaction checkpoint does not match session metadata')
    return cp


def _index_doc(source: dict[str, Any], sections: tuple[str, ...]) -> dict[str, Any]:
    """Record hashes and counts of existing prefixes, not copies of old text."""
    result: dict[str, Any] = {}
    for section in sections:
        dates = source.get(section, {})
        if not isinstance(dates, dict):
            raise HTTPException(409, f'Invalid dated section: {section}')
        result[section] = {}
        for day, values in dates.items():
            if isinstance(values, list):
                result[section][day] = {'count': len(values), 'sha256': sha(values)}
            else:
                result[section][day] = {'count': None, 'sha256': sha(values)}
    return result


def _tail_doc(source: dict[str, Any], anchors: dict[str, Any], sections: tuple[str, ...]) -> dict[str, Any] | None:
    """Return only new data after checkpoint, or None if any prefix changed."""
    remaining = deepcopy(source)
    for section in sections:
        entries = source.get(section, {})
        old = anchors.get(section, {})
        if not isinstance(entries, dict) or not isinstance(old, dict):
            return None
        compacted = {}
        for day, old_rec in old.items():
            if day not in entries or not isinstance(old_rec, dict):
                return None
            current = entries[day]
            length = old_rec.get('count')
            if length is None:
                if sha(current) != old_rec.get('sha256'):
                    return None
            elif type(length) is int and isinstance(current, list) and len(current) >= length:
                if sha(current[:length]) != old_rec.get('sha256'):
                    return None
                if len(current) > length:
                    compacted[day] = deepcopy(current[length:])
            else:
                return None
        for day, values in entries.items():
            if day not in old:
                compacted[day] = deepcopy(values)
        remaining[section] = compacted
    return remaining


def working_history(source: dict[str, Any], cp: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not cp:
        return source, {}
    # Chronology stores date -> period -> list, unlike character journals.
    flat = {'дни': {}}
    for day, periods in source.get('дни', {}).items():
        if not isinstance(periods, dict):
            return source, {'сжатие_недействительно': True}
        for period, entries in periods.items():
            flat['дни'][f'{day}\u0000{period}'] = entries
    tail = _tail_doc(flat, {'дни':cp['history_anchor']}, ('дни',))
    if tail is None:
        return source, {'сжатие_недействительно': True}
    days: dict[str, dict[str, Any]] = {}
    for key, entries in tail['дни'].items():
        day, period = key.split('\u0000', 1)
        days.setdefault(day, {})[period] = entries
    result = deepcopy(source)
    result['дни'] = days
    return result, {'сводка_прошлых_событий': cp['world_summary'], 'сжато_по_ход': cp['through_turn'], 'старые_даты_доступны':list(source.get('дни', {}))}


def working_memory(source: dict[str, Any], cid: str, cp: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not cp or cid not in cp.get('memory_anchors', {}):
        return source, {}
    tail = _tail_doc(source, cp['memory_anchors'][cid], SECTIONS)
    if tail is None:
        return source, {'сжатие_недействительно': True}
    return tail, {
        'сводка_личной_памяти': cp['character_summaries'][cid],
        'сжато_по_ход': cp['through_turn'],
        'старые_даты_доступны': {
            section:list(cp['memory_anchors'][cid][section]) for section in SECTIONS
        },
    }


def compaction_due(meta: dict[str, Any]) -> bool:
    last = int(meta.get('последний_ход', 0))
    return last > 0 and last % 60 == 0 and int(meta.get('last_compacted_turn', 0)) < last


def prepare_compaction(root: Path, meta: dict[str, Any]) -> dict[str, Any]:
    last = int(meta.get('последний_ход', 0))
    if not compaction_due(meta):
        raise HTTPException(409, 'A reviewed checkpoint can only be created at an unsummarized 60-turn boundary')
    if audit_due(meta) or int(meta.get('last_audited_turn', 0)) < last:
        raise HTTPException(409, 'Complete the 60th-turn audit before preparing compaction')
    old = get_checkpoint(root, meta)
    registry = read_json(root / 'персонажи.json')
    ids = [x['id'] for x in registry.get('персонажи', [])]
    memories: dict[str, Any] = {}
    anchors: dict[str, Any] = {}
    for cid in ids:
        journal = read_json(root / f'память/{cid}.json')
        anchors[cid] = _index_doc(journal, SECTIONS)
        view, extras = working_memory(journal, cid, old)
        memories[cid] = {'память':view, **extras}
    history = read_json(root / 'хронология.json')
    history_view, history_info = working_history(history, old)
    history_anchors: dict[str, Any] = {}
    for day, periods in history.get('дни', {}).items():
        for period, entries in periods.items():
            history_anchors[f'{day}\u0000{period}'] = {
                'count':len(entries) if isinstance(entries, list) else None,
                'sha256':sha(entries),
            }
    turns = _recent_turns(root, last, 60)
    # Don't push all 60 long scenes into a single model context. Four 15-turn
    # audits already reviewed the exact scenes. Include a verifiable index and
    # the recent 15 scenes; the exact older turns can be fetched on demand.
    audits: list[dict[str, Any]] = []
    audit_log = root / 'аудиты.jsonl'
    if audit_log.is_file():
        try:
            with audit_log.open('rb') as stream:
                for line in stream:
                    row = json.loads(line)
                    if last-59 <= row.get('through_turn',-1) <= last:
                        audits.append({'through_turn':row['through_turn'],
                                       'findings':row.get('findings',[]),
                                       'corrected_documents':list(row.get('изменения', {}))})
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(409, 'Damaged audit archive during compaction') from exc
    if [x['through_turn'] for x in audits] != list(range(last-45,last+1,15)):
        raise HTTPException(409, 'Four completed 15-turn audits are required before a 60-turn checkpoint')
    review = {
        'session_id':meta['id'], 'through_turn':last,
        'period':[last-59,last], 'previous_checkpoint_turn':old['through_turn'] if old else 0,
        'previous_world_summary':old['world_summary'] if old else '',
        'characters':memories,
        'history':history_view, 'history_info':history_info,
        'archive':[{'номер':x['номер'], 'scene_sha256':sha(x['сцена']),
                    'кратко':x['сцена'][:300], 'полная_длина':len(x['сцена'])} for x in turns],
        'recent_scenes':[{'номер':x['номер'], 'ввод':x['ввод'], 'сцена':x['сцена']} for x in turns[-15:]],
        'audits':audits,
        'older_scene_lookup':'GET /sessions/{id}/turns?from_turn=N&to_turn=M (maximum 15)',
        'character_ids':ids,
    }
    review['review_sha256'] = sha(review)
    return review


def commit_compaction(root: Path, meta: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    last = int(meta.get('последний_ход', 0))
    existing = get_checkpoint(root, meta)
    request_digest = sha(payload)
    if existing and existing.get('through_turn') == last:
        if existing.get('request_sha256') == request_digest:
            return {'status':'already_compacted','through_turn':last}
        raise HTTPException(409, 'This 60-turn checkpoint was already saved with different content')
    prepared = prepare_compaction(root, meta)
    if payload['through_turn'] != last or payload['review_sha256'] != prepared['review_sha256']:
        raise HTTPException(409, 'Compaction context has changed; prepare again')
    if not payload['reviewed_against_archive']:
        raise HTTPException(409, 'Compaction was not reviewed against the actual archive')
    ids = set(prepared['character_ids'])
    if set(payload['character_summaries']) != ids:
        raise HTTPException(422, 'Provide a reviewed character summary for every registered character')
    if not payload['world_summary'].strip() or any(not text.strip() for text in payload['character_summaries'].values()):
        raise HTTPException(422, 'Empty long-term summaries are not allowed')
    memory_anchors: dict[str, Any] = {}
    for cid in ids:
        journal = read_json(root / f'память/{cid}.json')
        memory_anchors[cid] = _index_doc(journal, SECTIONS)
    history = read_json(root/'хронология.json')
    history_anchor: dict[str, Any] = {}
    for day, periods in history.get('дни', {}).items():
        for period, entries in periods.items():
            history_anchor[f'{day}\u0000{period}'] = {
                'count':len(entries) if isinstance(entries, list) else None,
                'sha256':sha(entries),
            }
    checkpoint = {
        'through_turn':last,
        'world_summary':payload['world_summary'],
        'character_summaries':payload['character_summaries'],
        'memory_anchors':memory_anchors,
        'history_anchor':history_anchor,
        'review_sha256':prepared['review_sha256'],
        'request_sha256':request_digest,
    }
    new_meta = deepcopy(meta)
    new_meta['last_compacted_turn'] = last
    transaction = {'operation':'compaction','after':{CHECKPOINT:checkpoint},'meta_after':new_meta}
    durable_json(root/MAINTENANCE,transaction)
    recover_maintenance(root)
    return {'status':'compacted','through_turn':last,'full_memory_preserved':True}


def resume_session(root: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """New-chat handoff: small current snapshot, not a second copy of session."""
    phase = meta.get('этап')
    response = {
        'session_id':meta['id'], 'этап':phase,
        'последний_ход':meta.get('последний_ход',0),
        'следующий_ход':int(meta.get('последний_ход',0))+1,
        'аудит_требуется':audit_due(meta),
        'сжатие_требуется':compaction_due(meta),
        'последнее_сжатие':int(meta.get('last_compacted_turn',0)),
    }
    if phase not in {'игра','готово_к_игре'}:
        response['дальше'] = 'Продолжить существующий этап создания через /raw, /advance или /data'
        return response
    from .turn_context import _last_scenes, _preview_entries
    roster = read_json(root/'персонажи.json')
    state = read_json(root/'state.json')
    lore = read_json(root/'скрытый_лор_и_крючки.json')
    cp = get_checkpoint(root,meta)
    response.update({
        'название':read_json(root/'анкета.json').get('название',''),
        'state':state,
        'реестр':roster,
        'активные_крючки':_preview_entries(lore.get('крючки',[])),
        'последние_сцены':_last_scenes(root),
        'долговременная_сводка':cp['world_summary'] if cp else '',
        'дальше': ('Сначала выполнить /prepare-audit' if audit_due(meta) else
                   'После аудита выполнить /prepare-compaction' if compaction_due(meta) else
                   'Вызвать /prepare-turn с новым пользовательским вводом'),
    })
    return response


def archived_scenes(root: Path, meta: dict[str, Any], first: int, last: int) -> dict[str, Any]:
    """Bounded exact scene lookup; never read hidden technical document snapshots."""
    current = int(meta.get('последний_ход',0))
    if first < 1 or last < first or last > current or last-first+1 > 15:
        raise HTTPException(422, 'Choose existing consecutive turn numbers (maximum 15)')
    archive = root/'ходы.jsonl'
    if not archive.is_file():
        raise HTTPException(409, 'Turn archive is missing')
    rows: list[dict[str, Any]] = []
    try:
        with archive.open('rb') as stream:
            for raw in stream:
                item = json.loads(raw)
                number = item.get('номер') if isinstance(item,dict) else None
                if type(number) is int and first <= number <= last:
                    rows.append({'номер':number,'turn_id':item['turn_id'],
                                 'ввод':item['ввод'],'сцена':item['сцена']})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, 'Turn archive is damaged') from exc
    if [row['номер'] for row in rows] != list(range(first,last+1)):
        raise HTTPException(409, 'Requested archive has missing or duplicate turns')
    return {'session_id':meta['id'],'диапазон':[first,last],'сцены':rows}