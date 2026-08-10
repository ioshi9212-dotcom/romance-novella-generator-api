import json
import re
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from app.config import Settings
from app.models import (
    CommitAuditRequest,
    CommitTurnRequest,
    CreateSessionRequest,
    RuntimeStateUpdates,
    TurnPacketRequest,
)
from app.runtime_documents import read_runtime_rules, read_scene_builder
from app.storage import JsonStorage

BASE_STATE_PATHS = {
    "novel": "state/novel.json",
    "hidden_lore": "state/hidden_lore.json",
    "plot_state": "state/plot_state.json",
    "director_plan": "state/director_plan.json",
    "world_state": "state/world_state.json",
    "scene_state": "state/scene_state.json",
}

FOOTER_PATTERN = re.compile(
    r"Ход\s+(?P<turn>\d+)\s*·\s*цикл\s+(?P<cycle>\d+)\s*/\s*15",
    flags=re.IGNORECASE,
)


class ServiceError(Exception):
    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str, bytes_count: int = 12) -> str:
    return f"{prefix}_{secrets.token_urlsafe(bytes_count)}"


def _stamp_document(
    document: Any,
    *,
    session_id: str,
    state_revision: int,
    updated_turn: int,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = document.model_dump(mode="json") if hasattr(document, "model_dump") else document
    result = deepcopy(payload)
    if identity:
        result.update(identity)
    result["session_id"] = session_id
    result["_meta"] = {
        "state_revision": state_revision,
        "last_updated_turn": updated_turn,
        "updated_at": now_iso(),
    }
    return result


CARD_LEVEL_ORDER = {
    "noticeable": 1,
    "recurring": 2,
    "important": 3,
    "player_defined": 4,
}


def _stable_card_payload(card: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in card.items()
        if key
        not in {
            "session_id",
            "_meta",
            "card_level",
            "card_hint",
            "record_status",
            "story_status",
            "player_visibility",
        }
    }


def _facts_preserved(previous: Any, updated: Any) -> bool:
    """Return true when every established value still exists unchanged in the new card."""
    if isinstance(previous, dict):
        return isinstance(updated, dict) and all(
            key in updated and _facts_preserved(value, updated[key])
            for key, value in previous.items()
        )
    if isinstance(previous, list):
        return isinstance(updated, list) and all(item in updated for item in previous)
    if previous in (None, "", "unknown"):
        return True
    return previous == updated


def _split_text(text: str, chunk_size: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    return [
        text[index : index + chunk_size] for index in range(0, len(text), chunk_size)
    ]


def _is_positive_confirmation(value: str) -> bool:
    normalized = " ".join(value.lower().replace("ё", "е").split())
    if "не подтверждаю" in normalized:
        return False
    return re.search(r"(?:^|\W)подтверждаю(?:$|\W)", normalized) is not None


class NovellaService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = JsonStorage(settings.data_dir)

    def _require_session(self, session_id: str) -> dict[str, Any]:
        try:
            if not self.storage.session_exists(session_id):
                raise ServiceError(404, "SESSION_NOT_FOUND", "Session does not exist")
            session = self.storage.read_json(session_id, "session.json")
        except ValueError as exc:
            raise ServiceError(400, "INVALID_SESSION_ID", str(exc)) from exc
        if not isinstance(session, dict):
            raise ServiceError(
                500, "SESSION_CORRUPT", "session.json is missing or invalid"
            )
        if session.get("session_id") != session_id:
            raise ServiceError(
                409,
                "SESSION_MISMATCH",
                "Stored session_id does not match the requested session",
            )
        return session

    def create_session(self, request: CreateSessionRequest) -> dict[str, Any]:
        if not _is_positive_confirmation(request.player_confirmation):
            raise ServiceError(
                409,
                "PLAYER_CONFIRMATION_REQUIRED",
                "createSession is forbidden until the player positively writes «подтверждаю»",
            )
        character_ids = [item.character_id for item in request.characters]
        location_ids = [item.location_id for item in request.locations]
        object_ids = [item.object_id for item in request.objects]
        for label, values in (
            ("character_id", character_ids),
            ("location_id", location_ids),
            ("object_id", object_ids),
        ):
            if len(values) != len(set(values)):
                raise ServiceError(
                    422, "DUPLICATE_ID", f"Duplicate {label} in createSession payload"
                )

        for character in request.characters:
            if character.card.character_id != character.character_id:
                raise ServiceError(
                    422,
                    "CHARACTER_ID_MISMATCH",
                    f"Card ID does not match bundle ID for {character.character_id}",
                )

        for _ in range(10):
            session_id = _new_id("sess", 32)
            try:
                self.storage.create_session_dir(session_id)
                break
            except FileExistsError:  # pragma: no cover - cryptographically improbable.
                continue
        else:  # pragma: no cover
            raise ServiceError(
                500, "SESSION_ID_FAILURE", "Could not allocate a unique session_id"
            )

        created_at = now_iso()
        session = {
            "session_id": session_id,
            "status": "active",
            "created_at": created_at,
            "updated_at": created_at,
            "state_revision": 1,
            "last_completed_turn": 0,
            "last_audited_turn": 0,
            "turns_since_audit": 0,
            "next_turn_number": 1,
            "audit_required": False,
        }
        manifest = {
            "session_id": session_id,
            "schema_version": 1,
            "state_revision": 1,
            "character_ids": character_ids,
            "location_ids": location_ids,
            "object_ids": object_ids,
            "audit_ids": [],
            "updated_at": created_at,
        }
        chronology_manifest = {
            "session_id": session_id,
            "revision": 1,
            "active_part": "chronology_0001",
            "next_event_number": 1,
            "parts": [
                {
                    "part_id": "chronology_0001",
                    "turn_from": None,
                    "turn_to": None,
                    "date_from": None,
                    "date_to": None,
                    "sealed": False,
                }
            ],
        }
        writes: dict[str, Any] = {
            "session.json": session,
            "manifest.json": manifest,
            "chronology/manifest.json": chronology_manifest,
            "chronology/chronology_0001.json": {
                "session_id": session_id,
                "part_id": "chronology_0001",
                "events": [],
            },
        }
        for key, path in BASE_STATE_PATHS.items():
            writes[path] = _stamp_document(
                getattr(request, key),
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
            )
        for character in request.characters:
            prefix = f"characters/{character.character_id}"
            writes[f"{prefix}/card.json"] = _stamp_document(
                character.card.model_dump(mode="json"),
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"character_id": character.character_id},
            )
            writes[f"{prefix}/current_state.json"] = _stamp_document(
                character.current_state,
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"character_id": character.character_id},
            )
            writes[f"{prefix}/relationships.json"] = _stamp_document(
                character.relationships,
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"owner_character_id": character.character_id},
            )
            writes[f"{prefix}/knowledge.json"] = _stamp_document(
                character.knowledge,
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"character_id": character.character_id},
            )
        for location in request.locations:
            writes[f"locations/{location.location_id}.json"] = _stamp_document(
                location.state,
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"location_id": location.location_id},
            )
        for item in request.objects:
            writes[f"objects/{item.object_id}.json"] = _stamp_document(
                item.state,
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"object_id": item.object_id},
            )

        self.storage.write_json_batch(session_id, writes)
        return {
            "session_id": session_id,
            "status": "active",
            "state_revision": 1,
            "next_turn_number": 1,
            "cycle_position": 1,
            "next_required_action": "Keep this exact session_id. On gameplay input call getTurnPacket.",
        }

    def _read_state_bundle_locked(self, session_id: str) -> dict[str, Any]:
        manifest = self.storage.read_json(session_id, "manifest.json")
        if not isinstance(manifest, dict):
            raise ServiceError(
                500, "MANIFEST_CORRUPT", "manifest.json is missing or invalid"
            )
        bundle: dict[str, Any] = {"manifest": manifest}
        for key, path in BASE_STATE_PATHS.items():
            bundle[key] = self.storage.read_json(session_id, path, default={})

        characters: list[dict[str, Any]] = []
        for character_id in manifest.get("character_ids", []):
            prefix = f"characters/{character_id}"
            characters.append(
                {
                    "character_id": character_id,
                    "card": self.storage.read_json(
                        session_id, f"{prefix}/card.json", default={}
                    ),
                    "current_state": self.storage.read_json(
                        session_id, f"{prefix}/current_state.json", default={}
                    ),
                    "relationships": self.storage.read_json(
                        session_id, f"{prefix}/relationships.json", default={}
                    ),
                    "knowledge": self.storage.read_json(
                        session_id, f"{prefix}/knowledge.json", default={}
                    ),
                }
            )
        bundle["characters"] = characters
        bundle["locations"] = [
            {
                "location_id": location_id,
                "state": self.storage.read_json(
                    session_id, f"locations/{location_id}.json", default={}
                ),
            }
            for location_id in manifest.get("location_ids", [])
        ]
        bundle["objects"] = [
            {
                "object_id": object_id,
                "state": self.storage.read_json(
                    session_id, f"objects/{object_id}.json", default={}
                ),
            }
            for object_id in manifest.get("object_ids", [])
        ]
        return bundle

    def _state_bundle_writes(self, bundle: dict[str, Any]) -> dict[str, Any]:
        writes: dict[str, Any] = {"manifest.json": bundle["manifest"]}
        for key, path in BASE_STATE_PATHS.items():
            writes[path] = bundle[key]
        for character in bundle.get("characters", []):
            character_id = character["character_id"]
            prefix = f"characters/{character_id}"
            writes[f"{prefix}/card.json"] = character["card"]
            writes[f"{prefix}/current_state.json"] = character["current_state"]
            writes[f"{prefix}/relationships.json"] = character["relationships"]
            writes[f"{prefix}/knowledge.json"] = character["knowledge"]
        for location in bundle.get("locations", []):
            writes[f"locations/{location['location_id']}.json"] = location["state"]
        for item in bundle.get("objects", []):
            writes[f"objects/{item['object_id']}.json"] = item["state"]
        return writes

    def _apply_state_updates(
        self,
        base: dict[str, Any],
        updates: RuntimeStateUpdates,
        *,
        session_id: str,
        state_revision: int,
        updated_turn: int,
    ) -> dict[str, Any]:
        result = deepcopy(base)
        for key in BASE_STATE_PATHS:
            value = getattr(updates, key)
            if value is not None:
                result[key] = _stamp_document(
                    value,
                    session_id=session_id,
                    state_revision=state_revision,
                    updated_turn=updated_turn,
                )

        characters = {
            item["character_id"]: item for item in result.get("characters", [])
        }
        for update in updates.characters:
            existing = characters.get(update.character_id)
            if existing is None:
                if update.card is None:
                    raise ServiceError(
                        422,
                        "NEW_CHARACTER_NEEDS_CARD",
                        f"New character {update.character_id} requires a complete card",
                    )
                existing = {
                    "character_id": update.character_id,
                    "card": {},
                    "current_state": {},
                    "relationships": {},
                    "knowledge": {},
                }
                characters[update.character_id] = existing
                result["manifest"].setdefault("character_ids", []).append(
                    update.character_id
                )
            if update.card is not None:
                if update.card.character_id != update.character_id:
                    raise ServiceError(
                        422,
                        "CHARACTER_ID_MISMATCH",
                        f"Card ID does not match update ID for {update.character_id}",
                    )
                updated_card = update.card.model_dump(mode="json")
                previous_card = existing.get("card", {})
                previous_level = previous_card.get("card_level")
                updated_level = updated_card.get("card_level")
                if (
                    previous_level in CARD_LEVEL_ORDER
                    and updated_level in CARD_LEVEL_ORDER
                    and CARD_LEVEL_ORDER[updated_level] < CARD_LEVEL_ORDER[previous_level]
                ):
                    raise ServiceError(
                        409,
                        "CHARACTER_CARD_DOWNGRADE",
                        f"Character {update.character_id} cannot be downgraded from "
                        f"{previous_level} to {updated_level}",
                    )
                if (
                    previous_card
                    and not update.card_change_reason
                    and not _facts_preserved(
                        _stable_card_payload(previous_card),
                        _stable_card_payload(updated_card),
                    )
                ):
                    raise ServiceError(
                        409,
                        "CHARACTER_CARD_FACT_LOSS",
                        f"Updated card for {update.character_id} removes or changes established "
                        "facts; preserve them or provide card_change_reason for a canonical correction",
                    )
                existing["card"] = _stamp_document(
                    updated_card,
                    session_id=session_id,
                    state_revision=state_revision,
                    updated_turn=updated_turn,
                    identity={"character_id": update.character_id},
                )
            if update.current_state is not None:
                existing["current_state"] = _stamp_document(
                    update.current_state,
                    session_id=session_id,
                    state_revision=state_revision,
                    updated_turn=updated_turn,
                    identity={"character_id": update.character_id},
                )
            if update.relationships is not None:
                existing["relationships"] = _stamp_document(
                    update.relationships,
                    session_id=session_id,
                    state_revision=state_revision,
                    updated_turn=updated_turn,
                    identity={"owner_character_id": update.character_id},
                )
            if update.knowledge is not None:
                existing["knowledge"] = _stamp_document(
                    update.knowledge,
                    session_id=session_id,
                    state_revision=state_revision,
                    updated_turn=updated_turn,
                    identity={"character_id": update.character_id},
                )
        result["characters"] = [
            characters[character_id]
            for character_id in result["manifest"].get("character_ids", [])
            if character_id in characters
        ]

        locations = {item["location_id"]: item for item in result.get("locations", [])}
        for update in updates.locations:
            if update.location_id not in locations:
                result["manifest"].setdefault("location_ids", []).append(
                    update.location_id
                )
            else:
                previous_canon = locations[update.location_id].get("state", {}).get(
                    "canon", {}
                )
                updated_canon = update.state.canon.model_dump(mode="json")
                if (
                    previous_canon
                    and not update.canon_change_reason
                    and not _facts_preserved(previous_canon, updated_canon)
                ):
                    raise ServiceError(
                        409,
                        "LOCATION_CANON_CONFLICT",
                        f"Updated canon for {update.location_id} removes or changes established "
                        "details; preserve them or provide canon_change_reason for a canonical correction",
                    )
            locations[update.location_id] = {
                "location_id": update.location_id,
                "state": _stamp_document(
                    update.state.model_dump(mode="json"),
                    session_id=session_id,
                    state_revision=state_revision,
                    updated_turn=updated_turn,
                    identity={"location_id": update.location_id},
                ),
            }
        result["locations"] = [
            locations[location_id]
            for location_id in result["manifest"].get("location_ids", [])
            if location_id in locations
        ]

        objects = {item["object_id"]: item for item in result.get("objects", [])}
        for update in updates.objects:
            if update.object_id not in objects:
                result["manifest"].setdefault("object_ids", []).append(update.object_id)
            objects[update.object_id] = {
                "object_id": update.object_id,
                "state": _stamp_document(
                    update.state,
                    session_id=session_id,
                    state_revision=state_revision,
                    updated_turn=updated_turn,
                    identity={"object_id": update.object_id},
                ),
            }
        result["objects"] = [
            objects[object_id]
            for object_id in result["manifest"].get("object_ids", [])
            if object_id in objects
        ]
        result["manifest"]["state_revision"] = state_revision
        result["manifest"]["updated_at"] = now_iso()
        return result

    def _read_chronology_locked(
        self, session_id: str
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]]]:
        manifest = self.storage.read_json(session_id, "chronology/manifest.json")
        if not isinstance(manifest, dict):
            raise ServiceError(
                500, "CHRONOLOGY_CORRUPT", "chronology manifest is missing"
            )
        parts: dict[str, dict[str, Any]] = {}
        events: list[dict[str, Any]] = []
        for meta in manifest.get("parts", []):
            part_id = meta["part_id"]
            part = self.storage.read_json(
                session_id,
                f"chronology/{part_id}.json",
                default={"session_id": session_id, "part_id": part_id, "events": []},
            )
            parts[part_id] = part
            events.extend(part.get("events", []))
        return manifest, parts, events

    @staticmethod
    def _effective_chronology(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        active = [
            event for event in events if event.get("status", "active") == "active"
        ]
        compacted_ids = {
            event_id
            for event in active
            for event_id in event.get("compacts_event_ids", [])
        }
        effective = [
            event for event in active if event.get("event_id") not in compacted_ids
        ]
        return sorted(
            effective,
            key=lambda event: (
                int(event.get("turn_number", 0)),
                str(event.get("event_id", "")),
            ),
        )

    @staticmethod
    def _update_part_meta(meta: dict[str, Any], part: dict[str, Any]) -> None:
        events = part.get("events", [])
        if not events:
            meta.update(
                {"turn_from": None, "turn_to": None, "date_from": None, "date_to": None}
            )
            return
        turns = [int(event["turn_number"]) for event in events]
        dates = [str(event.get("story_datetime") or "") for event in events]
        meta.update(
            {
                "turn_from": min(turns),
                "turn_to": max(turns),
                "date_from": min(dates) if dates else None,
                "date_to": max(dates) if dates else None,
            }
        )

    def _append_chronology_locked(
        self,
        session_id: str,
        new_events: list[dict[str, Any]],
        *,
        supersede_ids: list[str] | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        manifest, parts, flat_events = self._read_chronology_locked(session_id)
        by_id = {event.get("event_id"): event for event in flat_events}
        supersede_ids = list(supersede_ids or [])
        explicit_supersedes = [
            event.get("supersedes_event_id")
            for event in new_events
            if event.get("supersedes_event_id")
        ]
        for event_id in [*supersede_ids, *explicit_supersedes]:
            if event_id not in by_id:
                raise ServiceError(
                    409,
                    "UNKNOWN_SUPERSEDED_EVENT",
                    f"Cannot supersede unknown event {event_id}",
                )
            by_id[event_id]["status"] = "superseded"
            by_id[event_id]["superseded_at"] = now_iso()

        for source in new_events:
            for event_id in source.get("compacts_event_ids", []):
                if event_id not in by_id:
                    raise ServiceError(
                        409,
                        "UNKNOWN_COMPACTED_EVENT",
                        f"Cannot compact unknown event {event_id}",
                    )
                if by_id[event_id].get("status", "active") != "active":
                    raise ServiceError(
                        409,
                        "INACTIVE_COMPACTED_EVENT",
                        f"Cannot compact inactive event {event_id}",
                    )

        created_ids: list[str] = []
        for index, source in enumerate(new_events):
            payload = deepcopy(source)
            if not payload.get("supersedes_event_id") and index < len(supersede_ids):
                payload["supersedes_event_id"] = supersede_ids[index]

            active_id = manifest["active_part"]
            active_part = parts[active_id]
            active_events = active_part.setdefault("events", [])
            last_scene = active_events[-1].get("scene_id") if active_events else None
            turn_count = len({event.get("turn_number") for event in active_events})
            size_reached = len(json.dumps(active_part, ensure_ascii=False)) >= 32_000
            if (
                active_events
                and (turn_count >= 30 or size_reached)
                and payload.get("scene_id") != last_scene
            ):
                for meta in manifest["parts"]:
                    if meta["part_id"] == active_id:
                        meta["sealed"] = True
                        self._update_part_meta(meta, active_part)
                        break
                next_number = len(manifest["parts"]) + 1
                active_id = f"chronology_{next_number:04d}"
                manifest["active_part"] = active_id
                manifest["parts"].append(
                    {
                        "part_id": active_id,
                        "turn_from": None,
                        "turn_to": None,
                        "date_from": None,
                        "date_to": None,
                        "sealed": False,
                    }
                )
                parts[active_id] = {
                    "session_id": session_id,
                    "part_id": active_id,
                    "events": [],
                }
                active_part = parts[active_id]

            event_number = int(manifest.get("next_event_number", 1))
            event_id = f"event_{event_number:06d}"
            manifest["next_event_number"] = event_number + 1
            event = {
                **payload,
                "session_id": session_id,
                "event_id": event_id,
                "status": "active",
                "recorded_at": now_iso(),
            }
            active_part.setdefault("events", []).append(event)
            created_ids.append(event_id)
            old_id = event.get("supersedes_event_id")
            if old_id and old_id in by_id:
                by_id[old_id]["superseded_by_event_id"] = event_id
            by_id[event_id] = event

        for meta in manifest.get("parts", []):
            part = parts[meta["part_id"]]
            self._update_part_meta(meta, part)
        manifest["revision"] = int(manifest.get("revision", 0)) + 1
        manifest["updated_at"] = now_iso()
        writes = {"chronology/manifest.json": manifest}
        writes.update(
            {f"chronology/{part_id}.json": part for part_id, part in parts.items()}
        )
        return writes, created_ids

    def _turn_path(self, turn_number: int) -> str:
        return f"turns/turn_{turn_number:06d}.json"

    @staticmethod
    def _public_turn(turn: dict[str, Any]) -> dict[str, Any]:
        return {
            key: deepcopy(value)
            for key, value in turn.items()
            if key not in {"before_state", "revision_history", "commit_response"}
        }

    def _read_turn_range_locked(
        self, session_id: str, turn_from: int, turn_to: int
    ) -> list[dict[str, Any]]:
        turns: list[dict[str, Any]] = []
        for turn_number in range(turn_from, turn_to + 1):
            turn = self.storage.read_json(session_id, self._turn_path(turn_number))
            if not isinstance(turn, dict):
                raise ServiceError(
                    500,
                    "TURN_MISSING",
                    f"Stored turn {turn_number} is missing during packet assembly",
                )
            turns.append(self._public_turn(turn))
        return turns

    def _store_packet_locked(
        self,
        session_id: str,
        *,
        packet_type: str,
        packet_id: str,
        payload: dict[str, Any],
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        chunks = _split_text(text, self.settings.packet_chunk_chars)
        digest = sha256(text.encode("utf-8")).hexdigest()
        pending.update(
            {
                "status": "active",
                "packet_type": packet_type,
                "packet_id": packet_id,
                "chunks": chunks,
                "content_sha256": digest,
                "created_at": now_iso(),
            }
        )
        self.storage._write_json_batch_locked(
            session_id,
            {f"pending_{packet_type}.json": pending},
        )
        return self._packet_chunk_response(session_id, pending, 0)

    @staticmethod
    def _packet_chunk_response(
        session_id: str, pending: dict[str, Any], chunk_index: int
    ) -> dict[str, Any]:
        chunks = pending.get("chunks", [])
        if chunk_index < 0 or chunk_index >= len(chunks):
            raise ServiceError(
                404, "PACKET_CHUNK_NOT_FOUND", "Packet chunk index is out of range"
            )
        has_more = chunk_index + 1 < len(chunks)
        packet_type = pending["packet_type"]
        next_action = (
            f"Call get{packet_type.title()}PacketChunk with chunk_index {chunk_index + 1}."
            if has_more
            else (
                "Generate the scene and call commitTurn before replying to the player."
                if packet_type == "turn"
                else "Complete the audit checklist and call commitAudit before requesting a turn."
            )
        )
        return {
            "session_id": session_id,
            "packet_id": pending["packet_id"],
            "packet_type": packet_type,
            "chunk_index": chunk_index,
            "chunk_count": len(chunks),
            "content": chunks[chunk_index],
            "content_sha256": pending["content_sha256"],
            "has_more": has_more,
            "next_chunk_index": chunk_index + 1 if has_more else None,
            "next_required_action": next_action,
        }

    def get_turn_packet(
        self, session_id: str, request: TurnPacketRequest
    ) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            session = self._require_session(session_id)
            pending = self.storage.read_json(
                session_id, "pending_turn.json", default={}
            )
            if isinstance(pending, dict) and pending.get("status") == "active":
                same_request = (
                    pending.get("player_input") == request.player_input
                    and pending.get("mode") == request.mode
                    and pending.get("client_request_id") == request.client_request_id
                )
                if not same_request:
                    raise ServiceError(
                        409,
                        "TURN_ALREADY_PENDING",
                        "A different turn packet is already pending and must be committed first",
                    )
                return self._packet_chunk_response(session_id, pending, 0)

            if request.mode == "new" and session.get("audit_required"):
                raise ServiceError(
                    409,
                    "AUDIT_REQUIRED",
                    "The next scene is blocked. Call getAuditPacket and commitAudit first.",
                )

            current_state = self._read_state_bundle_locked(session_id)
            chronology_manifest, _parts, chronology = self._read_chronology_locked(
                session_id
            )
            chronology = self._effective_chronology(chronology)
            last_completed = int(session.get("last_completed_turn", 0))
            if request.mode == "revise_last":
                if last_completed < 1:
                    raise ServiceError(
                        409, "NO_TURN_TO_REVISE", "There is no completed turn to revise"
                    )
                existing_turn = self.storage.read_json(
                    session_id, self._turn_path(last_completed), default={}
                )
                before_state = deepcopy(existing_turn.get("before_state"))
                if not isinstance(before_state, dict):
                    raise ServiceError(
                        500,
                        "TURN_SNAPSHOT_MISSING",
                        "The last turn has no pre-turn state",
                    )
                turn_number = last_completed
                cycle_position = int(existing_turn.get("cycle_position", 1))
                turn_revision = int(existing_turn.get("revision", 1)) + 1
                revising_turn = self._public_turn(existing_turn)
            else:
                before_state = current_state
                turn_number = last_completed + 1
                cycle_position = int(session.get("turns_since_audit", 0)) + 1
                turn_revision = 1
                revising_turn = None

            recent_from = max(int(session.get("last_audited_turn", 0)) + 1, 1)
            recent_turns = (
                self._read_turn_range_locked(session_id, recent_from, last_completed)
                if last_completed >= recent_from
                else []
            )
            turn_id = _new_id(f"turn_{turn_number}", 9)
            packet_id = _new_id("turnpacket", 9)
            novel_state = before_state.get("novel", {})
            scene_state = before_state.get("scene_state", {})
            pov_character_id = novel_state.get("pov_character_id")
            present_character_ids = list(
                dict.fromkeys(scene_state.get("present_character_ids", []))
            )
            required_full_character_ids = list(
                dict.fromkeys(
                    [
                        character_id
                        for character_id in [pov_character_id, *present_character_ids]
                        if character_id
                    ]
                )
            )
            packet_state = deepcopy(before_state)
            packet_state["characters"] = [
                character
                for character in before_state.get("characters", [])
                if character.get("character_id") in required_full_character_ids
            ]
            payload = {
                "packet_type": "turn",
                "session_id": session_id,
                "turn_id": turn_id,
                "turn_number": turn_number,
                "turn_revision": turn_revision,
                "cycle_position": cycle_position,
                "cycle_length": 15,
                "expected_state_revision": int(session["state_revision"]),
                "mode": request.mode,
                "player_input": request.player_input,
                "rules": read_runtime_rules(),
                "scene_builder": read_scene_builder(),
                "state": packet_state,
                "scene_focus": {
                    "pov_character_id": pov_character_id,
                    "present_character_ids": present_character_ids,
                    "required_full_character_ids": required_full_character_ids,
                    "instruction": (
                        "Before writing, read each listed character's complete card, "
                        "current_state, knowledge and directional relationships in state.characters. "
                        "Only characters physically present in the current scene are included. "
                        "Keep POV physically and emotionally present without taking major choices away "
                        "from the player."
                    ),
                },
                "chronology_manifest": chronology_manifest,
                "chronology": chronology,
                "turns_since_last_audit": recent_turns,
                "revising_turn": revising_turn,
                "instruction": (
                    "Read every field before writing, with special attention to scene_focus. "
                    "Use only character-specific knowledge. Build the complete scene, then "
                    "commit it before showing it to the player."
                ),
            }
            pending = {
                "turn_id": turn_id,
                "turn_number": turn_number,
                "turn_revision": turn_revision,
                "cycle_position": cycle_position,
                "expected_state_revision": int(session["state_revision"]),
                "mode": request.mode,
                "player_input": request.player_input,
                "client_request_id": request.client_request_id,
                "before_state": before_state,
            }
            return self._store_packet_locked(
                session_id,
                packet_type="turn",
                packet_id=packet_id,
                payload=payload,
                pending=pending,
            )

    def get_turn_packet_chunk(
        self, session_id: str, packet_id: str, chunk_index: int
    ) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_turn.json", default={}
            )
            if (
                pending.get("status") != "active"
                or pending.get("packet_id") != packet_id
            ):
                raise ServiceError(
                    404, "TURN_PACKET_NOT_FOUND", "Active turn packet was not found"
                )
            return self._packet_chunk_response(session_id, pending, chunk_index)

    @staticmethod
    def _validate_footer(
        scene_output: str, turn_number: int, cycle_position: int
    ) -> None:
        matches = list(FOOTER_PATTERN.finditer(scene_output))
        if not matches:
            raise ServiceError(
                422,
                "SCENE_FOOTER_MISSING",
                f"Scene must contain: Ход {turn_number} · цикл {cycle_position}/15",
            )
        match = matches[-1]
        if (
            int(match.group("turn")) != turn_number
            or int(match.group("cycle")) != cycle_position
        ):
            raise ServiceError(
                422,
                "SCENE_COUNTER_MISMATCH",
                f"Expected footer: Ход {turn_number} · цикл {cycle_position}/15",
            )
        reminder = scene_output[match.end() :].lower()
        if "state" not in reminder or "15" not in reminder or "свер" not in reminder:
            raise ServiceError(
                422,
                "SCENE_REMINDER_MISSING",
                "Footer must be followed by the reminder to read state and audit every 15 turns",
            )

    def _invalidate_audits_locked(
        self, session_id: str, manifest: dict[str, Any], revised_turn: int
    ) -> tuple[dict[str, Any], int | None, list[str]]:
        writes: dict[str, Any] = {}
        earliest: int | None = None
        audit_created_event_ids: list[str] = []
        for audit_id in manifest.get("audit_ids", []):
            path = f"audits/{audit_id}.json"
            audit = self.storage.read_json(session_id, path, default={})
            if (
                audit.get("status") == "complete"
                and int(audit.get("turn_to", 0)) >= revised_turn
            ):
                audit["status"] = "invalidated"
                audit["invalidated_by_turn"] = revised_turn
                audit["invalidated_at"] = now_iso()
                writes[path] = audit
                turn_from = int(audit.get("turn_from", revised_turn))
                earliest = turn_from if earliest is None else min(earliest, turn_from)
                audit_created_event_ids.extend(
                    audit.get("created_correction_event_ids", [])
                )
                audit_created_event_ids.extend(
                    audit.get("created_compaction_event_ids", [])
                )
        return writes, earliest, audit_created_event_ids

    @staticmethod
    def _revision_snapshot(turn: dict[str, Any]) -> dict[str, Any]:
        return {
            key: deepcopy(value)
            for key, value in turn.items()
            if key not in {"before_state", "revision_history", "commit_response"}
        }

    def commit_turn(
        self, session_id: str, request: CommitTurnRequest
    ) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            session = self._require_session(session_id)
            pending = self.storage.read_json(
                session_id, "pending_turn.json", default={}
            )
            if (
                pending.get("status") == "committed"
                and pending.get("turn_id") == request.turn_id
            ):
                return pending["commit_response"]
            if (
                pending.get("status") != "active"
                or pending.get("turn_id") != request.turn_id
            ):
                raise ServiceError(
                    409, "TURN_NOT_PENDING", "The supplied turn_id is not pending"
                )
            if int(session["state_revision"]) != request.expected_state_revision:
                raise ServiceError(
                    409,
                    "STATE_REVISION_CONFLICT",
                    "State changed after the packet was created; request a fresh packet",
                )
            if (
                int(pending["expected_state_revision"])
                != request.expected_state_revision
            ):
                raise ServiceError(
                    409, "PACKET_REVISION_CONFLICT", "Packet revision is stale"
                )

            turn_number = int(pending["turn_number"])
            cycle_position = int(pending["cycle_position"])
            self._validate_footer(request.scene_output, turn_number, cycle_position)
            new_state_revision = int(session["state_revision"]) + 1
            before_state = pending["before_state"]
            after_state = self._apply_state_updates(
                before_state,
                request.state_updates,
                session_id=session_id,
                state_revision=new_state_revision,
                updated_turn=turn_number,
            )

            mode = pending["mode"]
            existing_turn: dict[str, Any] | None = None
            old_event_ids: list[str] = []
            audit_writes: dict[str, Any] = {}
            invalidated_audit_event_ids: list[str] = []
            last_audited = int(session.get("last_audited_turn", 0))
            revision_history: list[dict[str, Any]] = []
            if mode == "revise_last":
                existing_turn = self.storage.read_json(
                    session_id, self._turn_path(turn_number), default={}
                )
                if not existing_turn:
                    raise ServiceError(
                        409, "TURN_TO_REVISE_MISSING", "Last turn file is missing"
                    )
                old_event_ids = list(existing_turn.get("created_event_ids", []))
                revision_history = list(existing_turn.get("revision_history", []))
                revision_history.append(self._revision_snapshot(existing_turn))
                current_manifest = self.storage.read_json(
                    session_id, "manifest.json", default={}
                )
                after_state["manifest"]["audit_ids"] = list(
                    current_manifest.get("audit_ids", [])
                )
                audit_writes, invalid_from, invalidated_audit_event_ids = (
                    self._invalidate_audits_locked(
                        session_id, current_manifest, turn_number
                    )
                )
                if invalid_from is not None:
                    last_audited = min(last_audited, invalid_from - 1)
            else:
                if turn_number != int(session.get("last_completed_turn", 0)) + 1:
                    raise ServiceError(
                        409,
                        "TURN_SEQUENCE_CONFLICT",
                        "Turn number is not the next turn",
                    )

            event_payloads = []
            for event in request.events:
                payload = event.model_dump(mode="json")
                payload.update(
                    {
                        "turn_number": turn_number,
                        "turn_id": request.turn_id,
                    }
                )
                event_payloads.append(payload)
            chronology_writes, created_event_ids = self._append_chronology_locked(
                session_id,
                event_payloads,
                supersede_ids=(
                    [*old_event_ids, *invalidated_audit_event_ids]
                    if mode == "revise_last"
                    else None
                ),
            )

            turn_revision = int(pending["turn_revision"])
            turn = {
                "session_id": session_id,
                "turn_id": request.turn_id,
                "turn_number": turn_number,
                "revision": turn_revision,
                "status": "current",
                "mode": mode,
                "cycle_position": cycle_position,
                "player_input": pending["player_input"],
                "scene_output": request.scene_output,
                "summary": request.summary,
                "scene_id": request.scene_id,
                "story_datetime": request.story_datetime,
                "created_event_ids": created_event_ids,
                "displayed_state_changes": request.displayed_state_changes,
                "before_state": before_state,
                "revision_history": revision_history,
                "created_at": existing_turn.get("created_at")
                if existing_turn
                else now_iso(),
                "updated_at": now_iso(),
            }

            last_completed = max(
                int(session.get("last_completed_turn", 0)), turn_number
            )
            turns_since_audit = last_completed - last_audited
            audit_required = turns_since_audit >= 15
            session.update(
                {
                    "updated_at": now_iso(),
                    "state_revision": new_state_revision,
                    "last_completed_turn": last_completed,
                    "last_audited_turn": last_audited,
                    "turns_since_audit": turns_since_audit,
                    "next_turn_number": last_completed + 1,
                    "audit_required": audit_required,
                }
            )
            after_state["manifest"]["state_revision"] = new_state_revision
            next_cycle = None if audit_required else turns_since_audit + 1
            response = {
                "session_id": session_id,
                "turn_id": request.turn_id,
                "turn_number": turn_number,
                "turn_revision": turn_revision,
                "state_revision": new_state_revision,
                "last_completed_turn": last_completed,
                "last_audited_turn": last_audited,
                "next_turn_number": last_completed + 1,
                "next_cycle_position": next_cycle,
                "audit_required": audit_required,
                "next_required_action": (
                    "Before another scene call getAuditPacket and complete the audit."
                    if audit_required
                    else "Reply with only the committed scene. On the next player input call getTurnPacket."
                ),
            }
            pending_committed = {
                "status": "committed",
                "packet_type": "turn",
                "turn_id": request.turn_id,
                "committed_at": now_iso(),
                "commit_response": response,
            }
            writes = self._state_bundle_writes(after_state)
            writes.update(chronology_writes)
            writes.update(audit_writes)
            writes.update(
                {
                    "session.json": session,
                    self._turn_path(turn_number): turn,
                    "pending_turn.json": pending_committed,
                }
            )
            pending_audit = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )
            if mode == "revise_last" and pending_audit.get("status") == "active":
                pending_audit.update(
                    {
                        "status": "invalidated",
                        "invalidated_by_turn": turn_number,
                        "invalidated_at": now_iso(),
                    }
                )
                writes["pending_audit.json"] = pending_audit
            self.storage._write_json_batch_locked(session_id, writes)
            return response

    def get_audit_packet(self, session_id: str) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            session = self._require_session(session_id)
            pending = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )
            if pending.get("status") == "active":
                return self._packet_chunk_response(session_id, pending, 0)
            if not session.get("audit_required"):
                raise ServiceError(
                    409, "AUDIT_NOT_REQUIRED", "There is no required 15-turn audit"
                )

            turn_from = int(session.get("last_audited_turn", 0)) + 1
            turn_to = min(turn_from + 14, int(session.get("last_completed_turn", 0)))
            if turn_to - turn_from + 1 < 15:
                raise ServiceError(
                    409, "AUDIT_RANGE_INCOMPLETE", "Fewer than 15 unaudited turns exist"
                )
            turns = self._read_turn_range_locked(session_id, turn_from, turn_to)
            state = self._read_state_bundle_locked(session_id)
            chronology_manifest, _parts, chronology = self._read_chronology_locked(
                session_id
            )
            chronology = self._effective_chronology(chronology)
            audit_id = _new_id(f"audit_{turn_from}_{turn_to}", 9)
            packet_id = _new_id("auditpacket", 9)
            payload = {
                "packet_type": "audit",
                "session_id": session_id,
                "audit_id": audit_id,
                "turn_from": turn_from,
                "turn_to": turn_to,
                "expected_state_revision": int(session["state_revision"]),
                "rules": read_runtime_rules(),
                "state": state,
                "chronology_manifest": chronology_manifest,
                "chronology": chronology,
                "full_turns_current_revisions": turns,
                "required_checklist": [
                    "events_and_consequences",
                    "time_and_movement",
                    "scene_and_physical_state",
                    "character_current_states",
                    "character_continuity",
                    "minor_npc_lifecycle",
                    "knowledge_sources",
                    "knowledge_boundaries",
                    "directional_relationships",
                    "plot_threads",
                    "hidden_lore_and_reveal_timing",
                    "compaction_and_duplicates",
                ],
                "instruction": (
                    "Read all 15 full turns, the full compact chronology and all current state. "
                    "Repair omissions, remove obsolete temporary state, compact duplicates, and "
                    "preserve facts, knowledge sources, relationship causes, player characters and hidden lore."
                ),
            }
            pending = {
                "audit_id": audit_id,
                "turn_from": turn_from,
                "turn_to": turn_to,
                "expected_state_revision": int(session["state_revision"]),
            }
            return self._store_packet_locked(
                session_id,
                packet_type="audit",
                packet_id=packet_id,
                payload=payload,
                pending=pending,
            )

    def get_audit_packet_chunk(
        self, session_id: str, packet_id: str, chunk_index: int
    ) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )
            if (
                pending.get("status") != "active"
                or pending.get("packet_id") != packet_id
            ):
                raise ServiceError(
                    404, "AUDIT_PACKET_NOT_FOUND", "Active audit packet was not found"
                )
            return self._packet_chunk_response(session_id, pending, chunk_index)

    def commit_audit(
        self, session_id: str, request: CommitAuditRequest
    ) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            session = self._require_session(session_id)
            pending = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )
            if (
                pending.get("status") == "committed"
                and pending.get("audit_id") == request.audit_id
            ):
                return pending["commit_response"]
            if (
                pending.get("status") != "active"
                or pending.get("audit_id") != request.audit_id
            ):
                raise ServiceError(
                    409, "AUDIT_NOT_PENDING", "The supplied audit_id is not pending"
                )
            if int(session["state_revision"]) != request.expected_state_revision:
                raise ServiceError(
                    409,
                    "STATE_REVISION_CONFLICT",
                    "State changed after the audit packet was created; request a fresh audit packet",
                )
            checklist = request.checklist.model_dump()
            incomplete = [
                name for name, checked in checklist.items() if checked is not True
            ]
            if incomplete:
                raise ServiceError(
                    422,
                    "AUDIT_CHECKLIST_INCOMPLETE",
                    "Every audit category must be checked: " + ", ".join(incomplete),
                )

            turn_from = int(pending["turn_from"])
            turn_to = int(pending["turn_to"])
            if turn_from != int(session.get("last_audited_turn", 0)) + 1:
                raise ServiceError(
                    409,
                    "AUDIT_RANGE_STALE",
                    "Audit range no longer starts at the expected turn",
                )
            new_state_revision = int(session["state_revision"]) + 1
            current_state = self._read_state_bundle_locked(session_id)
            after_state = self._apply_state_updates(
                current_state,
                request.state_updates,
                session_id=session_id,
                state_revision=new_state_revision,
                updated_turn=turn_to,
            )

            correction_payloads = []
            for correction in request.chronology_corrections:
                payload = correction.model_dump(mode="json")
                payload["turn_id"] = f"audit_correction_{request.audit_id}"
                correction_payloads.append(payload)
            compaction_payloads = []
            for compaction in request.chronology_compactions:
                payload = compaction.model_dump(mode="json")
                payload["turn_id"] = f"audit_compaction_{request.audit_id}"
                compaction_payloads.append(payload)
            chronology_writes, created_audit_event_ids = self._append_chronology_locked(
                session_id,
                [*correction_payloads, *compaction_payloads],
            )
            correction_ids = created_audit_event_ids[: len(correction_payloads)]
            compaction_ids = created_audit_event_ids[len(correction_payloads) :]

            audit = {
                "session_id": session_id,
                "audit_id": request.audit_id,
                "status": "complete",
                "turn_from": turn_from,
                "turn_to": turn_to,
                "checklist": checklist,
                "findings": request.findings,
                "created_correction_event_ids": correction_ids,
                "created_compaction_event_ids": compaction_ids,
                "state_revision_before": request.expected_state_revision,
                "state_revision_after": new_state_revision,
                "completed_at": now_iso(),
            }
            if request.audit_id not in after_state["manifest"].setdefault(
                "audit_ids", []
            ):
                after_state["manifest"]["audit_ids"].append(request.audit_id)
            after_state["manifest"]["state_revision"] = new_state_revision
            after_state["manifest"]["updated_at"] = now_iso()

            last_completed = int(session.get("last_completed_turn", 0))
            last_audited = turn_to
            turns_since_audit = last_completed - last_audited
            audit_required = turns_since_audit >= 15
            session.update(
                {
                    "updated_at": now_iso(),
                    "state_revision": new_state_revision,
                    "last_audited_turn": last_audited,
                    "turns_since_audit": turns_since_audit,
                    "audit_required": audit_required,
                    "next_turn_number": last_completed + 1,
                }
            )
            next_cycle = None if audit_required else turns_since_audit + 1
            response = {
                "session_id": session_id,
                "audit_id": request.audit_id,
                "audit_complete": True,
                "audited_turn_from": turn_from,
                "audited_turn_to": turn_to,
                "state_revision": new_state_revision,
                "last_audited_turn": last_audited,
                "audit_required": audit_required,
                "next_turn_number": last_completed + 1,
                "next_cycle_position": next_cycle,
                "next_required_action": (
                    "Another 15-turn audit is required before a scene. Call getAuditPacket again."
                    if audit_required
                    else "Audit gate is clear. Call getTurnPacket and only then write the next scene."
                ),
            }
            pending_committed = {
                "status": "committed",
                "packet_type": "audit",
                "audit_id": request.audit_id,
                "committed_at": now_iso(),
                "commit_response": response,
            }
            writes = self._state_bundle_writes(after_state)
            writes.update(chronology_writes)
            writes.update(
                {
                    "session.json": session,
                    f"audits/{request.audit_id}.json": audit,
                    "pending_audit.json": pending_committed,
                }
            )
            self.storage._write_json_batch_locked(session_id, writes)
            return response

    def get_chronology_page(
        self,
        session_id: str,
        cursor: int = 0,
        limit: int = 100,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        self._require_session(session_id)
        if cursor < 0:
            raise ServiceError(422, "INVALID_CURSOR", "cursor must be zero or greater")
        if limit < 1 or limit > 200:
            raise ServiceError(422, "INVALID_LIMIT", "limit must be between 1 and 200")
        with self.storage.session_transaction(session_id):
            _manifest, _parts, events = self._read_chronology_locked(session_id)
            if not include_inactive:
                events = self._effective_chronology(events)
            page = events[cursor : cursor + limit]
            next_cursor = cursor + len(page)
            has_more = next_cursor < len(events)
            return {
                "session_id": session_id,
                "cursor": cursor,
                "events": page,
                "include_inactive": include_inactive,
                "has_more": has_more,
                "next_cursor": next_cursor if has_more else None,
            }
