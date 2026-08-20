from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from typing import Any

from app.character_registry import (
    build_character_registry,
    character_name_aliases,
    reserved_character_names,
)
from app.service import NovellaService, ServiceError, _split_text
from app.writer_service import WriterFirstNovellaService


class EnhancedWriterNovellaService(WriterFirstNovellaService):
    """Adds small author-facing continuity layers without expanding the public API."""

    ENHANCED_PACKET_VERSION = 3
    ENHANCED_AUDIT_PACKET_VERSION = 1
    INTRO_MARKERS = (
        "познаком",
        "представил",
        "представила",
        "представился",
        "представилась",
        "представлены",
        "обменялись имен",
        "назвал свое имя",
        "назвала свое имя",
        "узнал имя",
        "узнала имя",
        "introduced",
        "met for the first time",
        "exchanged names",
    )

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

    @classmethod
    def _event_explicitly_introduces_pair(
        cls,
        event: dict[str, Any],
        pov_character_id: str,
        character_id: str,
    ) -> bool:
        participants = {str(item) for item in event.get("participants_present", [])}
        if pov_character_id not in participants or character_id not in participants:
            return False
        text = " ".join(
            str(event.get(key, ""))
            for key in ("event", "summary", "fact", "description")
        ).casefold().replace("ё", "е")
        if "не познаком" in text or "не представ" in text:
            return False
        return any(marker in text for marker in cls.INTRO_MARKERS)

    @staticmethod
    def _has_relationship_evidence(
        character: dict[str, Any], pov_character_id: str
    ) -> bool:
        for relation in character.get("relationships", {}).get("relations", []):
            if str(relation.get("target_character_id", "")) != pov_character_id:
                continue
            if relation.get("dimensions"):
                return True
            if relation.get("beliefs_about_target") or relation.get("unresolved_between_them"):
                return True
            for key in ("relationship_type", "relationship_context", "current_dynamic"):
                value = str(relation.get(key, "")).strip()
                if value:
                    return True
        return False

    @staticmethod
    def _knowledge_mentions_character(
        owner: dict[str, Any], target_id: str, target_name: str
    ) -> bool:
        knowledge = owner.get("knowledge", {})
        text = json.dumps(knowledge, ensure_ascii=False).casefold().replace("ё", "е")
        if target_id and target_id.casefold() in text:
            return True
        normalized_name = " ".join(target_name.casefold().replace("ё", "е").split())
        if normalized_name and normalized_name in text:
            return True
        first_name = normalized_name.split()[0] if normalized_name else ""
        return bool(first_name and len(first_name) >= 3 and first_name in text)

    @classmethod
    def _registry_with_continuity(
        cls,
        before_state: dict[str, Any],
        payload: dict[str, Any],
        chronology: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        registry = build_character_registry(before_state.get("characters", []))
        continuity = {
            str(item.get("character_id")): item
            for item in payload.get("character_continuity_index", [])
            if item.get("character_id")
        }
        characters = {
            str(item.get("character_id", "")): item
            for item in before_state.get("characters", [])
            if item.get("character_id")
        }
        pov_character_id = str(before_state.get("novel", {}).get("pov_character_id", ""))
        pov_character = characters.get(pov_character_id, {})
        pov_name = str(
            pov_character.get("card", {}).get("identity", {}).get("name", "")
        )

        for entry in registry:
            character_id = str(entry.get("character_id", ""))
            continuity_entry = continuity.get(character_id, {})
            entry["encountered_with_pov"] = bool(
                continuity_entry.get("has_shared_scene_with_pov")
            )
            entry["first_shared_scene_with_pov_turn"] = continuity_entry.get(
                "first_seen_turn"
            )
            entry["last_shared_scene_with_pov_turn"] = continuity_entry.get(
                "last_shared_scene_with_pov_turn"
            )
            familiarity = entry.get("pov_familiarity")
            if isinstance(familiarity, dict) and familiarity.get("status"):
                entry["continuity_status"] = familiarity.get("status")
                entry["familiarity_source"] = "stored"
                continue

            character = characters.get(character_id, {})
            explicit_events = [
                event
                for event in chronology
                if cls._event_explicitly_introduces_pair(
                    event, pov_character_id, character_id
                )
            ]
            if explicit_events:
                first_event = min(
                    explicit_events,
                    key=lambda item: int(item.get("turn_number", 0) or 0),
                )
                entry["continuity_status"] = "acquainted"
                entry["familiarity_source"] = "legacy_chronology"
                entry["legacy_familiarity_evidence"] = {
                    "kind": "explicit_introduction_event",
                    "turn_number": first_event.get("turn_number"),
                    "event_id": first_event.get("event_id"),
                }
                continue

            shared = entry["encountered_with_pov"]
            relationship_evidence = cls._has_relationship_evidence(
                character, pov_character_id
            )
            character_name = str(entry.get("name", ""))
            npc_knows_pov = cls._knowledge_mentions_character(
                character, pov_character_id, pov_name
            )
            pov_knows_npc = cls._knowledge_mentions_character(
                pov_character, character_id, character_name
            )
            if shared and (relationship_evidence or (npc_knows_pov and pov_knows_npc)):
                entry["continuity_status"] = "legacy_known_relationship"
                entry["familiarity_source"] = "legacy_state_inference"
                entry["legacy_familiarity_evidence"] = {
                    "shared_scene": True,
                    "directed_relationship_to_pov": relationship_evidence,
                    "npc_identity_knowledge": npc_knows_pov,
                    "pov_identity_knowledge": pov_knows_npc,
                }
            elif shared:
                entry["continuity_status"] = "encountered"
                entry["familiarity_source"] = "legacy_copresence"
            else:
                entry["continuity_status"] = "not_encountered"
                entry["familiarity_source"] = "none"
        return registry

    @staticmethod
    def _reserved_name_rows(before_state: dict[str, Any]) -> list[dict[str, str]]:
        by_id = {
            str(item.get("character_id", "")): item
            for item in before_state.get("characters", [])
        }
        rows: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for alias, character_id in reserved_character_names(
            before_state.get("characters", [])
        ).items():
            key = (alias, character_id)
            if key in seen:
                continue
            seen.add(key)
            card = by_id.get(character_id, {}).get("card", {})
            display = str(card.get("identity", {}).get("name", "")).strip()
            rows.append(
                {
                    "reserved_name": alias,
                    "character_id": character_id,
                    "display_name": display,
                }
            )
        return rows

    @staticmethod
    def _familiarity_backfill_targets(
        registry: list[dict[str, Any]], pov_character_id: str
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for entry in registry:
            character_id = str(entry.get("character_id", ""))
            if not character_id or character_id == pov_character_id:
                continue
            if entry.get("familiarity_source") == "stored":
                continue
            status = entry.get("continuity_status")
            if status == "acquainted":
                evidence = entry.get("legacy_familiarity_evidence", {})
                result.append(
                    {
                        "character_id": character_id,
                        "name": entry.get("name"),
                        "required_status": "acquainted",
                        "evidence": deepcopy(evidence),
                    }
                )
            elif status == "legacy_known_relationship":
                result.append(
                    {
                        "character_id": character_id,
                        "name": entry.get("name"),
                        "required_status": "known_or_acquainted",
                        "evidence": deepcopy(
                            entry.get("legacy_familiarity_evidence", {})
                        ),
                    }
                )
        return result

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
        _chronology_manifest, _parts, chronology = self._read_chronology_locked(session_id)
        chronology = self._effective_chronology(chronology)
        character_registry = self._registry_with_continuity(
            before_state, payload, chronology
        )
        novel = payload.setdefault("story_bible", {}).setdefault("novel", {})
        novel["character_registry"] = character_registry
        novel["character_registry_instruction"] = (
            "Compact authoritative roster derived from character cards every turn. Player-defined "
            "characters stay here for the whole session; recurring/important runtime NPCs appear "
            "automatically. character_id is the link to the full card. continuity_status is not "
            "cosmetic: acquainted means a recorded introduction exists; known means stored identity/" 
            "relationship familiarity; legacy_known_relationship means an older session already "
            "contains enough shared-scene/relationship evidence that the pair must not be reset to "
            "strangers; encountered means prior co-presence only and does not prove a formal "
            "introduction. Never stage a first meeting again for acquainted, known or "
            "legacy_known_relationship. During the next mandatory audit, backfill missing "
            "current_state.pov_familiarity for strong legacy evidence instead of discarding it."
        )
        payload["reserved_character_names"] = {
            "names": self._reserved_name_rows(before_state),
            "instruction": (
                "Every listed name/first-name alias belongs to its character_id and is reserved. "
                "Do not assign it to a newly invented NPC. If a new recurring/important NPC is "
                "needed, choose a different name and create one card/id for that person."
            ),
        }
        payload["game_clock"] = game_clock
        payload["relationship_lens"] = self._relationship_lens(before_state)
        payload["instruction"] = (
            str(payload.get("instruction", ""))
            + " Use game_clock for the authoritative Day N header. Use relationship_lens as "
            "causal input to NPC behavior. Before inventing/naming a character, check "
            "story_bible.novel.character_registry and reserved_character_names. When POV and a "
            "character explicitly become acquainted, commit an objective chronology event and "
            "set that character current_state.pov_familiarity = {status: acquainted, since_turn: "
            "current turn, source: explicit_scene}; also update personal knowledge of names/identity "
            "according to what each person actually learned. Mere co-presence is encountered, not "
            "automatically acquainted. For old sessions, acquainted, known and "
            "legacy_known_relationship must never be written as a new first meeting."
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

    def _augment_audit_packet_locked(
        self,
        session_id: str,
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            pending.get("enhanced_audit_packet_version")
            == self.ENHANCED_AUDIT_PACKET_VERSION
        ):
            return self._packet_chunk_response(session_id, pending, 0)

        raw = "".join(pending.get("chunks", []))
        if not raw:
            raise ServiceError(500, "AUDIT_PACKET_CORRUPT", "Audit packet has no content")
        payload = json.loads(raw)
        state = payload.get("state", {})
        chronology = payload.get("chronology", [])
        pov_character_id = str(state.get("novel", {}).get("pov_character_id", ""))
        continuity_index = self._character_continuity_index_locked(
            session_id,
            before_state=state,
            chronology=chronology,
            pov_character_id=pov_character_id or None,
            history_end=int(payload.get("turn_to", 0)),
        )
        registry = self._registry_with_continuity(
            state,
            {"character_continuity_index": continuity_index},
            chronology,
        )
        backfill_targets = self._familiarity_backfill_targets(
            registry, pov_character_id
        )
        payload["character_familiarity_audit"] = {
            "registry": registry,
            "backfill_targets": backfill_targets,
            "instruction": (
                "Audit familiarity as canon. For every backfill target, inspect chronology, full "
                "turns, knowledge and relationships. If required_status is acquainted, write "
                "current_state.pov_familiarity.status = acquainted. If required_status is "
                "known_or_acquainted, preserve the fact that they are not strangers: use status "
                "known unless the audit establishes an explicit introduction, then use acquainted. "
                "Include source=legacy_audit and useful evidence/turn metadata. Do not backfill "
                "encountered-only characters as acquainted merely because they shared a room."
            ),
        }
        verification = payload.setdefault("required_findings_verification", {})
        verification["familiarity_checked_character_ids"] = [
            item["character_id"] for item in backfill_targets
        ]
        payload["instruction"] = (
            str(payload.get("instruction", ""))
            + " Also reconcile character_familiarity_audit. Every listed backfill target must "
            "be checked and persisted in current_state.pov_familiarity before commitAudit. Put "
            "all target IDs in findings.verification.familiarity_checked_character_ids."
        ).strip()

        text = json.dumps(payload, ensure_ascii=False, indent=2)
        chunks = _split_text(text, self.settings.packet_chunk_chars)
        pending.update(
            {
                "chunks": chunks,
                "content_sha256": sha256(text.encode("utf-8")).hexdigest(),
                "last_delivered_chunk_index": 0,
                "all_chunks_delivered": len(chunks) == 1,
                "enhanced_audit_packet_version": self.ENHANCED_AUDIT_PACKET_VERSION,
                "familiarity_backfill_targets": backfill_targets,
            }
        )
        self.storage._write_json_batch_locked(
            session_id, {"pending_audit.json": pending}
        )
        return self._packet_chunk_response(session_id, pending, 0)

    def get_turn_packet(self, session_id: str, request: Any) -> dict[str, Any]:
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

    def get_audit_packet(self, session_id: str) -> dict[str, Any]:
        super().get_audit_packet(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )
            if pending.get("status") != "active":
                raise ServiceError(
                    409, "AUDIT_NOT_PENDING", "Audit packet is no longer active"
                )
            return self._augment_audit_packet_locked(session_id, pending)

    def create_session(self, request: Any) -> dict[str, Any]:
        owner_by_alias: dict[str, str] = {}
        for character in request.characters:
            card = character.card.model_dump(mode="json")
            for alias in character_name_aliases(card):
                previous = owner_by_alias.get(alias)
                if previous and previous != character.character_id:
                    raise ServiceError(
                        422,
                        "CHARACTER_NAME_RESERVED",
                        f"Character name '{alias}' is already assigned to {previous}",
                    )
                owner_by_alias[alias] = character.character_id
        return super().create_session(request)

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
        if expected_day is not None:
            header = "\n".join(request.scene_output.splitlines()[:4])
            if f"День {expected_day}" not in header:
                raise ServiceError(
                    422,
                    "GAME_DAY_HEADER_MISMATCH",
                    f"Scene header must display authoritative story day: День {expected_day}",
                )

        reserved = reserved_character_names(before_state.get("characters", []))
        for update in request.state_updates.characters:
            if update.card is None:
                continue
            card = update.card.model_dump(mode="json")
            for alias in character_name_aliases(card):
                owner_id = reserved.get(alias)
                if owner_id and owner_id != update.character_id:
                    raise ServiceError(
                        422,
                        "CHARACTER_NAME_RESERVED",
                        f"Character name '{alias}' is reserved for {owner_id}; choose a different "
                        f"name for {update.character_id}",
                    )

    @staticmethod
    def _validate_familiarity_audit_backfill(
        request: Any,
        targets: list[dict[str, Any]],
    ) -> None:
        verification = request.findings.get("verification", {})
        checked = {
            str(item)
            for item in verification.get("familiarity_checked_character_ids", [])
        }
        required_ids = {str(item.get("character_id", "")) for item in targets}
        missing_checked = sorted(required_ids - checked)
        if missing_checked:
            raise ServiceError(
                422,
                "AUDIT_FAMILIARITY_INCOMPLETE",
                "Familiarity audit did not cover: " + ", ".join(missing_checked),
            )

        updates = {
            str(item.character_id): item
            for item in request.state_updates.characters
        }
        for target in targets:
            character_id = str(target.get("character_id", ""))
            update = updates.get(character_id)
            current_state = update.current_state if update is not None else None
            familiarity = (
                current_state.get("pov_familiarity")
                if isinstance(current_state, dict)
                else None
            )
            if not isinstance(familiarity, dict):
                raise ServiceError(
                    422,
                    "AUDIT_FAMILIARITY_BACKFILL_REQUIRED",
                    f"Audit must persist pov_familiarity for {character_id}",
                )
            status = str(familiarity.get("status", "")).strip().lower()
            required = target.get("required_status")
            allowed = (
                {"acquainted"}
                if required == "acquainted"
                else {"known", "acquainted"}
            )
            if status not in allowed:
                raise ServiceError(
                    422,
                    "AUDIT_FAMILIARITY_BACKFILL_REQUIRED",
                    f"pov_familiarity.status for {character_id} must be one of: "
                    + ", ".join(sorted(allowed)),
                )

    def commit_audit(self, session_id: str, request: Any) -> dict[str, Any]:
        self._require_session(session_id)
        targets: list[dict[str, Any]] = []
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )
            if (
                pending.get("status") == "active"
                and pending.get("audit_id") == request.audit_id
            ):
                targets = list(pending.get("familiarity_backfill_targets", []))
        if targets:
            self._validate_familiarity_audit_backfill(request, targets)
        return super().commit_audit(session_id, request)
