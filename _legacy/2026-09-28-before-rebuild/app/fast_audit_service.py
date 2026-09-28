from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.service import NovellaService, ServiceError, _new_id


class FastAuditNovellaService(EnhancedWriterNovellaService):
    """Keep the existing runtime intact and replace only the 15-turn audit packet.

    The model already has the 15 visible turns in the current chat. Railway therefore sends
    only a compact snapshot of what is already persisted, so the model can fill omissions
    instead of rereading the whole novella from storage.
    """

    FAST_AUDIT_VERSION = 1

    def create_session(self, request: Any) -> dict[str, Any]:
        """Preserve the complete accepted setup once without adding it to turn packets."""
        result = super().create_session(request)
        session_id = str(result["session_id"])
        self.storage.write_json_batch(
            session_id,
            {
                "intake/confirmed_payload.json": {
                    "session_id": session_id,
                    "payload": request.model_dump(mode="json"),
                }
            },
        )
        return result

    @classmethod
    def _audit_character_snapshot(
        cls,
        state: dict[str, Any],
        character_ids: list[str],
    ) -> list[dict[str, Any]]:
        wanted = set(character_ids)
        result: list[dict[str, Any]] = []
        for character in state.get("characters", []):
            character_id = str(character.get("character_id", ""))
            if character_id not in wanted:
                continue
            card = character.get("card", {})
            result.append(
                {
                    "character_id": character_id,
                    "name": card.get("identity", {}).get("name"),
                    "current_state": cls._clean(character.get("current_state", {})),
                    "relationships": cls._clean(character.get("relationships", {})),
                    "knowledge": cls._clean(character.get("knowledge", {})),
                }
            )
        return result

    @classmethod
    def _audit_turn_summaries(
        cls,
        turns: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for turn in turns:
            result.append(
                cls._clean(
                    {
                        "turn_number": turn.get("turn_number"),
                        "player_input": turn.get("player_input"),
                        "summary": turn.get("summary"),
                        "scene_id": turn.get("scene_id"),
                        "story_datetime": turn.get("story_datetime"),
                    }
                )
            )
        return result

    @classmethod
    def _audit_chronology_slice(
        cls,
        chronology: list[dict[str, Any]],
        turn_from: int,
        turn_to: int,
    ) -> list[dict[str, Any]]:
        keep = (
            "event_id",
            "turn_number",
            "scene_id",
            "story_datetime",
            "location_id",
            "event",
            "summary",
            "fact",
            "description",
            "participants_present",
            "status",
        )
        return [
            cls._clean({key: event.get(key) for key in keep if key in event})
            for event in chronology
            if turn_from <= cls._turn_number(event) <= turn_to
        ]

    def get_audit_packet(self, session_id: str) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            session = self._require_session(session_id)
            pending = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )

            # Replace an old heavy packet that may already be stuck mid-audit.
            if (
                isinstance(pending, dict)
                and pending.get("status") == "active"
                and pending.get("fast_audit_version") == self.FAST_AUDIT_VERSION
            ):
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

            state = self._read_state_bundle_locked(session_id)
            _chronology_manifest, _parts, chronology = self._read_chronology_locked(
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
            turns = self._read_turn_range_locked(session_id, turn_from, turn_to)

            audit_id = _new_id(f"audit_{turn_from}_{turn_to}", 9)
            packet_id = _new_id("auditpacket", 9)
            payload = {
                "packet_type": "audit",
                "audit_mode": "fast_chat_reconciliation",
                "fast_audit_version": self.FAST_AUDIT_VERSION,
                "session_id": session_id,
                "audit_id": audit_id,
                "turn_from": turn_from,
                "turn_to": turn_to,
                "expected_state_revision": int(session["state_revision"]),
                "chat_turns_are_primary_review_source": True,
                "turn_summaries_backup": self._audit_turn_summaries(turns),
                "persisted_chronology_for_cycle": self._audit_chronology_slice(
                    chronology, turn_from, turn_to
                ),
                "persisted_state_snapshot": {
                    "scene_state": self._clean(state.get("scene_state", {})),
                    "world": self._current_world_slice(state.get("world_state", {})),
                    "plot_state": self._clean(state.get("plot_state", {})),
                    "characters": self._audit_character_snapshot(
                        state,
                        list(audit_targets.get("character_ids", [])),
                    ),
                },
                "audit_targets": audit_targets,
                "instruction": (
                    "FAST AUDIT. The 15 committed scenes are already visible in the current chat; "
                    "do not reread full scenes from Railway and do not perform multi-pass analysis. "
                    "Make one quick comparison of those visible 15 turns against this persisted "
                    "snapshot. Check only: (1) missing important chronology events, (2) missing or "
                    "unsupported character knowledge/relationship memory, and (3) obvious current "
                    "state contradictions with the latest scene. Add only missing/corrective data. "
                    "Do not re-audit hidden lore, director_plan, locations, card promotion or minor "
                    "NPC lifecycle unless an obvious contradiction is visible in these 15 turns. "
                    "Do not compact chronology during routine audit. After this single pass call "
                    "commitAudit immediately. For backward-compatible request schema, set every "
                    "legacy checklist boolean to true. findings may be brief; exhaustive verification "
                    "lists are not required. Never tell the player that audit is still running."
                ),
            }
            pending = {
                "audit_id": audit_id,
                "turn_from": turn_from,
                "turn_to": turn_to,
                "expected_state_revision": int(session["state_revision"]),
                "audit_targets": audit_targets,
                "fast_audit_version": self.FAST_AUDIT_VERSION,
            }
            return self._store_packet_locked(
                session_id,
                packet_type="audit",
                packet_id=packet_id,
                payload=payload,
                pending=pending,
            )

    def commit_audit(self, session_id: str, request: Any) -> dict[str, Any]:
        """Use the stable base commit path, skipping legacy exhaustive evidence gates."""
        return NovellaService.commit_audit(self, session_id, request)
