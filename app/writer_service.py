from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.runtime_documents import read_runtime_rules, read_scene_builder
from app.service import FOOTER_PATTERN, NovellaService, ServiceError, _new_id


class WriterFirstNovellaService(NovellaService):
    """Turn-packet variant that keeps Railway authoritative but gives GPT a writer-sized context.

    The complete state remains in pending_turn.before_state and is still used by commitTurn,
    revisions and audits. Only the packet shown to the scene writer is reduced.
    """

    RECENT_FULL_SCENES = 2
    RECENT_GLOBAL_EVENTS = 12
    CHARACTER_MEMORY_EVENTS = 4
    LOCATION_MEMORY_EVENTS = 4

    @staticmethod
    def _clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: WriterFirstNovellaService._clean(item)
                for key, item in value.items()
                if key not in {"session_id", "_meta", "recorded_at", "updated_at"}
            }
        if isinstance(value, list):
            return [WriterFirstNovellaService._clean(item) for item in value]
        return deepcopy(value)

    @staticmethod
    def _turn_number(value: dict[str, Any]) -> int:
        try:
            return int(value.get("turn_number", 0))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _compact_turn(cls, turn: dict[str, Any]) -> dict[str, Any]:
        keep = (
            "turn_number",
            "revision",
            "cycle_position",
            "player_input",
            "scene_output",
            "summary",
            "scene_id",
            "story_datetime",
        )
        return cls._clean({key: turn.get(key) for key in keep if key in turn})

    @classmethod
    def _active_story_direction(cls, director_plan: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        terminal = {"resolved", "closed", "expired", "cancelled", "canceled", "done"}
        for key, value in director_plan.items():
            if key in {"session_id", "_meta"}:
                continue
            if isinstance(value, list):
                result[key] = [
                    cls._clean(item)
                    for item in value
                    if not (
                        isinstance(item, dict)
                        and str(item.get("status", "")).strip().lower() in terminal
                    )
                ]
            else:
                result[key] = cls._clean(value)
        return result

    @classmethod
    def _select_story_memory(
        cls,
        chronology: list[dict[str, Any]],
        *,
        last_completed: int,
        participant_ids: list[str],
        location_id: str | None,
        exclude_turn: int | None = None,
    ) -> list[dict[str, Any]]:
        usable = [
            event
            for event in chronology
            if exclude_turn is None or cls._turn_number(event) != exclude_turn
        ]
        recent = [
            event
            for event in usable
            if cls._turn_number(event) >= max(last_completed - 5, 1)
        ][-cls.RECENT_GLOBAL_EVENTS :]

        selected: dict[str, dict[str, Any]] = {}

        def remember(event: dict[str, Any]) -> None:
            key = str(event.get("event_id") or f"turn:{cls._turn_number(event)}:{id(event)}")
            selected[key] = event

        for event in recent:
            remember(event)

        for character_id in participant_ids:
            matches = [
                event
                for event in usable
                if character_id in event.get("participants_present", [])
            ][-cls.CHARACTER_MEMORY_EVENTS :]
            for event in matches:
                remember(event)

        if location_id:
            matches = [
                event for event in usable if event.get("location_id") == location_id
            ][-cls.LOCATION_MEMORY_EVENTS :]
            for event in matches:
                remember(event)

        return [
            cls._clean(event)
            for event in sorted(
                selected.values(),
                key=lambda item: (cls._turn_number(item), str(item.get("event_id", ""))),
            )
        ]

    @staticmethod
    def _contains_known_id(value: Any, known_ids: set[str]) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for item in value.values():
                found.update(WriterFirstNovellaService._contains_known_id(item, known_ids))
        elif isinstance(value, list):
            for item in value:
                found.update(WriterFirstNovellaService._contains_known_id(item, known_ids))
        elif isinstance(value, str) and value in known_ids:
            found.add(value)
        return found

    @classmethod
    def _current_world_slice(cls, world_state: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "story_datetime",
            "season",
            "weather",
            "current_weather",
            "time_of_day",
            "day_of_week",
            "public_conditions",
            "current_conditions",
        }
        return cls._clean(
            {key: value for key, value in world_state.items() if key in allowed}
        )

    @classmethod
    def _location_name(cls, location: dict[str, Any]) -> str:
        return str(location.get("state", {}).get("canon", {}).get("name", "")).strip()

    @classmethod
    def _object_name(cls, item: dict[str, Any]) -> str:
        state = item.get("state", {})
        for path in (
            state.get("name"),
            state.get("display_name"),
            state.get("canon", {}).get("name") if isinstance(state.get("canon"), dict) else None,
        ):
            if path:
                return str(path).strip()
        return ""

    @classmethod
    def _writer_state(
        cls,
        before_state: dict[str, Any],
        *,
        required_character_ids: list[str],
        pov_character_id: str | None,
        player_input: str,
    ) -> tuple[dict[str, Any], str | None]:
        scene_state = before_state.get("scene_state", {})
        selected_characters = [
            character
            for character in before_state.get("characters", [])
            if character.get("character_id") in required_character_ids
        ]
        pov = next(
            (
                character
                for character in selected_characters
                if character.get("character_id") == pov_character_id
            ),
            None,
        )
        location_id = scene_state.get("location_id")
        if not location_id and pov:
            location_id = pov.get("current_state", {}).get("current_location_id")

        text = player_input.casefold()
        selected_locations: list[dict[str, Any]] = []
        location_index: list[dict[str, str]] = []
        for location in before_state.get("locations", []):
            known_id = str(location.get("location_id", ""))
            name = cls._location_name(location)
            location_index.append({"location_id": known_id, "name": name})
            mentioned = bool(known_id and known_id.casefold() in text) or bool(
                name and name.casefold() in text
            )
            if known_id == location_id or mentioned:
                selected_locations.append(location)

        known_object_ids = {
            str(item.get("object_id"))
            for item in before_state.get("objects", [])
            if item.get("object_id")
        }
        referenced_object_ids = cls._contains_known_id(scene_state, known_object_ids)
        for character in selected_characters:
            referenced_object_ids.update(
                cls._contains_known_id(character.get("current_state", {}), known_object_ids)
            )

        selected_objects: list[dict[str, Any]] = []
        object_index: list[dict[str, str]] = []
        for item in before_state.get("objects", []):
            object_id = str(item.get("object_id", ""))
            name = cls._object_name(item)
            object_index.append({"object_id": object_id, "name": name})
            mentioned = bool(object_id and object_id.casefold() in text) or bool(
                name and name.casefold() in text
            )
            if object_id in referenced_object_ids or mentioned:
                selected_objects.append(item)

        manifest = before_state.get("manifest", {})
        manifest_slice = {
            key: manifest.get(key)
            for key in (
                "schema_version",
                "state_revision",
                "character_ids",
                "location_ids",
                "object_ids",
            )
            if key in manifest
        }
        writer_state = {
            "manifest": cls._clean(manifest_slice),
            "scene_state": cls._clean(scene_state),
            "world": cls._current_world_slice(before_state.get("world_state", {})),
            "characters": cls._clean(selected_characters),
            "locations": cls._clean(selected_locations),
            "location_index": cls._clean(location_index),
            "objects": cls._clean(selected_objects),
            "object_index": cls._clean(object_index),
        }
        return writer_state, str(location_id) if location_id else None

    @staticmethod
    def _validate_footer(scene_output: str, turn_number: int, cycle_position: int) -> None:
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

    def get_turn_packet(self, session_id: str, request: Any) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            session = self._require_session(session_id)
            pending = self.storage.read_json(session_id, "pending_turn.json", default={})
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
            _chronology_manifest, _parts, chronology = self._read_chronology_locked(session_id)
            chronology = self._effective_chronology(chronology)
            last_completed = int(session.get("last_completed_turn", 0))

            if request.mode == "revise_last":
                if last_completed < 1:
                    raise ServiceError(409, "NO_TURN_TO_REVISE", "There is no completed turn to revise")
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
                revising_turn = self._compact_turn(self._public_turn(existing_turn))
                history_end = last_completed - 1
                exclude_memory_turn = turn_number
            else:
                before_state = current_state
                turn_number = last_completed + 1
                cycle_position = int(session.get("turns_since_audit", 0)) + 1
                turn_revision = 1
                revising_turn = None
                history_end = last_completed
                exclude_memory_turn = None

            novel_state = before_state.get("novel", {})
            scene_state = before_state.get("scene_state", {})
            pov_character_id = novel_state.get("pov_character_id")
            present_character_ids = list(
                dict.fromkeys(scene_state.get("present_character_ids", []))
            )
            required_full_character_ids = list(
                dict.fromkeys(
                    character_id
                    for character_id in [pov_character_id, *present_character_ids]
                    if character_id
                )
            )

            packet_state, location_id = self._writer_state(
                before_state,
                required_character_ids=required_full_character_ids,
                pov_character_id=pov_character_id,
                player_input=request.player_input,
            )

            history_from = max(history_end - self.RECENT_FULL_SCENES + 1, 1)
            recent_scene_history = (
                [
                    self._compact_turn(turn)
                    for turn in self._read_turn_range_locked(
                        session_id, history_from, history_end
                    )
                ]
                if history_end >= history_from
                else []
            )
            story_memory = self._select_story_memory(
                chronology,
                last_completed=last_completed,
                participant_ids=required_full_character_ids,
                location_id=location_id,
                exclude_turn=exclude_memory_turn,
            )

            turn_id = _new_id(f"turn_{turn_number}", 9)
            packet_id = _new_id("turnpacket", 9)
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
                "story_bible": {
                    "novel": self._clean(before_state.get("novel", {})),
                    "hidden_lore": self._clean(before_state.get("hidden_lore", {})),
                    "active_plot": self._clean(before_state.get("plot_state", {})),
                    "story_direction": self._active_story_direction(
                        before_state.get("director_plan", {})
                    ),
                },
                "state": packet_state,
                "story_memory": story_memory,
                "recent_scene_history": recent_scene_history,
                "scene_focus": {
                    "pov_character_id": pov_character_id,
                    "present_character_ids": present_character_ids,
                    "required_full_character_ids": required_full_character_ids,
                    "instruction": (
                        "These are the people who matter in the current frame. Use their full "
                        "character data as a character bible, not as a checklist. Keep POV alive "
                        "in the scene without choosing major decisions for the player."
                    ),
                },
                "revising_turn": revising_turn,
                "instruction": (
                    "Write the next piece of the novel from the current moment. story_memory is "
                    "compact continuity; recent_scene_history preserves the immediate rhythm and "
                    "dialogue. Do not reconstruct or audit the archive during a normal turn. "
                    "story_direction is an outline, not a list of beats that must fire now. "
                    "Write the scene first. After it is complete, commit only facts and state "
                    "changes that the written scene actually established."
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
                "required_full_character_ids": required_full_character_ids,
                "loaded_scene_character_ids": [],
                "scene_character_bundles": {},
            }
            return self._store_packet_locked(
                session_id,
                packet_type="turn",
                packet_id=packet_id,
                payload=payload,
                pending=pending,
            )
