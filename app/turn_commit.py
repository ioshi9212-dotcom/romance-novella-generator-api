"""Single-session turn transaction: small patches, durable redo journal, append-only archive.

No scene decisions, narrative rules or automatic character knowledge inference here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

JOURNAL = '.pending_turn.json'
ARCHIVE = 'ходы.jsonl'


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def durable_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.tmp_', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8') + b'\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sync_directory(root: Path) -> None:
    fd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def patch_path(pointer: str) -> list[str]:
    if not isinstance(pointer, str) or (pointer and not pointer.startswith('/')):
        raise HTTPException(422, 'Invalid JSON pointer')
    parts = pointer[1:].split('/') if pointer else []
    for piece in parts:
        # Forbid malformed escapes, ambiguous numeric indices, and template metadata edits.
        if re.search(r'~(?![01])', piece):
            raise HTTPException(422, 'Invalid JSON pointer escape')
    parts = [part.replace('~1', '/').replace('~0', '~') for part in parts]
    if parts and parts[0].startswith('_'):
        raise HTTPException(422, 'Template metadata cannot be changed during a turn')
    return parts


def apply_patches(existing: dict[str, Any] | None, operations: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = deepcopy(existing) if existing is not None else {}
    if not operations:
        raise HTTPException(422, 'Empty patch list')
    for operation in operations:
        op = operation['op']
        path = patch_path(operation['path'])
        value = operation.get('value')
        if not path:
            if op != 'set' or existing is not None or not isinstance(value, dict):
                raise HTTPException(422, 'Whole-document set is only available for new files')
            result = deepcopy(value)
            continue
        parent: Any = result
        for part in path[:-1]:
            if not isinstance(parent, dict):
                raise HTTPException(422, 'Patch must traverse JSON objects')
            if part not in parent:
                if op == 'remove':
                    raise HTTPException(422, 'Cannot remove missing path')
                parent[part] = {}
            parent = parent[part]
        if not isinstance(parent, dict):
            raise HTTPException(422, 'Patch parent must be an object')
        field = path[-1]
        if op == 'set':
            if 'value' not in operation:
                raise HTTPException(422, 'Set needs value')
            parent[field] = deepcopy(value)
        elif op == 'append':
            if 'value' not in operation:
                raise HTTPException(422, 'Append needs value')
            if field not in parent:
                parent[field] = []
            if not isinstance(parent[field], list):
                raise HTTPException(422, 'Append target must be an array')
            parent[field].append(deepcopy(value))
        elif op == 'merge_by_id':
            if not isinstance(parent.get(field), list):
                raise HTTPException(422, 'merge_by_id target must be an existing array')
            if not isinstance(value, dict) or not isinstance(value.get('id'), str):
                raise HTTPException(422, 'merge_by_id value must contain a character ID')
            matches = [row for row in parent[field] if isinstance(row, dict) and row.get('id') == value['id']]
            if len(matches) != 1:
                raise HTTPException(422, 'merge_by_id requires exactly one matching record')
            for key, new_value in value.items():
                if key != 'id':
                    matches[0][key] = deepcopy(new_value)
        elif op == 'remove':
            if field not in parent:
                raise HTTPException(422, 'Cannot remove missing path')
            del parent[field]
        else:
            raise HTTPException(422, 'Unknown patch operation')
    return result


def archive_entry_at(root: Path, turn_number: int) -> dict[str, Any] | None:
    archive = root / ARCHIVE
    if not archive.exists():
        return None
    with archive.open('rb') as source:
        for raw in source:
            try:
                item = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                raise HTTPException(409, 'Corrupted turn archive') from exc
            if isinstance(item, dict) and item.get('номер') == turn_number:
                return item
    return None


def _archive_last(root: Path) -> tuple[dict[str, Any] | None, int]:
    """Return last complete archive entry and truncate an interrupted partial tail.

    Must only run while the durable redo journal exists and session lock is held.
    """
    archive = root / ARCHIVE
    with archive.open('a+b') as stream:
        stream.seek(0, 2)
        end = stream.tell()
        if not end:
            return None, 0
        stream.seek(end - 1)
        if stream.read(1) != b'\n':
            # An interrupted append can leave a partial final record.
            position = end - 1
            while position >= 0:
                stream.seek(position)
                if stream.read(1) == b'\n':
                    break
                position -= 1
            end = position + 1
            stream.truncate(end)
            stream.flush()
            os.fsync(stream.fileno())
        if end == 0:
            return None, 0
        pos = end - 2
        while pos >= 0:
            stream.seek(pos)
            if stream.read(1) == b'\n':
                break
            pos -= 1
        stream.seek(pos + 1)
        raw = stream.read(end - (pos + 1)).strip()
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(409, 'Last archived turn is damaged') from exc
        if not isinstance(row, dict):
            raise HTTPException(409, 'Last archived turn is invalid')
        return row, end


def _ensure_archive(root: Path, receipt: dict[str, Any]) -> None:
    last, _ = _archive_last(root)
    number = receipt['номер']
    if last and last.get('номер') == number:
        if last.get('turn_id') != receipt['turn_id'] or last.get('request_sha256') != receipt['request_sha256']:
            raise HTTPException(409, 'Archived turn differs from pending transaction')
        return
    if last and last.get('номер') != number - 1:
        raise HTTPException(409, 'Turn archive sequence is inconsistent')
    if not last and number != 1:
        raise HTTPException(409, 'Turn archive is missing previous records')
    with (root / ARCHIVE).open('ab') as out:
        out.write(canonical(receipt) + b'\n')
        out.flush()
        os.fsync(out.fileno())
    sync_directory(root)


def recover_pending(root: Path) -> None:
    pending = root / JOURNAL
    if not pending.is_file():
        return
    try:
        transaction = json.loads(pending.read_text(encoding='utf-8'))
        receipt = transaction['receipt']
        for name, document in transaction['after'].items():
            durable_json(root / name, document)
        _ensure_archive(root, receipt)
        durable_json(root / 'сессия.json', transaction['meta_after'])
        pending.unlink()
        sync_directory(root)
    except HTTPException:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, 'A pending turn could not be recovered') from exc


def verify_overlay(
    root: Path, after: dict[str, dict[str, Any]], foundation_check: Callable[[Path], list[str]]
) -> list[str]:
    """Use hardlinks for unchanged files and a temporary overlay to reuse existing validation.

    Changes are never written to the live novel until all checks succeed.
    """
    with tempfile.TemporaryDirectory(prefix='.validation_', dir=root) as directory:
        sandbox = Path(directory)
        for name in ('анкета.json', 'персонажи.json', 'state.json', 'хронология.json',
                     'скрытый_лор_и_крючки.json', 'отношения.json', 'локации.json'):
            if name not in after:
                try:
                    os.link(root / name, sandbox / name)
                except OSError:
                    shutil.copyfile(root / name, sandbox / name)
        for subdir in ('карточки', 'память'):
            source = root / subdir
            dest = sandbox / subdir
            dest.mkdir()
            if source.exists():
                for file in source.glob('*.json'):
                    name = f'{subdir}/{file.name}'
                    if name not in after:
                        try:
                            os.link(file, dest / file.name)
                        except OSError:
                            shutil.copyfile(file, dest / file.name)
        for name, document in after.items():
            destination = sandbox / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(canonical(document))
        issues = foundation_check(sandbox)
        from .turn_context import _scene_ids
        state = json.loads((sandbox / 'state.json').read_text(encoding='utf-8'))
        try:
            _scene_ids(state)
        except HTTPException as exc:
            issues.append(str(exc.detail))
        return issues



def validate_relationship_steps(
    changed: dict[str, dict[str, Any]],
    exceptions: list[dict[str, Any]],
    previously_registered: set[str],
) -> None:
    """Enforce gradual changes without imposing any relationship vocabulary.

    Existing NPC->POV parameters may move by at most 3 per game turn.
    The scene writer may mark a specific larger change as critical and state
    why. Backend validates the declaration, not the literary severity.
    New NPCs may enter with established backstory relationships.
    """
    delta_exceptions: dict[tuple[str, str], str] = {}
    for exception in exceptions:
        owner = exception['owner_id'].strip()
        parameter = exception['parameter'].strip()
        reason = exception['reason'].strip()
        key = (owner, parameter)
        if not parameter or not owner or len(reason) < 12:
            raise HTTPException(422, "Critical relationship change must identify the owner, parameter and meaningful reason")
        if key in delta_exceptions:
            raise HTTPException(422, "Duplicate critical relationship exception for one parameter")
        delta_exceptions[key] = reason

    relation_change = changed.get('отношения.json')
    if relation_change is None:
        if delta_exceptions:
            raise HTTPException(422, "Relationship exceptions require a real change to отношения.json")
        return
    before = relation_change['до'] or {}
    after = relation_change['после']
    previous_owners = before.get('персонажи', {})
    current_owners = after.get('персонажи', {})
    used: set[tuple[str, str]] = set()
    for owner in set(previous_owners) | set(current_owners):
        if owner not in previously_registered:
            # A genuinely new permanent character can have established
            # relationships from their pre-introduction personal history.
            continue
        prev = previous_owners.get(owner) or {}
        current = current_owners.get(owner) or {}
        old_params = (prev.get('к_POV') or {}).get('параметры') or {}
        new_params = (current.get('к_POV') or {}).get('параметры') or {}
        # Replacing the entire parameter dictionary with the newly changed
        # metric used to silently erase unrelated existing relationship axes.
        # Existing axes remain as-is (or at value 0); never drop them as a
        # side effect of adding or changing another metric.
        dropped = sorted(set(old_params) - set(new_params))
        if dropped:
            raise HTTPException(409, {
                "code": "RELATIONSHIP_METRICS_DROPPED",
                "character_id": owner,
                "missing_parameters": dropped,
                "hint": (
                    "Do not replace the whole parameters object. "
                    "Use set /персонажи/<id>/к_POV/параметры/<parameter> "
                    "to change only one metric and preserve all others."
                ),
            })
        for metric in set(old_params) | set(new_params):
            previous_value = old_params.get(metric, 0)
            current_value = new_params.get(metric, 0)
            # Invalid values are rejected by the foundation validator before
            # the call to this function.
            movement = abs(current_value - previous_value)
            key = (owner, metric)
            if movement > 3:
                if key not in delta_exceptions:
                    raise HTTPException(409, {
                        "code": "RELATIONSHIP_CHANGE_TOO_LARGE",
                        "character_id": owner, "parameter": metric,
                        "actual_delta": movement, "normal_max_delta": 3,
                        "hint": "Use a specific relationship_exceptions entry only for a critical event actually shown in the scene.",
                    })
                used.add(key)
    if used != set(delta_exceptions):
        raise HTTPException(422, "Critical relationship exceptions must refer to existing large changes")


def save_turn(
    root: Path, meta: dict[str, Any], payload: dict[str, Any],
    valid_path: Callable[[str], bool], foundation_check: Callable[[Path], list[str]],
    build_packet: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    turn_id = payload['turn_id']
    number = meta['последний_ход'] + 1
    proposed = f"{meta['id']}:{number}"
    digest = sha(payload)
    if turn_id != proposed:
        previous_number = None
        if isinstance(turn_id, str) and turn_id.startswith(meta['id'] + ':'):
            try:
                previous_number = int(turn_id.rsplit(':', 1)[1])
            except ValueError:
                pass
        if previous_number is not None and 1 <= previous_number <= meta['последний_ход']:
            old = archive_entry_at(root, previous_number)
            if old and old.get('turn_id') == turn_id and old.get('request_sha256') == digest:
                return {'turn_id': turn_id, 'номер_хода': previous_number, 'status': 'already_saved', 'changed_files': list(old.get('изменения', {}))}
            raise HTTPException(409, 'An already saved turn cannot be replaced')
        raise HTTPException(409, f'Stale or invalid turn_id, next expected: {proposed}')

    selection = {k: payload.get(k, []) for k in ('additional_character_ids', 'selected_hook_indices', 'selected_secret_indices', 'additional_location_ids', 'full_memory_character_ids')}
    selection['full_chronology'] = payload.get('full_chronology', False)
    packet = build_packet(
        root=root, meta=meta, user_input=payload['user_input'],
        **selection,
    )
    if payload['context_sha256'] != packet['контекст_sha256']:
        raise HTTPException(409, {
            'code': 'STALE_TURN_CONTEXT',
            'reason': (
                'Game data, Rules or Skin Builder changed after prepare-turn. '
                'Repeat prepareTurn, read all chunks and write the scene using '
                'the current Skin Builder before committing.'
            ),
        })

    loaded = set(packet['персонажи_подробно'])
    existing = {row['id'] for row in packet['режиссёр']['реестр']['персонажи']}
    patches = payload['updates']
    after: dict[str, dict[str, Any]] = {}
    changed: dict[str, dict[str, Any]] = {}
    for name, operations in patches.items():
        if not valid_path(name):
            raise HTTPException(422, f'Not a novel data file: {name}')
        if name.startswith(('карточки/', 'память/')):
            character_id = name.split('/')[1][:-5]
            if character_id in existing and character_id not in loaded:
                raise HTTPException(409, f'Character was not prepared: {character_id}')
        target = root / name
        before = json.loads(target.read_text(encoding='utf-8')) if target.is_file() else None
        new = apply_patches(before, operations)
        if before == new:
            continue
        after[name] = new
        changed[name] = {'до': before, 'после': new}
    if after:
        issues = verify_overlay(root, after, foundation_check)
        if issues:
            raise HTTPException(409, {'code': 'TURN_INVALID', 'issues': issues})
    validate_relationship_steps(changed, payload.get('relationship_exceptions', []), existing)
    # Even a narrative-only turn must be durably archived to advance gameplay.
    entry = {
        'номер': number, 'turn_id': turn_id,
        'request_sha256': digest, 'context_sha256': payload['context_sha256'],
        'ввод': payload['user_input'], 'сцена': payload['scene'],
        'изменения': changed,
    }
    meta_after = deepcopy(meta)
    meta_after['последний_ход'] = number
    meta_after['этап'] = 'игра'
    transaction = {'receipt': entry, 'after': after, 'meta_after': meta_after}
    durable_json(root / JOURNAL, transaction)
    recover_pending(root)
    return {'turn_id': turn_id, 'номер_хода': number, 'status': 'saved', 'changed_files': list(after)}