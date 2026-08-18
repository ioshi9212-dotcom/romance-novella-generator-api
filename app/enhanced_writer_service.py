from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from typing import Any

from app.service import NovellaService, ServiceError, _split_text
from app.writer_service import WriterFirstNovellaService


class EnhancedWriterNovellaService(WriterFirstNovellaService):
    """Adds a small author-facing layer for story-day and relationship causality.

    No new public API is required: the extra fields are injected into the existing turn
    packet before its first chunk is returned.
    """

    ENHANCED_PACKET_VERSION = 1

    @staticmethod
    def _parse_story_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    @classmethod
    def _game_day_for(cls, start_value: Any, current_value: Any) -> int | None:
        start = cls._parse_story_datetime(start_value)
        current = cls._parse_story_datetime(current_value)
        if start is None or current is None:
            return None
        return max((current.date() - start.date()).days + 1, 1)

    def _story_start_datetime_locked(
        self,
        session_id: str,
        before_state: dict[str, Any],
    ) -> str | None:
        # Turn one keeps the exact pre-story state, so it is the authoritative fallback
        # for sessions created before this feature existed.
        first_turn = self.storage.read_json(
            session_id, self._turn_path(1), default={}
        )
        if isinstance(first_turn, dict) and first_turn:
            value = (
                first_turn.get("before_state", {})
                .get("world_state", {})
                .get("story_datetime")
            )
            if value:
                return str(value)

        value = before_state.get("world_state", {}).get("story_datetime")
        return str(value) if value else None

    @classmethod
    def _relationship_lens(cls, before_state: dict[str, Any]) -> dict[str, Any]:
        scene_state = before_state.get("scene_state", {})
        present_ids = list(dict.fromkeys(scene_state.get("present_character_ids", [])))
        present_set = set(present_ids)
        pov_character_id = before_state.get("novel", {}).get("pov_character_id")

        names: dict[str, str] = {}
        characters_by_id: dict[str, dict[str, Any]] = {}
        for character in before_state.get("characters", []):
            character_id = str(character.get("character_id", ""))
            if not character_id:
                continue
            characters_by_id[character_id] = character
            names[character_id] = str(
                character.get("card", {}).get("identity", {}).get("name", "")
            )

        relations: list[dict[str, Any]] = []
        for owner_id in present_ids:
            if owner_id == pov_character_id:
                # POV -> others is intentionally player-owned and is never assigned by runtime.
                continue
            owner = characters_by_id.get(owner_id)
            if not owner:
                continue
            for relation in owner.get("relationships", {}).get("relations", []):
                target_id = str(relation.get("target_character_id", ""))
                if not target_id:
                    continue
                if target_id != pov_character_id and target_id not in present_set:
                    continue
                dimensions = [
                    {
                        "key": item.get("key"),
                        "label": item.get("label"),
                        "value": item.get("value"),
                    }
                    for item in relation.get("dimensions", [])
                ]
                relations.append(
                    {
                        "owner_character_id": owner_id,
                        "owner_name": names.get(owner_id, ""),
                        "target_character_id": target_id,
                        "target_name": names.get(target_id, ""),
                        "relationship_type": relation.get("relationship_type"),
                        "current_dynamic": relation.get("current_dynamic"),
                        "dimensions": dimensions,
                        "beliefs_about_target": deepcopy(
                            relation.get("beliefs_about_target", [])
                        ),
                        "unresolved_between_them": deepcopy(
                            relation.get("unresolved_between_them", [])
                        ),
                        "dynamic_constraints": deepcopy(
                            relation.get("dynamic_constraints", [])
                        ),
                        "last_changed_turn": relation.get("last_changed_turn", 0),
                    }
                )

        return {
            "relations_in_current_scene": relations,
            "instruction": (
                "Relationship dimensions are causal state, not decorative footer numbers. "
                "Before choosing an NPC reaction, line, initiative or interpretation, combine "
                "their actual dimensions with personality, goals, knowledge and current state. "
                "Trust can affect belief and willingness; jealousy can affect attention, rivalry "
                "or restraint; closeness can affect familiarity; sympathy, attraction, respect, "
                "resentment, suspicion and other dimensions can matter differently for different "
                "people. Do not force every dimension to produce an obvious reaction: a character "
                "may hide it or act against it for another goal. Absence of a dimension is not zero. "
                "Do not create 'interest' as a generic fallback merely because the footer needs a "
                "number. Create or change only dimensions genuinely established by the relationship "
                "and scene; several independent dimensions may coexist and change separately."
            ),
        }

    def _augment_turn_packet_locked(
        self,
        session_id: str,
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        if pending.get("enhanced_packet_version") == self.ENHANCED_PACKET_VERSION:
            return self._packet_chunk_response(session_id, pending, 0)

        raw = "".join(pending.get("chunks", []))
        if not raw:
            raise ServiceError(500, "TURN_PACKET_CORRUPT", "Turn packet has no content")
        payload = json.loads(raw)
        before_state = pending.get("before_state", {})
        story_start_datetime = self._story_start_datetime_locked(
            session_id, before_state
        )
        turn_start_datetime = before_state.get("world_state", {}).get("story_datetime")
        game_day_at_turn_start = self._game_day_for(
            story_start_datetime, turn_start_datetime
        )
        game_clock = {
            "story_start_datetime": story_start_datetime,
            "turn_start_datetime": turn_start_datetime,
            "game_day_at_turn_start": game_day_at_turn_start,
            "instruction": (
                "The displayed game day is a calendar story-day count, not a turn count. "
                "Day 1 is the calendar date on which the story started. For the scene header, "
                "game_day = calendar date of the scene's displayed story datetime minus the "
                "story-start calendar date + 1. If the scene crosses midnight, increment it."
            ),
        }
        payload["game_clock"] = game_clock
        payload["relationship_lens"] = self._relationship_lens(before_state)
        payload["instruction"] = (
            str(payload.get("instruction", ""))
            + " Use game_clock for the authoritative Day N header. Use relationship_lens as "
            "causal input to NPC behavior, not merely as numbers to print after the scene."
        ).strip()

        text = json.dumps(payload, ensure_ascii=False, indent=2)
        chunks = _split_text(text, self.settings.packet_chunk_chars)
        pending.update(
            {
                "chunks": chunks,
                "content_sha256": sha256(text.encode("utf-8")).hexdigest(),
                "last_delivered_chunk_index": 0,
                "all_chunks_delivered": len(chunks) == 1,
                "enhanced_packet_version": self.ENHANCED_PACKET_VERSION,
                "game_clock": game_clock,
            }
        )
        self.storage._write_json_batch_locked(
            session_id, {"pending_turn.json": pending}
        )
        return self._packet_chunk_response(session_id, pending, 0)

    def get_turn_packet(self, session_id: str, request: Any) -> dict[str, Any]:
        # WriterFirst assembles the authoritative packet first. We then enrich that exact
        # packet before the first chunk reaches the caller.
        super().get_turn_packet(session_id, request)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_turn.json", default={}
            )
            if pending.get("status") != "active":
                raise ServiceError(
                    409, "TURN_NOT_PENDING", "Turn packet is no longer active"
                )
            return self._augment_turn_packet_locked(session_id, pending)

    @staticmethod
    def _validate_scene_commit_context(
        request: Any,
        pending: dict[str, Any],
        before_state: dict[str, Any],
        turn_number: int,
    ) -> None:
        NovellaService._validate_scene_commit_context(
            request, pending, before_state, turn_number
        )
        clock = pending.get("game_clock", {})
        expected_day = EnhancedWriterNovellaService._game_day_for(
            clock.get("story_start_datetime"), request.story_datetime
        )
        if expected_day is None:
            return
        header = "\n".join(request.scene_output.splitlines()[:4])
        if f"День {expected_day}" not in header:
            raise ServiceError(
                422,
                "GAME_DAY_HEADER_MISMATCH",
                f"Scene header must display authoritative story day: День {expected_day}",
            )
