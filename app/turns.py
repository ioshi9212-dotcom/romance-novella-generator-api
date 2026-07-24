from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.context_builder import build_frozen_packet
from app.models import (
    AbortTurnResponse,
    CommitTurnRequest,
    ContextChunk,
    PrepareTurnRequest,
    PrepareTurnResponse,
    SessionStatus,
    TurnMode,
    TurnReceipt,
)
from app.storage import (
    atomic_write_json,
    deep_merge,
    execute_transaction,
    json_text,
    jsonl_with_event,
    read_json,
    read_text,
    recover_transactions,
    require_session,
    safe_id,
    session_lock,
    utc_now,
)
from app.validator import validate_commit_semantics


def _input_hash(user_input: str, mode: TurnMode, state_version: int) -> str:
    value = f"{state_version}\0{mode.value}\0{user_input}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _pending_directories(root: Path) -> list[Path]:
    pending_root = root / "transactions" / "pending"
    if not pending_root.is_dir():
        return []
    return sorted((path for path in pending_root.iterdir() if path.is_dir()), reverse=True)


def _response_from_packet(
    session_id: str,
    turn_id: str,
    metadata: dict[str, Any],
    packet: dict[str, Any],
    chunk_index: int = 0,
) -> PrepareTurnResponse:
    chunks = packet.get("chunks") or [[]]
    if chunk_index < 0 or chunk_index >= len(chunks):
        raise HTTPException(status_code=404, detail="Context chunk not found")
    has_more = chunk_index + 1 < len(chunks)
    return PrepareTurnResponse(
        status="prepared",
        session_id=session_id,
        turn_id=turn_id,
        mode=TurnMode(metadata["mode"]),
        base_state_version=int(metadata["base_state_version"]),
        input_hash=str(metadata["input_hash"]),
        chunk=ContextChunk(chunk_index=chunk_index, sections=chunks[chunk_index]),
        has_more=has_more,
        next_chunk_index=chunk_index + 1 if has_more else None,
        total_chunks=len(chunks),
        warnings=packet.get("warnings", []),
    )


def prepare_turn(session_id: str, request: PrepareTurnRequest) -> PrepareTurnResponse:
    root = require_session(session_id)
    with session_lock(root):
        recover_transactions(root)
        session = read_json(root / "session.json", default={}) or {}
        if session.get("status") != SessionStatus.ACTIVE.value:
            raise HTTPException(status_code=409, detail="Session is not active")
        state_version = int(session.get("state_version", 0))
        input_hash = _input_hash(request.user_input, request.mode, state_version)

        open_pending: list[tuple[Path, dict[str, Any]]] = []
        for directory in _pending_directories(root):
            metadata = read_json(directory / "metadata.json", default={}) or {}
            if metadata.get("status") != "open":
                continue
            if metadata.get("input_hash") == input_hash:
                packet = read_json(directory / "packet.json", default={}) or {}
                return _response_from_packet(session_id, directory.name, metadata, packet)
            open_pending.append((directory, metadata))

        if open_pending and not request.replace_pending:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "pending_turn_exists",
                    "pending_turn_id": open_pending[0][0].name,
                },
            )
        for directory, metadata in open_pending:
            metadata["status"] = "aborted"
            metadata["aborted_at"] = utc_now()
            metadata["abort_reason"] = "replaced by newer prepareTurn"
            atomic_write_json(directory / "metadata.json", metadata)

        turn_id = f"turn_{uuid4().hex}"
        packet = build_frozen_packet(
            root,
            request.user_input,
            request.mode.value,
            state_version,
            int(session.get("turn_number", 0)),
        )
        directory = root / "transactions" / "pending" / turn_id
        directory.mkdir(parents=True, exist_ok=False)
        metadata = {
            "turn_id": turn_id,
            "session_id": session_id,
            "status": "open",
            "mode": request.mode.value,
            "base_state_version": state_version,
            "input_hash": input_hash,
            "prepared_at": utc_now(),
        }
        atomic_write_json(directory / "metadata.json", metadata)
        atomic_write_json(directory / "packet.json", packet)
        return _response_from_packet(session_id, turn_id, metadata, packet)


def get_turn_chunk(session_id: str, turn_id: str, chunk_index: int) -> PrepareTurnResponse:
    root = require_session(session_id)
    turn_id = safe_id(turn_id, "turn_id")
    with session_lock(root):
        recover_transactions(root)
        directory = root / "transactions" / "pending" / turn_id
        metadata = read_json(directory / "metadata.json", default=None)
        packet = read_json(directory / "packet.json", default=None)
        if not isinstance(metadata, dict) or not isinstance(packet, dict):
            raise HTTPException(status_code=404, detail="Prepared turn not found")
        if metadata.get("status") not in {"open", "committed"}:
            raise HTTPException(status_code=409, detail="Prepared turn is not readable")
        return _response_from_packet(session_id, turn_id, metadata, packet, chunk_index)


def _advance_datetime(current: dict[str, Any], minutes: int, warnings: list[str]) -> None:
    if not minutes:
        return
    raw = current.get("datetime")
    if not isinstance(raw, str):
        warnings.append("time_advance_minutes ignored because current.datetime is missing")
        return
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        warnings.append("time_advance_minutes ignored because current.datetime is invalid")
        return
    current["datetime"] = (value + timedelta(minutes=minutes)).isoformat()


def _character_ids(index: dict[str, Any]) -> set[str]:
    return set(str(key) for key in (index.get("characters", {}) or {}))


def _apply_knowledge_events(
    root: Path,
    writes: dict[str, str],
    turn_id: str,
    scene_number: int | None,
    events: list[Any],
    valid_character_ids: set[str],
) -> None:
    grouped: dict[str, list[Any]] = {}
    for event in events:
        if event.character_id not in valid_character_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown knowledge character: {event.character_id}",
            )
        grouped.setdefault(event.character_id, []).append(event)
    for character_id, items in grouped.items():
        relative_path = f"state/knowledge/{character_id}.json"
        if relative_path in writes:
            knowledge = json.loads(writes[relative_path])
        else:
            path = root / relative_path
            knowledge = read_json(
                path,
                default={"character_id": character_id, "entries": []},
            ) or {}
        entries = knowledge.setdefault("entries", [])
        for item in items:
            entry_id = f"{turn_id}:{len(entries) + 1}"
            entries.append(
                {
                    "entry_id": entry_id,
                    "fact": item.fact,
                    "status": item.status,
                    "source": item.source,
                    "scene_number": scene_number,
                    "acquired_at": utc_now(),
                    "replaces_entry_id": item.replaces_entry_id,
                }
            )
        writes[relative_path] = json_text(knowledge)


def _apply_relationship_events(
    relationships: dict[str, Any],
    turn_id: str,
    scene_number: int | None,
    events: list[Any],
    valid_character_ids: set[str],
) -> None:
    pairs = relationships.setdefault("pairs", {})
    for event in events:
        if event.from_character_id not in valid_character_ids or event.to_character_id not in valid_character_ids:
            raise HTTPException(status_code=422, detail="Relationship references unknown character")
        pair_id = "__".join(sorted((event.from_character_id, event.to_character_id)))
        pair = pairs.setdefault(pair_id, {"directions": {}, "history": []})
        direction_id = f"{event.from_character_id}->{event.to_character_id}"
        direction = pair.setdefault("directions", {}).setdefault(direction_id, {"metrics": {}})
        metrics = direction.setdefault("metrics", {})
        old_value = int(metrics.get(event.metric, 0))
        new_value = max(0, min(100, old_value + event.delta))
        actual_delta = new_value - old_value
        metrics[event.metric] = new_value
        pair.setdefault("history", []).append(
            {
                "turn_id": turn_id,
                "scene_number": scene_number,
                "direction": direction_id,
                "metric": event.metric,
                "before": old_value,
                "after": new_value,
                "delta": actual_delta,
                "reason": event.reason,
            }
        )


def _normalize_plot_lines(plot: dict[str, Any]) -> dict[str, Any]:
    lines = plot.get("lines")
    if isinstance(lines, dict):
        return lines
    result: dict[str, Any] = {}
    if isinstance(lines, list):
        for item in lines:
            if isinstance(item, dict) and item.get("id"):
                result[str(item["id"])] = item
    plot["lines"] = result
    return result


def commit_turn(session_id: str, turn_id: str, request: CommitTurnRequest) -> TurnReceipt:
    root = require_session(session_id)
    turn_id = safe_id(turn_id, "turn_id")
    with session_lock(root):
        recover_transactions(root)
        receipt_path = root / "transactions" / "receipts" / f"{turn_id}.json"
        existing_receipt = read_json(receipt_path, default=None)
        if isinstance(existing_receipt, dict):
            return TurnReceipt(**existing_receipt)

        directory = root / "transactions" / "pending" / turn_id
        metadata = read_json(directory / "metadata.json", default=None)
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=404, detail="Prepared turn not found")
        if metadata.get("status") != "open":
            raise HTTPException(status_code=409, detail="Prepared turn is not open")
        mode = TurnMode(metadata["mode"])
        validate_commit_semantics(mode, request)

        session = read_json(root / "session.json", default={}) or {}
        base_version = int(metadata["base_state_version"])
        current_version = int(session.get("state_version", 0))
        if current_version != base_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "state_version_conflict",
                    "expected": base_version,
                    "actual": current_version,
                },
            )

        warnings: list[str] = []
        writes: dict[str, str] = {}
        changed: set[str] = set()
        next_turn_number = int(session.get("turn_number", 0)) + (1 if mode == TurnMode.PLAY else 0)
        scene_number = next_turn_number if mode == TurnMode.PLAY else None

        current = read_json(root / "state" / "current.json", default={}) or {}
        current = deep_merge(current, request.current_patch)
        _advance_datetime(current, request.time_advance_minutes, warnings)
        if mode == TurnMode.PLAY:
            current["last_scene_end"] = request.scene_summary
            current["last_turn_id"] = turn_id
        writes["state/current.json"] = json_text(current)
        changed.add("state/current.json")

        index_path = root / "state" / "characters" / "index.json"
        index = read_json(index_path, default={"characters": {}}) or {"characters": {}}
        valid_ids = _character_ids(index)

        for new_character in request.new_characters:
            character_id = safe_id(new_character.character_id, "character_id")
            if character_id in valid_ids:
                raise HTTPException(status_code=409, detail=f"Character already exists: {character_id}")
            card = dict(new_character.card)
            card.setdefault("id", character_id)
            if not card.get("name"):
                raise HTTPException(status_code=422, detail=f"New character {character_id} requires name")
            index.setdefault("characters", {})[character_id] = {
                "id": character_id,
                "name": card["name"],
                "aliases": card.get("aliases", []),
                "tags": card.get("tags", []),
            }
            writes[f"state/characters/{character_id}.json"] = json_text(card)
            writes[f"state/knowledge/{character_id}.json"] = json_text(
                {
                    "character_id": character_id,
                    "entries": new_character.starting_knowledge,
                }
            )
            changed.update(
                {
                    f"state/characters/{character_id}.json",
                    f"state/knowledge/{character_id}.json",
                }
            )
            valid_ids.add(character_id)

        for patch in request.character_patches:
            if patch.character_id not in valid_ids:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown character patch target: {patch.character_id}",
                )
            relative_path = f"state/characters/{patch.character_id}.json"
            if relative_path in writes:
                card = json.loads(writes[relative_path])
            else:
                path = root / relative_path
                card = read_json(path, default={}) or {}
            card = deep_merge(card, patch.changes)
            writes[relative_path] = json_text(card)
            changed.add(relative_path)
        writes["state/characters/index.json"] = json_text(index)
        changed.add("state/characters/index.json")

        _apply_knowledge_events(
            root,
            writes,
            turn_id,
            scene_number,
            request.knowledge_events,
            valid_ids,
        )
        changed.update(path for path in writes if path.startswith("state/knowledge/"))

        relationships = read_json(root / "state" / "relationships.json", default={"pairs": {}}) or {
            "pairs": {}
        }
        _apply_relationship_events(
            relationships,
            turn_id,
            scene_number,
            request.relationship_events,
            valid_ids,
        )
        writes["state/relationships.json"] = json_text(relationships)
        changed.add("state/relationships.json")

        plot = read_json(root / "state" / "plot.json", default={}) or {}
        lines = _normalize_plot_lines(plot)
        for patch in request.plotline_patches:
            lines[patch.plotline_id] = deep_merge(lines.get(patch.plotline_id, {}), patch.changes)
        if request.audit_updates:
            plot["last_audit"] = {
                "turn_id": turn_id,
                "at": utc_now(),
                "updates": request.audit_updates,
            }
        writes["state/plot.json"] = json_text(plot)
        changed.add("state/plot.json")

        if mode == TurnMode.PLAY:
            scene_path = f"scenes/{scene_number:06d}.md"
            writes[scene_path] = request.scene_text.rstrip() + "\n"
            changed.add(scene_path)

            chronology = read_text(root / "state" / "chronology.jsonl", default="")
            chronology_event = {
                **(request.chronology_event or {}),
                "turn_id": turn_id,
                "scene_number": scene_number,
            }
            writes["state/chronology.jsonl"] = jsonl_with_event(
                chronology,
                chronology_event,
                "turn_id",
                turn_id,
            )
            history = read_text(root / "state" / "scene_history.jsonl", default="")
            history_event = {
                "turn_id": turn_id,
                "scene_number": scene_number,
                "summary": request.scene_summary,
                "datetime": current.get("datetime"),
                "location_id": current.get("location_id"),
            }
            writes["state/scene_history.jsonl"] = jsonl_with_event(
                history,
                history_event,
                "turn_id",
                turn_id,
            )
            changed.update({"state/chronology.jsonl", "state/scene_history.jsonl"})

        new_version = current_version + 1
        session["state_version"] = new_version
        session["turn_number"] = next_turn_number
        session["updated_at"] = utc_now()
        writes["session.json"] = json_text(session)
        changed.add("session.json")

        metadata["status"] = "committed"
        metadata["committed_at"] = utc_now()
        writes[f"transactions/pending/{turn_id}/metadata.json"] = json_text(metadata)

        receipt = TurnReceipt(
            status="committed",
            session_id=session_id,
            turn_id=turn_id,
            mode=mode,
            base_state_version=base_version,
            new_state_version=new_version,
            turn_number=next_turn_number,
            scene_number=scene_number,
            changed_files=sorted(changed),
            warnings=warnings,
            committed_at=metadata["committed_at"],
        )
        execute_transaction(root, turn_id, writes, receipt.model_dump(mode="json"))
        return receipt


def abort_turn(session_id: str, turn_id: str, reason: str) -> AbortTurnResponse:
    root = require_session(session_id)
    turn_id = safe_id(turn_id, "turn_id")
    with session_lock(root):
        recover_transactions(root)
        receipt = read_json(
            root / "transactions" / "receipts" / f"{turn_id}.json",
            default=None,
        )
        if isinstance(receipt, dict):
            return AbortTurnResponse(status="already_committed", turn_id=turn_id)
        path = root / "transactions" / "pending" / turn_id / "metadata.json"
        metadata = read_json(path, default=None)
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=404, detail="Prepared turn not found")
        if metadata.get("status") == "aborted":
            return AbortTurnResponse(status="already_aborted", turn_id=turn_id)
        metadata["status"] = "aborted"
        metadata["aborted_at"] = utc_now()
        metadata["abort_reason"] = reason
        atomic_write_json(path, metadata)
        return AbortTurnResponse(status="aborted", turn_id=turn_id)
