from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from typing import Any

from app.character_registry import character_display_name, character_name_aliases
from app.recovery_service import RecoveryNovellaService
from app.service import ServiceError, _split_text


class ActiveLoreNovellaService(RecoveryNovellaService):
    """Keep questionnaire canon, POV history and important cast causally active each turn.

    Railway remains authoritative. This layer changes only the writer packet: it adds an
    always-on story/POV memory, explicit knowledge lenses for scene NPCs, a compact cast index,
    keyword-activated full dossiers and a small offscreen cast pulse. No public API changes.
    """

    ACTIVE_LORE_PACKET_VERSION = 1
    MAX_ACTIVATED_CHARACTERS = 6
    MAX_OFFSCREEN_PULSES = 6
    MAX_CHARACTER_EVENTS = 8
    MAX_POV_EVENTS = 12

    @staticmethod
    def _normalized(value: Any) -> str:
        return " ".join(str(value or "").casefold().replace("ё", "е").split())

    @classmethod
    def _character_is_durable(cls, character: dict[str, Any]) -> bool:
        card = character.get("card", {})
        return bool(
            card.get("origin") == "player"
            or card.get("card_level") in {"recurring", "important", "player_defined"}
        )

    @classmethod
    def _causal_card(cls, card: dict[str, Any]) -> dict[str, Any]:
        """The parts of a card most likely to cause behavior, without duplicating appearance."""
        keep = (
            "card_level",
            "origin",
            "record_status",
            "story_status",
            "player_visibility",
            "identity",
            "card_hint",
            "immediate_scene_goal",
            "personality",
            "preferences",
            "biography",
            "skills",
            "goals",
            "hidden_motives",
            "secrets",
            "constraints",
        )
        return cls._clean({key: card.get(key) for key in keep if key in card})

    @classmethod
    def _character_aliases(cls, character: dict[str, Any]) -> set[str]:
        aliases = set(character_name_aliases(character.get("card", {})))
        character_id = cls._normalized(character.get("character_id"))
        if character_id:
            aliases.add(character_id)
        return {alias for alias in aliases if len(alias) >= 3}

    @classmethod
    def _is_mentioned(cls, character: dict[str, Any], text: str) -> bool:
        normalized = cls._normalized(text)
        return any(alias in normalized for alias in cls._character_aliases(character))

    @classmethod
    def _matching_director_rows(
        cls,
        character: dict[str, Any],
        director_plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        aliases = cls._character_aliases(character)
        if not aliases:
            return []
        result: list[dict[str, Any]] = []
        for section, value in director_plan.items():
            if not isinstance(value, list):
                continue
            for row in value:
                if not isinstance(row, dict):
                    continue
                row_text = cls._normalized(json.dumps(row, ensure_ascii=False))
                if any(alias in row_text for alias in aliases):
                    result.append({"section": section, "entry": cls._clean(row)})
                    if len(result) >= 4:
                        return result
        return result

    @classmethod
    def _relations_to_targets(
        cls,
        character: dict[str, Any],
        target_ids: set[str],
    ) -> list[dict[str, Any]]:
        return [
            cls._clean(relation)
            for relation in character.get("relationships", {}).get("relations", [])
            if str(relation.get("target_character_id", "")) in target_ids
        ]

    @classmethod
    def _event_memory_for(
        cls,
        chronology: list[dict[str, Any]],
        character_ids: set[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not character_ids or limit <= 0:
            return []
        matches = [
            event
            for event in chronology
            if character_ids.intersection(
                {str(item) for item in event.get("participants_present", [])}
            )
        ]
        matches.sort(
            key=lambda item: (cls._turn_number(item), str(item.get("event_id", "")))
        )
        if len(matches) <= limit:
            selected = matches
        else:
            earliest_count = min(2, limit)
            selected = matches[:earliest_count] + matches[-(limit - earliest_count) :]

        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for event in selected:
            identity = str(
                event.get("event_id")
                or f"{cls._turn_number(event)}:{event.get('scene_id', '')}:{event.get('event', '')}"
            )
            if identity in seen:
                continue
            seen.add(identity)
            result.append(cls._clean(event))
        return result

    @classmethod
    def _continuity_by_id(cls, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(item.get("character_id")): item
            for item in payload.get("character_continuity_index", [])
            if item.get("character_id")
        }

    @classmethod
    def _cast_index_entry(
        cls,
        character: dict[str, Any],
        continuity: dict[str, Any],
    ) -> dict[str, Any]:
        card = character.get("card", {})
        current_state = character.get("current_state", {})
        goals = card.get("goals", {}) if isinstance(card.get("goals"), dict) else {}
        current_goal = None
        for key in (
            "current_goal",
            "goal",
            "immediate_goal",
            "intention",
            "current_intention",
            "activity",
            "current_activity",
        ):
            if current_state.get(key) not in (None, ""):
                current_goal = deepcopy(current_state.get(key))
                break
        return {
            "character_id": character.get("character_id"),
            "name": character_display_name(card),
            "role": card.get("identity", {}).get("role"),
            "card_level": card.get("card_level"),
            "origin": card.get("origin"),
            "story_status": card.get("story_status"),
            "current_location_id": current_state.get("current_location_id"),
            "current_goal_or_activity": current_goal or goals.get("immediate"),
            "goal_toward_pov": goals.get("toward_pov"),
            "pov_familiarity": cls._clean(current_state.get("pov_familiarity")),
            "last_seen_turn": continuity.get("last_seen_turn"),
            "last_shared_scene_with_pov_turn": continuity.get(
                "last_shared_scene_with_pov_turn"
            ),
        }

    @classmethod
    def _scene_npc_lens(
        cls,
        character: dict[str, Any],
        present_ids: set[str],
        pov_character_id: str,
    ) -> dict[str, Any]:
        return {
            "character_id": character.get("character_id"),
            "name": character_display_name(character.get("card", {})),
            "causal_card": cls._causal_card(character.get("card", {})),
            "current_state": cls._clean(character.get("current_state", {})),
            "knowledge": cls._clean(character.get("knowledge", {})),
            "relationships_relevant_now": cls._relations_to_targets(
                character, present_ids | {pov_character_id}
            ),
        }

    @classmethod
    def _full_lore_entry(
        cls,
        character: dict[str, Any],
        chronology: list[dict[str, Any]],
        activation_reason: str,
    ) -> dict[str, Any]:
        character_id = str(character.get("character_id", ""))
        return {
            "activation_reason": activation_reason,
            "character": cls._clean(character),
            "relevant_character_history": cls._event_memory_for(
                chronology, {character_id}, cls.MAX_CHARACTER_EVENTS
            ),
        }

    @classmethod
    def _offscreen_score(
        cls,
        character: dict[str, Any],
        *,
        player_input: str,
        director_rows: list[dict[str, Any]],
        pov_character_id: str,
        continuity: dict[str, Any],
    ) -> int:
        card = character.get("card", {})
        score = 0
        if cls._is_mentioned(character, player_input):
            score += 1000
        if director_rows:
            score += 300
        if card.get("card_level") in {"important", "player_defined"}:
            score += 120
        elif card.get("card_level") == "recurring":
            score += 80
        if card.get("origin") == "player":
            score += 60
        if cls._relations_to_targets(character, {pov_character_id}):
            score += 90
        if character.get("current_state"):
            score += 30
        if continuity.get("last_shared_scene_with_pov_turn") is not None:
            score += 30
        status = str(card.get("story_status", ""))
        if status == "active":
            score += 50
        elif status in {"offstage", "missing"}:
            score += 35
        return score

    @classmethod
    def _build_active_memory(
        cls,
        *,
        before_state: dict[str, Any],
        payload: dict[str, Any],
        chronology: list[dict[str, Any]],
        player_input: str,
    ) -> dict[str, Any]:
        novel = before_state.get("novel", {})
        pov_character_id = str(novel.get("pov_character_id", ""))
        scene_state = before_state.get("scene_state", {})
        present_ids = {
            str(item) for item in scene_state.get("present_character_ids", []) if item
        }
        characters = [
            item
            for item in before_state.get("characters", [])
            if isinstance(item, dict) and item.get("character_id")
        ]
        by_id = {str(item.get("character_id")): item for item in characters}
        pov = by_id.get(pov_character_id)
        continuity_by_id = cls._continuity_by_id(payload)
        director_plan = before_state.get("director_plan", {})

        cast_index = [
            cls._cast_index_entry(
                character,
                continuity_by_id.get(str(character.get("character_id")), {}),
            )
            for character in characters
            if cls._character_is_durable(character)
        ]

        scene_npc_lenses = [
            cls._scene_npc_lens(character, present_ids, pov_character_id)
            for character in characters
            if str(character.get("character_id")) in present_ids
            and str(character.get("character_id")) != pov_character_id
        ]

        activated: list[dict[str, Any]] = []
        for character in characters:
            character_id = str(character.get("character_id", ""))
            if character_id in present_ids:
                continue
            if cls._is_mentioned(character, player_input):
                activated.append(
                    cls._full_lore_entry(
                        character, chronology, "mentioned_in_current_player_input"
                    )
                )
                if len(activated) >= cls.MAX_ACTIVATED_CHARACTERS:
                    break

        scored_offscreen: list[tuple[int, str, dict[str, Any], list[dict[str, Any]]]] = []
        for character in characters:
            character_id = str(character.get("character_id", ""))
            if character_id == pov_character_id or character_id in present_ids:
                continue
            if not cls._character_is_durable(character):
                continue
            card = character.get("card", {})
            status = str(card.get("story_status", ""))
            director_rows = cls._matching_director_rows(character, director_plan)
            explicitly_activated = cls._is_mentioned(character, player_input)
            if status in {"dead", "retired"} and not explicitly_activated:
                continue
            if status == "not_introduced" and not (explicitly_activated or director_rows):
                continue
            score = cls._offscreen_score(
                character,
                player_input=player_input,
                director_rows=director_rows,
                pov_character_id=pov_character_id,
                continuity=continuity_by_id.get(character_id, {}),
            )
            scored_offscreen.append((score, character_id, character, director_rows))

        scored_offscreen.sort(key=lambda item: (-item[0], item[1]))
        offscreen_pulse: list[dict[str, Any]] = []
        for score, character_id, character, director_rows in scored_offscreen[
            : cls.MAX_OFFSCREEN_PULSES
        ]:
            offscreen_pulse.append(
                {
                    "priority_score": score,
                    "character_id": character_id,
                    "name": character_display_name(character.get("card", {})),
                    "causal_card": cls._causal_card(character.get("card", {})),
                    "current_state": cls._clean(character.get("current_state", {})),
                    "knowledge": cls._clean(character.get("knowledge", {})),
                    "relationships": cls._clean(character.get("relationships", {})),
                    "director_agenda_matches": director_rows,
                    "character_history": cls._event_memory_for(
                        chronology, {character_id}, cls.MAX_CHARACTER_EVENTS
                    ),
                }
            )

        pov_memory = None
        if pov is not None:
            pov_memory = {
                "character_id": pov_character_id,
                "full_confirmed_card": cls._clean(pov.get("card", {})),
                "current_state": cls._clean(pov.get("current_state", {})),
                "knowledge": cls._clean(pov.get("knowledge", {})),
                "relationships": cls._clean(pov.get("relationships", {})),
                "long_term_story_events": cls._event_memory_for(
                    chronology, {pov_character_id}, cls.MAX_POV_EVENTS
                ),
            }

        return {
            "memory_contract": (
                "MANDATORY CAUSAL MEMORY. novel_questionnaire and pov_long_term_memory are always "
                "active canon, not optional background and not facts to postpone until a later "
                "scene. Apply them naturally whenever they affect motive, interpretation, choice, "
                "reaction or continuity; do not force exposition. For every NPC physically present, "
                "scene_npc_lenses is the required knowledge/personality/relationship lens before "
                "writing that NPC. A character may act only on their own knowledge and beliefs; do "
                "not leak hidden lore or another character's knowledge into them. cast_memory_index "
                "is the durable roster: do not forget, rename, recreate or replace an established "
                "character because they are currently offscreen. activated_lore contains complete "
                "dossiers pulled in by the current input. offscreen_cast_pulse keeps important NPCs "
                "alive outside the frame: let goals, current state, knowledge, relationships and "
                "director agendas cause plausible messages, arrivals, absences or consequences when "
                "appropriate, but never force an entrance merely because a pulse exists."
            ),
            "novel_questionnaire": cls._clean(novel),
            "pov_long_term_memory": pov_memory,
            "scene_npc_lenses": scene_npc_lenses,
            "cast_memory_index": cast_index,
            "activated_lore": activated,
            "offscreen_cast_pulse": offscreen_pulse,
        }

    def _augment_turn_packet_locked(
        self,
        session_id: str,
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            pending.get("active_lore_packet_version")
            == self.ACTIVE_LORE_PACKET_VERSION
        ):
            return self._packet_chunk_response(session_id, pending, 0)

        # First preserve every existing enhanced/recovery layer exactly as-is.
        super()._augment_turn_packet_locked(session_id, pending)

        raw = "".join(pending.get("chunks", []))
        if not raw:
            raise ServiceError(500, "TURN_PACKET_CORRUPT", "Turn packet has no content")
        payload = json.loads(raw)
        before_state = pending.get("before_state", {})
        _chronology_manifest, _parts, chronology = self._read_chronology_locked(session_id)
        chronology = self._effective_chronology(chronology)

        payload["active_memory"] = self._build_active_memory(
            before_state=before_state,
            payload=payload,
            chronology=chronology,
            player_input=str(pending.get("player_input", "")),
        )
        payload["instruction"] = (
            str(payload.get("instruction", ""))
            + " Before drafting, read active_memory.memory_contract and actually use "
            "active_memory as causal context. Questionnaire facts and established POV/NPC memory "
            "remain operative regardless of how many turns ago they were introduced. Never trade "
            "continuity for a convenient scene reset."
        ).strip()

        text = json.dumps(payload, ensure_ascii=False, indent=2)
        chunks = _split_text(text, self.settings.packet_chunk_chars)
        pending.update(
            {
                "chunks": chunks,
                "content_sha256": sha256(text.encode("utf-8")).hexdigest(),
                "last_delivered_chunk_index": 0,
                "all_chunks_delivered": len(chunks) == 1,
                "active_lore_packet_version": self.ACTIVE_LORE_PACKET_VERSION,
            }
        )
        self.storage._write_json_batch_locked(
            session_id, {"pending_turn.json": pending}
        )
        return self._packet_chunk_response(session_id, pending, 0)
