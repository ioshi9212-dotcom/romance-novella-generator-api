"""Durable last-turn rollback and archive-grounded, model-reviewed memory audits.

This module never invents corrections: audit corrections require explicit evidence
turn numbers and are committed as sparse document patches after human/model review.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from .turn_commit import (
    ARCHIVE, JOURNAL, apply_patches, canonical, durable_json,
    sha, sync_directory, verify_overlay,
)

MAINTENANCE = '.pending_maintenance.json'
AUDIT_LOG = 'аудиты.jsonl'


def _last_entry(root: Path, name: str) -> tuple[dict[str, Any] | None, int]:
    """Get complete last JSONL record and its byte start; do not mutate read-only data."""
    path = root / name
    if not path.exists():
        return None, 0
    with path.open('rb') as stream:
        stream.seek(0, 2)
        end = stream.tell()
        if not end:
            return None, 0
        stream.seek(end - 1)
        if stream.read(1) != b'\n':
            raise HTTPException(409, f'{name} has an unfinished last record')
        pos = end - 2
        while pos >= 0:
            stream.seek(pos)
            if stream.read(1) == b'\n':
                break
            pos -= 1
        start = pos + 1
        stream.seek(start)
        raw = stream.read(end - start)
    try:
        row = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(409, f'{name} has a damaged record') from exc
    if not isinstance(row, dict):
        raise HTTPException(409, f'{name} has an invalid last record')
    return row, start


def _append_once(root: Path, name: str, receipt: dict[str, Any]) -> None:
    """Append exactly once; truncate a partial tail only while redo journal exists."""
    path = root / name
    if path.exists():
        with path.open('rb+') as stream:
            stream.seek(0, 2)
            end = stream.tell()
            if end:
                stream.seek(end - 1)
                if stream.read(1) != b'\n':
                    pos = end - 1
                    while pos >= 0:
                        stream.seek(pos)
                        if stream.read(1) == b'\n':
                            break
                        pos -= 1
                    stream.truncate(pos + 1)
                    stream.flush()
                    os.fsync(stream.fileno())
    last, _ = _last_entry(root, name)
    if last and last.get('audit_id') == receipt.get('audit_id'):
        if last.get('request_sha256') != receipt.get('request_sha256'):
            raise HTTPException(409, 'Audit archive entry differs from pending transaction')
        return
    if last and last.get('through_turn', 0) >= receipt['through_turn']:
        raise HTTPException(409, 'Audit archive is out of order')
    with path.open('ab') as stream:
        stream.write(canonical(receipt) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(root)


def _remove_last(root: Path, name: str, id_field: str, target: str, previous: int) -> None:
    last, start = _last_entry(root, name)
    if last is None:
        if previous != 0:
            raise HTTPException(409, f'{name} is missing previous records')
        return
    if last.get(id_field) == target:
        with (root / name).open('rb+') as stream:
            stream.truncate(start)
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(root)
    elif last.get('номер' if name == ARCHIVE else 'through_turn') != previous:
        raise HTTPException(409, f'{name} cannot safely truncate a different record')


def recover_maintenance(root: Path) -> None:
    """Idempotently finish a pending maintenance transaction under session lock."""
    pending = root / MAINTENANCE
    if not pending.is_file():
        return
    try:
        transaction = json.loads(pending.read_text(encoding='utf-8'))
        for name, document in transaction['after'].items():
            destination = root / name
            if document is None:
                destination.unlink(missing_ok=True)
                sync_directory(destination.parent)
            else:
                durable_json(destination, document)
        if transaction['operation'] == 'audit':
            _append_once(root, AUDIT_LOG, transaction['receipt'])
        elif transaction['operation'] == 'compaction':
            pass  # The checkpoint and session metadata are journaled above.
        elif transaction['operation'] == 'rollback':
            old_turn = transaction['turn_id']
            prev = transaction['meta_after']['последний_ход']
            _remove_last(root, ARCHIVE, 'turn_id', old_turn, prev)
            audit_id = transaction.get('audit_to_remove')
            if audit_id:
                _remove_last(root, AUDIT_LOG, 'audit_id', audit_id,
                             transaction['meta_after'].get('last_audited_turn', 0))
        else:
            raise HTTPException(409, 'Unrecognized maintenance transaction')
        durable_json(root / 'сессия.json', transaction['meta_after'])
        pending.unlink()
        sync_directory(root)
    except HTTPException:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, 'Pending maintenance could not be recovered') from exc


def audit_due(meta: dict[str, Any]) -> bool:
    last = int(meta.get('последний_ход', 0))
    audited = int(meta.get('last_audited_turn', 0))
    return last >= 15 and (last // 15) * 15 > audited


def _recent_turns(root: Path, last: int, count: int) -> list[dict[str, Any]]:
    start = max(1, last - count + 1)
    rows: list[dict[str, Any]] = []
    archive = root / ARCHIVE
    if not archive.exists():
        raise HTTPException(409, 'Missing turn archive')
    try:
        with archive.open('rb') as f:
            for raw in f:
                item = json.loads(raw)
                if isinstance(item, dict) and start <= item.get('номер', -1) <= last:
                    rows.append(item)
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(409, 'Turn archive cannot be audited') from exc
    if [x.get('номер') for x in rows] != list(range(start, last + 1)):
        raise HTTPException(409, 'Audit archive has missing or duplicated turns')
    return rows


def prepare_audit(root: Path, meta: dict[str, Any], character_ids: list[str]) -> dict[str, Any]:
    """Return exact evidence and relevant current files, without changing any data."""
    last = int(meta.get('последний_ход', 0))
    if last < 1:
        raise HTTPException(409, 'There are no turns to audit')
    latest_checkpoint = (last // 15) * 15
    due = audit_due(meta)
    if not due and last <= int(meta.get('last_audited_turn', 0)):
        raise HTTPException(409, 'Current turns have already been audited')
    # At checkpoint 60 the detailed 15-turn audit remains bounded. Extended
    # compaction is flagged for an explicitly reviewed subsequent operation.
    turns = _recent_turns(root, last, 15)
    registry = json.loads((root / 'персонажи.json').read_text(encoding='utf-8'))
    known = {p.get('id') for p in registry.get('персонажи', []) if isinstance(p, dict)}
    for cid in character_ids:
        if cid not in known:
            raise HTTPException(422, f'Unknown audit character: {cid}')
    state = json.loads((root / 'state.json').read_text(encoding='utf-8'))
    involved = {p['id'] for key in ('физически', 'удалённо') for p in state.get(key, []) if isinstance(p, dict) and 'id' in p}
    for turn in turns:
        for name in turn.get('изменения', {}):
            if name.startswith(('память/', 'карточки/')) and name.endswith('.json'):
                involved.add(name.split('/')[1][:-5])
    selected = sorted((involved | set(character_ids)) & known)
    memories = {cid:json.loads((root / f'память/{cid}.json').read_text(encoding='utf-8')) for cid in selected}
    bundle = {
        'session_id': meta['id'], 'through_turn':last,
        'период': [turns[0]['номер'], last],
        'checkpoints': {'audit_due': due, 'next_checkpoint':latest_checkpoint + 15,
                        'compaction_60_due':last % 60 == 0},
        'архив': [{'номер':x['номер'], 'turn_id':x['turn_id'],
                    'ввод':x['ввод'], 'сцена':x['сцена'],
                    'изменённые_файлы':list(x.get('изменения', {}))} for x in turns],
        'реестр': registry,
        'state':state,
        'отношения':json.loads((root/'отношения.json').read_text(encoding='utf-8')),
        'хронология':json.loads((root/'хронология.json').read_text(encoding='utf-8')),
        'скрытый_лор_и_крючки':json.loads((root/'скрытый_лор_и_крючки.json').read_text(encoding='utf-8')),
        'память':memories,
        'загруженные_id':selected,
        'доступные_для_догрузки_id':sorted(known - set(selected)),
    }
    bundle['audit_sha256'] = sha(bundle)
    return bundle


def commit_audit(root: Path, meta: dict[str, Any], payload: dict[str, Any],
                 valid_path: Callable[[str], bool],
                 foundation_check: Callable[[Path], list[str]]) -> dict[str, Any]:
    digest = sha(payload)
    last_audit, _ = _last_entry(root, AUDIT_LOG)
    if last_audit and last_audit.get('request_sha256') == digest:
        return {'status':'already_audited', 'through_turn':last_audit['through_turn'],
                'changed_files':list(last_audit['изменения'])}
    current = prepare_audit(root, meta, payload['character_ids'])
    if payload['through_turn'] != current['through_turn'] or payload['audit_sha256'] != current['audit_sha256']:
        raise HTTPException(409, 'Audit context changed; prepare-audit again')
    if not payload['reviewed_against_archive']:
        raise HTTPException(409, 'The archive review has not been confirmed')
    changes: dict[str, dict[str, Any]] = {}
    after: dict[str, dict[str, Any]] = {}
    start, last = current['период']
    for path, patches in payload['updates'].items():
        if not valid_path(path):
            raise HTTPException(422, f'Invalid audit document: {path}')
        if path.startswith(('память/', 'карточки/')) and path.split('/')[1][:-5] not in current['загруженные_id']:
            raise HTTPException(409, f'Character not loaded for audit: {path}')
        evidence = payload['evidence_turns'].get(path)
        if not isinstance(evidence, list) or not evidence or any(type(i) is not int or i < start or i > last for i in evidence):
            raise HTTPException(422, f'Audit update lacks valid source turns: {path}')
        target = root/path
        if not target.is_file():
            raise HTTPException(422, 'Audit cannot invent documents: ' + path)
        original = json.loads(target.read_text(encoding='utf-8'))
        updated = apply_patches(original, patches)
        if updated != original:
            changes[path] = {'до':original, 'после':updated}
            after[path] = updated
    if after:
        issues = verify_overlay(root, after, foundation_check)
        if issues:
            raise HTTPException(409, {'code':'AUDIT_INVALID','issues':issues})
    receipt = {'audit_id':f"{meta['id']}:audit:{last}", 'through_turn':last,
               'request_sha256':digest, 'archive_sha256':payload['audit_sha256'],
               'evidence_turns':payload['evidence_turns'],
               'findings':payload['findings'],
               'previous_audited_turn':int(meta.get('last_audited_turn',0)),
               'previous_compaction_review_turn':int(meta.get('last_compaction_review_turn',0)),
               'изменения':changes}
    new_meta = deepcopy(meta)
    new_meta['last_audited_turn'] = last
    if last % 60 == 0:
        new_meta['last_compaction_review_turn'] = last
    transaction = {'operation':'audit','receipt':receipt,'after':after,'meta_after':new_meta}
    durable_json(root/MAINTENANCE, transaction)
    recover_maintenance(root)
    return {'status':'audited','through_turn':last, 'changed_files':list(after),
            'compaction_60_reviewed':last % 60 == 0}


def rollback_last(root: Path, meta: dict[str, Any], expected_turn_id: str) -> dict[str, Any]:
    number = int(meta.get('последний_ход', 0))
    if number <= 0:
        raise HTTPException(409, 'There are no turns to roll back')
    last, _ = _last_entry(root, ARCHIVE)
    if not last or last.get('номер') != number or last.get('turn_id') != expected_turn_id:
        raise HTTPException(409, 'Expected last turn does not match the saved archive')
    # An audit at this same last turn is undone together with its corrections.
    audit, _ = _last_entry(root, AUDIT_LOG)
    undo_audit = audit is not None and audit.get('through_turn') == number
    audit_changes = audit.get('изменения', {}) if undo_audit else {}
    if audit and audit.get('through_turn', 0) > number:
        raise HTTPException(409, 'The audit log refers to a future turn')
    previous: dict[str, dict[str, Any] | None] = {}
    for name, change in audit_changes.items():
        previous[name] = change['до']
    for name, change in last.get('изменения', {}).items():
        # Undo latest turn back to its original state, even if its last version
        # was later corrected by audit.
        previous[name] = change['до']
    meta_after = deepcopy(meta)
    meta_after['последний_ход'] = number - 1
    # A compact checkpoint for the removed turn must not cite undone events.
    if int(meta.get('last_compacted_turn', 0)) == number:
        from .session_continuity import CHECKPOINT
        previous[CHECKPOINT] = None
        meta_after['last_compacted_turn'] = 0
    if undo_audit:
        meta_after['last_audited_turn'] = int(audit.get('previous_audited_turn',0))
        if meta_after.get('last_compaction_review_turn') == number:
            meta_after['last_compaction_review_turn'] = int(audit.get('previous_compaction_review_turn',0))
    if number == 1:
        meta_after['этап'] = 'готово_к_игре'
    transaction = {'operation':'rollback','turn_id':expected_turn_id,'after':previous,
                   'audit_to_remove':audit['audit_id'] if undo_audit else None,
                   'meta_after':meta_after}
    durable_json(root/MAINTENANCE,transaction)
    recover_maintenance(root)
    return {'status':'rolled_back','removed_turn_id':expected_turn_id,
            'последний_ход':number-1,'restored_files':list(previous),
            'audit_reverted':undo_audit}
