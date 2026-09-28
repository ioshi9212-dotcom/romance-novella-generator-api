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
    CONTINUITY_TURNS = 15
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
    def _parse_player_input(text: str) -> dict[str, Any]:
        ordered: list[dict[str, str]] = []
        buffer: list[str] = []
        depth = 0
        kind = "spoken"
        unclosed = False

        def flush(segment_kind: str) -> None:
            value = "".join(buffer).strip()
            buffer.clear()
            if value:
                ordered.append({"kind": segment_kind, "text": value})

        for char in text:
            if char == "(":
                if depth == 0:
                    flush("spoken")
                    kind = "stage_direction"
                    depth = 1
                    continue
                depth += 1
                buffer.append(char)
                continue
            if char == ")" and depth > 0:
                depth -= 1
                if depth == 0:
                    flush("stage_direction")
                    kind = "spoken"
                    continue
                buffer.append(char)
                continue
            buffer.append(char)

        if buffer:
            if depth > 0:
                unclosed = True
                flush("stage_direction")
            else:
                flush(kind)

        spoken = [item["text"] for item in ordered if item["kind"] == "spoken"]
        stage = [item["text"] for item in ordered if item["kind"] == "stage_direction"]
        return {
            "ordered_segments": ordered,
            "spoken_segments": spoken,
            "stage_directions": stage,
            "unclosed_parenthesis": unclosed,
            "instruction": (
                "spoken segments are POV speech aloud. stage_direction segments are not speech "
                "and are not messages by themselves. A stage direction becomes communication "
                "only when it explicitly says the POV speaks, writes, sends or otherwise "
                "communicates something. Never merge an unrelated stage direction into the "
                "preceding spoken line."
            ),
        }

    def _continuity_window_locked(
        self,
        session_id: str,
        *,
        turn_from: int,
        turn_to: int,
        chronology: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if turn_to < turn_from:
            return []
        events_by_turn: dict[int, list[dict[str, Any]]] = {}
        for event in chronology:
            number = self._turn_number(event)
            if turn_from <= number <= turn_to:
                events_by_turn.setdefault(number, []).append(self._clean(event))

        result: list[dict[str, Any]] = []
        for turn_number in range(turn_from, turn_to + 1):
            raw_turn = self.storage.read_json(
                session_id, self._turn_path(turn_number), default={}
            )
            if not isinstance(raw_turn, dict) or not raw_turn:
                continue
            public = self._public_turn(raw_turn)
            item = self._clean(
                {
                    key: public.get(key)
                    for key in (
                        "turn_number",
                        "revision",
                        "cycle_position",
                        "player_input",
                        "summary",
                        "scene_id",
                        "story_datetime",
                    )
                    if key in public
                }
            )
            before_scene = raw_turn.get("before_state", {}).get("scene_state", {})
            item["present_at_start"] = self._clean(
                before_scene.get("present_character_ids", [])
            )
            item["loaded_scene_character_ids"] = self._clean(
                raw_turn.get("loaded_scene_character_ids", [])
            )
            item["events"] = events_by_turn.get(turn_number, [])
            result.append(item)
        return result

    def _character_continuity_index_locked(
        self,
        session_id: str,
        *,
        before_state: dict[str, Any],
        chronology: list[dict[str, Any]],
        pov_character_id: str | None,
        history_end: int,
    ) -> list[dict[str, Any]]:
        chronology_turns: dict[str, list[int]] = {}
        shared_turns: dict[str, list[int]] = {}
        for event in chronology:
            turn_number = self._turn_number(event)
            if turn_number < 1 or turn_number > history_end:
                continue
            participants = list(event.get("participants_present", []))
            for character_id in participants:
                chronology_turns.setdefault(str(character_id), []).append(turn_number)
            if pov_character_id and pov_character_id in participants:
                for character_id in participants:
                    if character_id != pov_character_id:
                        shared_turns.setdefault(str(character_id), []).append(turn_number)

        # Recover co-presence even if a chronology event was underspecified.
        scan_from = max(history_end - self.CONTINUITY_TURNS + 1, 1)
        for turn_number in range(scan_from, history_end + 1):
            raw_turn = self.storage.read_json(
                session_id, self._turn_path(turn_number), default={}
            )
            present = (
                raw_turn.get("before_state", {})
                .get("scene_state", {})
                .get("present_character_ids", [])
                if isinstance(raw_turn, dict)
                else []
            )
            for character_id in present:
                chronology_turns.setdefault(str(character_id), []).append(turn_number)
            if pov_character_id and pov_character_id in present:
                for character_id in present:
                    if character_id != pov_character_id:
                        shared_turns.setdefault(str(character_id), []).append(turn_number)

        current_present = set(
            before_state.get("scene_state", {}).get("present_character_ids", [])
        )
        result: list[dict[str, Any]] = []
        for character in before_state.get("characters", []):
            character_id = str(character.get("character_id", ""))
            if not character_id:
                continue
            card = character.get("card", {})
            identity = card.get("identity", {})
            appeared = sorted(set(chronology_turns.get(character_id, [])))
            shared = sorted(set(shared_turns.get(character_id, [])))
            result.append(
                {
                    "character_id": character_id,
                    "name": str(identity.get("name", "")),
                    "story_status": card.get("story_status"),
                    "card_level": card.get("card_level"),
                    "currently_present": character_id in current_present,
                    "first_seen_turn": appeared[0] if appeared else None,
                    "last_seen_turn": appeared[-1] if appeared else None,
                    "has_shared_scene_with_pov": bool(shared),
                    "last_shared_scene_with_pov_turn": shared[-1] if shared else None,
                }
            )
        return result

    @classmethod
    def _deep_merge_dict(cls, previous: Any, patch: Any) -> Any:
        if isinstance(previous, dict) and isinstance(patch, dict):
            result = deepcopy(previous)
            for key, value in patch.items():
                if key in result:
                    result[key] = cls._deep_merge_dict(result[key], value)
                else:
                    result[key] = deepcopy(value)
            return result
        # Lists in ordinary state are intentional replacements, so an active arc can close,
        # a temporary condition can clear, etc.
        return deepcopy(patch)

    @classmethod
    def _memory_item_identity(cls, item: Any) -> tuple[str, str] | None:
        if not isinstance(item, dict):
            return None
        for key in (
            "knowledge_id",
            "fact_id",
            "entry_id",
            "target_character_id",
            "id",
            "key",
        ):
            value = item.get(key)
            if value not in (None, ""):
                return key, str(value)
        return None

    @classmethod
    def _merge_memory_value(cls, previous: Any, patch: Any) -> Any:
        if isinstance(previous, dict) and isinstance(patch, dict):
            result = deepcopy(previous)
            for key, value in patch.items():
                if key in result:
                    result[key] = cls._merge_memory_value(result[key], value)
                else:
                    result[key] = deepcopy(value)
            return result
        if isinstance(previous, list) and isinstance(patch, list):
            result = deepcopy(previous)
            index: dict[tuple[str, str], int] = {}
            for position, item in enumerate(result):
                identity = cls._memory_item_identity(item)
                if identity is not None:
                    index[identity] = position
            for item in patch:
                identity = cls._memory_item_identity(item)
                if identity is not None and identity in index:
                    position = index[identity]
                    result[position] = cls._merge_memory_value(result[position], item)
                elif item not in result:
                    if identity is not None:
                        index[identity] = len(result)
                    result.append(deepcopy(item))
            return result
        return deepcopy(patch)

    def _apply_state_updates(
        self,
        base: dict[str, Any],
        updates: Any,
        *,
        session_id: str,
        state_revision: int,
        updated_turn: int,
    ) -> dict[str, Any]:
        """Use patch semantics for memory-bearing documents in production.

        scene_state remains a full replacement. Knowledge and directional relationships
        preserve unrelated established entries; corrections should update the same entry
        and mark it corrected/superseded instead of silently deleting history.
        """

        prepared = deepcopy(updates)

        for key in ("novel", "hidden_lore", "plot_state", "world_state"):
            patch = getattr(prepared, key, None)
            if isinstance(patch, dict):
                previous = self._clean(base.get(key, {}))
                setattr(prepared, key, self._deep_merge_dict(previous, patch))

        director_plan = getattr(prepared, "director_plan", None)
        if director_plan is not None:
            fields_set = set(getattr(director_plan, "model_fields_set", set()))
            patch = director_plan.model_dump(mode="json", include=fields_set)
            previous = self._clean(base.get("director_plan", {}))
            merged = self._deep_merge_dict(previous, patch)
            prepared.director_plan = type(director_plan).model_validate(merged)

        existing_characters = {
            item.get("character_id"): item for item in base.get("characters", [])
        }
        for update in prepared.characters:
            existing = existing_characters.get(update.character_id)
            if not existing:
                continue
            if update.current_state is not None:
                previous_state = self._clean(existing.get("current_state", {}))
                update.current_state = self._deep_merge_dict(
                    previous_state, update.current_state
                )
            if update.knowledge is not None:
                previous_knowledge = self._clean(existing.get("knowledge", {}))
                update.knowledge = self._merge_memory_value(
                    previous_knowledge, update.knowledge
                )
            if update.relationships is not None:
                previous_relationships = self._clean(
                    existing.get("relationships", {})
                )
                patch_relationships = update.relationships.model_dump(mode="json")
                merged_relationships = self._merge_memory_value(
                    previous_relationships, patch_relationships
                )
                update.relationships = type(update.relationships).model_validate(
                    merged_relationships
                )

        return super()._apply_state_updates(
            base,
            prepared,
            session_id=session_id,
            state_revision=state_revision,
            updated_turn=updated_turn,
        )

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
            continuity_from = max(history_end - self.CONTINUITY_TURNS + 1, 1)
            continuity_window = self._continuity_window_locked(
                session_id,
                turn_from=continuity_from,
                turn_to=history_end,
                chronology=chronology,
            )
            story_memory = self._select_story_memory(
                chronology,
                last_completed=last_completed,
                participant_ids=required_full_character_ids,
                location_id=location_id,
                exclude_turn=exclude_memory_turn,
            )
            character_continuity_index = self._character_continuity_index_locked(
                session_id,
                before_state=before_state,
                chronology=chronology,
                pov_character_id=pov_character_id,
                history_end=history_end,
            )
            player_input_map = self._parse_player_input(request.player_input)

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
                "player_input_map": player_input_map,
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
                "continuity_window": continuity_window,
                "recent_scene_history": recent_scene_history,
                "character_continuity_index": character_continuity_index,
                "scene_focus": {
                    "pov_character_id": pov_character_id,
                    "present_character_ids": present_character_ids,
                    "required_full_character_ids": required_full_character_ids,
                    "instruction": (
                        "These are the people in the current frame. Read their full card, "
                        "current_state, relationships and knowledge. character_continuity_index "
                        "prevents accidental first-meeting resets: if a character already shared "
                        "a recorded scene with POV, do not introduce them as a new acquaintance. "
                        "Identity details still depend on POV knowledge."
                    ),
                },
                "revising_turn": revising_turn,
                "instruction": (
                    "Before writing, do a short continuity preflight: reconcile the current frame "
                    "with continuity_window (up to the last 15 turns), the two recent full scenes, "
                    "story_memory and current Railway state. Do not invent a reset when they "
                    "disagree; Railway canon and actual committed events win. Use player_input_map "
                    "literally: spoken segments are speech aloud; stage directions are not speech "
                    "or messages unless they explicitly describe communication. Then write the "
                    "next piece of the novel. story_direction is flexible, not mandatory beats. "
                    "After writing, commit every meaningful event and update knowledge for every "
                    "character who actually saw/heard/received it, not only the addressee."
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

    def _build_audit_targets_locked(
        self,
        session_id: str,
        *,
        turn_from: int,
        turn_to: int,
        state: dict[str, Any] | None = None,
        chronology: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        state = state or self._read_state_bundle_locked(session_id)
        if chronology is None:
            _manifest, _parts, chronology = self._read_chronology_locked(session_id)
            chronology = self._effective_chronology(chronology)

        range_events = [
            event
            for event in chronology
            if turn_from <= self._turn_number(event) <= turn_to
        ]
        participants: set[str] = set()
        for event in range_events:
            participants.update(str(item) for item in event.get("participants_present", []))

        # Recover physically present characters from the raw turn snapshots as a second source.
        for turn_number in range(turn_from, turn_to + 1):
            raw_turn = self.storage.read_json(
                session_id, self._turn_path(turn_number), default={}
            )
            if not isinstance(raw_turn, dict):
                continue
            start_present = (
                raw_turn.get("before_state", {})
                .get("scene_state", {})
                .get("present_character_ids", [])
            )
            participants.update(str(item) for item in start_present)
            participants.update(
                str(item) for item in raw_turn.get("loaded_scene_character_ids", [])
            )
        participants.update(
            str(item)
            for item in state.get("scene_state", {}).get("present_character_ids", [])
        )

        touched_characters: set[str] = set(participants)
        knowledge_targets: set[str] = set(participants)
        for character in state.get("characters", []):
            character_id = str(character.get("character_id", ""))
            if not character_id:
                continue
            for document_name in ("card", "current_state", "relationships", "knowledge"):
                document = character.get(document_name, {})
                try:
                    last_updated = int(document.get("_meta", {}).get("last_updated_turn", 0))
                except (TypeError, ValueError):
                    last_updated = 0
                if turn_from <= last_updated <= turn_to:
                    touched_characters.add(character_id)
                    if document_name == "knowledge":
                        knowledge_targets.add(character_id)

        pov_character_id = state.get("novel", {}).get("pov_character_id")
        if pov_character_id:
            touched_characters.add(str(pov_character_id))

        return {
            "turn_numbers": list(range(turn_from, turn_to + 1)),
            "chronology_event_ids": [
                str(event["event_id"])
                for event in range_events
                if event.get("event_id")
            ],
            "character_ids": sorted(touched_characters),
            "knowledge_character_ids": sorted(knowledge_targets),
        }

    def get_audit_packet(self, session_id: str) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            session = self._require_session(session_id)
            pending = self.storage.read_json(session_id, "pending_audit.json", default={})
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
            audit_targets = self._build_audit_targets_locked(
                session_id,
                turn_from=turn_from,
                turn_to=turn_to,
                state=state,
                chronology=chronology,
            )
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
                "audit_targets": audit_targets,
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
                    "director_plan_and_offscreen_consequences",
                    "character_card_levels_and_promotions",
                    "location_canon_and_current_changes",
                    "compaction_and_duplicates",
                ],
                "required_findings_verification": {
                    "turns_checked": audit_targets["turn_numbers"],
                    "chronology_event_ids_checked": audit_targets[
                        "chronology_event_ids"
                    ],
                    "characters_checked": audit_targets["character_ids"],
                    "knowledge_checked_character_ids": audit_targets[
                        "knowledge_character_ids"
                    ],
                    "final_consistency_pass": True,
                    "unresolved_issues": [],
                },
                "instruction": (
                    "This is a hard memory audit, not a summary. Read all 15 full turns, current "
                    "state and chronology. Pass 1: scene by scene, verify objective events, order, "
                    "time, movement, participants, introductions and consequences. Pass 2: for "
                    "each audit target character, reconstruct only what they personally saw, heard, "
                    "were told, read, discovered or reasonably inferred; add missing knowledge and "
                    "correct unsupported knowledge without deleting established history. Pass 3: "
                    "reconcile scene/current state, relationships, plot arcs, hidden lore, "
                    "director_plan, locations and minor NPC lifecycle. Compact only true repetition. "
                    "Repeat consistency checks until no unresolved issue remains. Only then call "
                    "commitAudit, with findings.verification covering every audit target and "
                    "unresolved_issues empty."
                ),
            }
            pending = {
                "audit_id": audit_id,
                "turn_from": turn_from,
                "turn_to": turn_to,
                "expected_state_revision": int(session["state_revision"]),
                "audit_targets": audit_targets,
            }
            return self._store_packet_locked(
                session_id,
                packet_type="audit",
                packet_id=packet_id,
                payload=payload,
                pending=pending,
            )

    @staticmethod
    def _require_verification_set(
        verification: dict[str, Any],
        *,
        field: str,
        required: list[Any],
    ) -> None:
        supplied = verification.get(field)
        if not isinstance(supplied, list):
            raise ServiceError(
                422,
                "AUDIT_EVIDENCE_INCOMPLETE",
                f"findings.verification.{field} must be a list covering every audit target",
            )
        required_set = {str(item) for item in required}
        supplied_set = {str(item) for item in supplied}
        missing = sorted(required_set - supplied_set)
        if missing:
            raise ServiceError(
                422,
                "AUDIT_EVIDENCE_INCOMPLETE",
                f"Audit evidence is missing {field}: " + ", ".join(missing),
            )

    def _validate_audit_evidence(
        self, findings: dict[str, Any], audit_targets: dict[str, Any]
    ) -> None:
        verification = findings.get("verification")
        if not isinstance(verification, dict):
            raise ServiceError(
                422,
                "AUDIT_EVIDENCE_INCOMPLETE",
                "findings.verification is required before commitAudit",
            )
        for field, target_key in (
            ("turns_checked", "turn_numbers"),
            ("chronology_event_ids_checked", "chronology_event_ids"),
            ("characters_checked", "character_ids"),
            ("knowledge_checked_character_ids", "knowledge_character_ids"),
        ):
            self._require_verification_set(
                verification,
                field=field,
                required=list(audit_targets.get(target_key, [])),
            )
        if verification.get("final_consistency_pass") is not True:
            raise ServiceError(
                422,
                "AUDIT_EVIDENCE_INCOMPLETE",
                "final_consistency_pass must be true before commitAudit",
            )
        unresolved = verification.get("unresolved_issues")
        if not isinstance(unresolved, list) or unresolved:
            raise ServiceError(
                422,
                "AUDIT_EVIDENCE_INCOMPLETE",
                "unresolved_issues must be an empty list before commitAudit",
            )

    def commit_audit(self, session_id: str, request: Any) -> dict[str, Any]:
        self._require_session(session_id)
        validate = False
        targets: dict[str, Any] = {}
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(session_id, "pending_audit.json", default={})
            if (
                pending.get("status") == "active"
                and pending.get("audit_id") == request.audit_id
            ):
                turn_from = int(pending["turn_from"])
                turn_to = int(pending["turn_to"])
                targets = pending.get("audit_targets") or self._build_audit_targets_locked(
                    session_id, turn_from=turn_from, turn_to=turn_to
                )
                validate = True
        if validate:
            self._validate_audit_evidence(request.findings, targets)
        return super().commit_audit(session_id, request)
