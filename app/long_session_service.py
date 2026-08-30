from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256
from typing import Any

from app.active_lore_service import ActiveLoreNovellaService
from app.character_registry import character_display_name
from app.service import ServiceError, _split_text


class LongSessionNovellaService(ActiveLoreNovellaService):
    """Keep long-running sessions fast without deleting authoritative memory.

    Railway keeps the complete questionnaire, chronology, character knowledge and old turns.
    This layer changes only the writer packet: large accumulated knowledge is projected into a
    bounded working view, while story identity and neglected cast obligations stay explicit.
    """

    LONG_SESSION_PACKET_VERSION = 1

    MAX_WORKING_KNOWLEDGE_ENTRIES = 18
    MAX_CORE_KNOWLEDGE_ENTRIES = 6
    MAX_RELEVANT_KNOWLEDGE_ENTRIES = 7
    MAX_RECENT_KNOWLEDGE_ENTRIES = 8
    MAX_OFFSCREEN_KNOWLEDGE_ENTRIES = 8

    MAX_STORY_COMPASS_FIELDS = 24
    MAX_COMPASS_VALUE_CHARS = 900

    MAX_CAST_DEBT = 10
    MAX_RESURFACING_DEBT = 10
    MAX_RESURFACING_PULSE_ADDITIONS = 2
    RESURFACE_AFTER_TURNS = 18

    _TOKEN_RE = re.compile(r"[\w-]{4,}", flags=re.UNICODE)
    _STOPWORDS = {
        "this",
        "that",
        "with",
        "from",
        "into",
        "then",
        "than",
        "have",
        "will",
        "your",
        "their",
        "there",
        "here",
        "который",
        "которая",
        "которые",
        "этого",
        "этот",
        "эта",
        "сейчас",
        "после",
        "перед",
        "только",
        "потом",
        "чтобы",
        "если",
        "когда",
        "тогда",
        "снова",
        "просто",
        "очень",
    }

    _COMPASS_KEYWORDS = (
        "genre",
        "жанр",
        "category",
        "категор",
        "tone",
        "тон",
        "style",
        "стил",
        "focus",
        "фокус",
        "center",
        "центр",
        "priority",
        "приоритет",
        "direction",
        "направ",
        "theme",
        "тем",
        "balance",
        "баланс",
        "contrast",
        "контраст",
        "premise",
        "основ",
        "главн",
        "rule",
        "правил",
        "require",
        "обяз",
        "forbid",
        "запрет",
        "thriller",
        "трил",
        "action",
        "экш",
        "romance",
        "романт",
        "supernatural",
        "сверхъест",
    )

    @classmethod
    def _tokens(cls, value: Any) -> set[str]:
        if value in (None, ""):
            return set()
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str)
        normalized = cls._normalized(value)
        return {
            token
            for token in cls._TOKEN_RE.findall(normalized)
            if token not in cls._STOPWORDS
        }

    @classmethod
    def _packet_relevance_terms(
        cls,
        *,
        before_state: dict[str, Any],
        payload: dict[str, Any],
        player_input: str,
    ) -> set[str]:
        terms = cls._tokens(player_input)
        scene_state = before_state.get("scene_state", {})
        present_ids = {
            str(item) for item in scene_state.get("present_character_ids", []) if item
        }
        for character in before_state.get("characters", []):
            character_id = str(character.get("character_id", ""))
            if character_id not in present_ids:
                continue
            terms.update(cls._tokens(character_id))
            terms.update(cls._tokens(character_display_name(character.get("card", {}))))

        location_id = scene_state.get("location_id")
        if location_id:
            terms.update(cls._tokens(str(location_id)))
            for location in before_state.get("locations", []):
                if str(location.get("location_id", "")) != str(location_id):
                    continue
                state = location.get("state", {})
                canon = state.get("canon", {}) if isinstance(state, dict) else {}
                terms.update(cls._tokens(canon.get("name")))
                break

        story_bible = payload.get("story_bible", {})
        terms.update(cls._tokens(story_bible.get("story_direction", {})))
        return terms

    @classmethod
    def _knowledge_core_score(cls, entry: Any) -> int:
        if not isinstance(entry, dict):
            return 0
        score = 0
        for key in (
            "pinned",
            "is_pinned",
            "core",
            "permanent",
            "anchor",
            "must_remember",
            "critical",
        ):
            if entry.get(key) is True:
                score += 500

        source = cls._normalized(entry.get("source"))
        if any(
            marker in source
            for marker in (
                "confirmed",
                "setup",
                "questionnaire",
                "player",
                "canon",
                "intake",
            )
        ):
            score += 180

        importance = cls._normalized(
            " ".join(
                str(entry.get(key, ""))
                for key in ("importance", "priority", "tier", "status", "tags")
            )
        )
        if any(
            marker in importance
            for marker in (
                "critical",
                "core",
                "pinned",
                "anchor",
                "permanent",
                "essential",
                "важн",
                "ключев",
                "обязательн",
                "якор",
            )
        ):
            score += 300
        return score

    @classmethod
    def _knowledge_relevance_score(
        cls, entry: Any, relevance_terms: set[str]
    ) -> int:
        if not relevance_terms:
            return 0
        text = cls._normalized(json.dumps(entry, ensure_ascii=False, default=str))
        return sum(1 for term in relevance_terms if term and term in text)

    @classmethod
    def _working_knowledge(
        cls,
        knowledge: Any,
        *,
        relevance_terms: set[str],
        limit: int | None = None,
    ) -> Any:
        cleaned = cls._clean(knowledge)
        if not isinstance(cleaned, dict):
            return cleaned

        entries = cleaned.get("entries")
        if not isinstance(entries, list):
            return cleaned

        limit = max(int(limit or cls.MAX_WORKING_KNOWLEDGE_ENTRIES), 1)
        total = len(entries)
        if total <= limit:
            result = deepcopy(cleaned)
            result["_working_view"] = {
                "complete": True,
                "total_entries": total,
                "included_entries": total,
                "omitted_entries": 0,
                "authoritative_source": "Railway character knowledge",
            }
            return result

        indexed = list(enumerate(entries))
        selected_indices: set[int] = set()

        core_ranked: list[tuple[int, int]] = []
        relevant_ranked: list[tuple[int, int]] = []
        for index, entry in indexed:
            core_score = cls._knowledge_core_score(entry)
            if core_score > 0:
                core_ranked.append((core_score, index))
            relevant_score = cls._knowledge_relevance_score(entry, relevance_terms)
            if relevant_score > 0:
                relevant_ranked.append((relevant_score, index))

        core_ranked.sort(key=lambda item: (-item[0], item[1]))
        for _score, index in core_ranked[: cls.MAX_CORE_KNOWLEDGE_ENTRIES]:
            selected_indices.add(index)

        relevant_ranked.sort(key=lambda item: (-item[0], -item[1]))
        relevant_added = 0
        for _score, index in relevant_ranked:
            if len(selected_indices) >= limit:
                break
            if index in selected_indices:
                continue
            selected_indices.add(index)
            relevant_added += 1
            if relevant_added >= cls.MAX_RELEVANT_KNOWLEDGE_ENTRIES:
                break

        recent_added = 0
        for index in range(total - 1, -1, -1):
            if len(selected_indices) >= limit:
                break
            if index in selected_indices:
                continue
            selected_indices.add(index)
            recent_added += 1
            if recent_added >= cls.MAX_RECENT_KNOWLEDGE_ENTRIES:
                break

        if len(selected_indices) < limit:
            for index in range(total - 1, -1, -1):
                if len(selected_indices) >= limit:
                    break
                selected_indices.add(index)

        ordered_indices = sorted(selected_indices)
        result = deepcopy(cleaned)
        result["entries"] = [entries[index] for index in ordered_indices]
        result["_working_view"] = {
            "complete": False,
            "total_entries": total,
            "included_entries": len(ordered_indices),
            "omitted_entries": total - len(ordered_indices),
            "selection": "pinned/core + scene-relevant + recent",
            "authoritative_source": "Railway character knowledge",
            "instruction": (
                "This is a writer projection, not the complete memory. Omitted entries still exist "
                "in Railway canon and must not be treated as forgotten, false or nonexistent."
            ),
        }
        return result

    @classmethod
    def _compass_value(cls, value: Any) -> Any:
        if isinstance(value, str):
            if len(value) <= cls.MAX_COMPASS_VALUE_CHARS:
                return value
            return value[: cls.MAX_COMPASS_VALUE_CHARS] + "…"
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, list) and all(
            isinstance(item, (str, int, float, bool)) or item is None for item in value
        ):
            return [cls._compass_value(item) for item in value[:20]]
        return None

    @classmethod
    def _story_compass_fields(cls, novel: dict[str, Any]) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []

        def walk(value: Any, path: tuple[str, ...], inherited_match: bool = False) -> None:
            if len(fields) >= cls.MAX_STORY_COMPASS_FIELDS:
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    if len(fields) >= cls.MAX_STORY_COMPASS_FIELDS:
                        return
                    key_text = cls._normalized(key)
                    matched = inherited_match or any(
                        marker in key_text for marker in cls._COMPASS_KEYWORDS
                    )
                    walk(child, (*path, str(key)), matched)
                return

            projected = cls._compass_value(value)
            if not inherited_match or projected is None:
                return
            fields.append({"path": ".".join(path), "value": projected})

        walk(novel, ())
        return fields

    @classmethod
    def _story_compass(
        cls, novel: dict[str, Any], *, current_turn: int
    ) -> dict[str, Any]:
        fields = cls._story_compass_fields(novel)
        genre_fields = [
            item
            for item in fields
            if any(
                marker in cls._normalized(item.get("path"))
                for marker in ("genre", "жанр", "category", "категор")
            )
        ]
        return {
            "source_path": "story_bible.novel",
            "current_turn": current_turn,
            "declared_genre_fields": genre_fields,
            "directional_questionnaire_fields": fields,
            "instruction": (
                "Treat the questionnaire as the identity of the whole novel, not as old setup text. "
                "Every declared genre remains live throughout a long session. Recent romantic scenes "
                "must not silently turn a romance+thriller+action+supernatural story into romance-only. "
                "Use natural opportunities to rotate neglected genre pressure, active threats, "
                "mysteries, action consequences and supernatural threads without forcing a random beat "
                "into every scene. Preserve the user's exact priorities and prohibitions from "
                "story_bible.novel."
            ),
        }

    @classmethod
    def _compact_current_state_for_debt(cls, current_state: Any) -> dict[str, Any]:
        if not isinstance(current_state, dict):
            return {}
        keep = (
            "current_location_id",
            "current_activity",
            "activity",
            "current_goal",
            "goal",
            "immediate_goal",
            "intention",
            "current_intention",
            "availability",
            "condition",
            "status",
            "pov_familiarity",
        )
        return cls._clean(
            {key: current_state.get(key) for key in keep if key in current_state}
        )

    @classmethod
    def _cast_debt(
        cls,
        *,
        before_state: dict[str, Any],
        payload: dict[str, Any],
        continuity_by_id: dict[str, dict[str, Any]],
        pov_character_id: str,
    ) -> list[dict[str, Any]]:
        current_turn = int(payload.get("turn_number") or 1)
        director_plan = before_state.get("director_plan", {})
        rows: list[tuple[int, str, dict[str, Any]]] = []

        for character in before_state.get("characters", []):
            if not isinstance(character, dict):
                continue
            character_id = str(character.get("character_id", ""))
            if not character_id or character_id == pov_character_id:
                continue
            if not cls._character_is_durable(character):
                continue

            card = character.get("card", {})
            status = cls._normalized(card.get("story_status"))
            continuity = continuity_by_id.get(character_id, {})
            first_seen = continuity.get("first_seen_turn")
            never_seen = first_seen is None
            if status in {"dead", "retired"}:
                continue
            if status != "not_introduced" and not never_seen:
                continue

            director_rows = cls._matching_director_rows(character, director_plan)
            level = str(card.get("card_level", ""))
            score = {
                "player_defined": 500,
                "important": 420,
                "recurring": 280,
            }.get(level, 150)
            if card.get("origin") == "player":
                score += 180
            if director_rows:
                score += 180
            score += min(max(current_turn - 1, 0), 250)

            goals = card.get("goals", {}) if isinstance(card.get("goals"), dict) else {}
            rows.append(
                (
                    score,
                    character_id,
                    {
                        "priority_score": score,
                        "character_id": character_id,
                        "name": character_display_name(card),
                        "role": card.get("identity", {}).get("role"),
                        "card_level": card.get("card_level"),
                        "origin": card.get("origin"),
                        "story_status": card.get("story_status"),
                        "first_seen_turn": first_seen,
                        "unintroduced_for_turns": max(current_turn - 1, 0),
                        "card_hint": card.get("card_hint"),
                        "immediate_scene_goal": card.get("immediate_scene_goal")
                        or goals.get("immediate"),
                        "current_state": cls._compact_current_state_for_debt(
                            character.get("current_state", {})
                        ),
                        "director_agenda_matches": director_rows,
                        "instruction": (
                            "This is an introduction debt, not an order to teleport the character "
                            "into the current scene. Keep them in director awareness and create a "
                            "plausible entrance window when story causality allows it."
                        ),
                    },
                )
            )

        rows.sort(key=lambda item: (-item[0], item[1]))
        return [entry for _score, _character_id, entry in rows[: cls.MAX_CAST_DEBT]]

    @classmethod
    def _resurfacing_debt(
        cls,
        *,
        before_state: dict[str, Any],
        payload: dict[str, Any],
        continuity_by_id: dict[str, dict[str, Any]],
        pov_character_id: str,
    ) -> list[dict[str, Any]]:
        current_turn = int(payload.get("turn_number") or 1)
        present_ids = {
            str(item)
            for item in before_state.get("scene_state", {}).get(
                "present_character_ids", []
            )
            if item
        }
        director_plan = before_state.get("director_plan", {})
        rows: list[tuple[int, str, dict[str, Any]]] = []

        for character in before_state.get("characters", []):
            if not isinstance(character, dict):
                continue
            character_id = str(character.get("character_id", ""))
            if (
                not character_id
                or character_id == pov_character_id
                or character_id in present_ids
            ):
                continue
            if not cls._character_is_durable(character):
                continue

            card = character.get("card", {})
            status = cls._normalized(card.get("story_status"))
            if status in {"dead", "retired", "not_introduced"}:
                continue

            continuity = continuity_by_id.get(character_id, {})
            first_seen = continuity.get("first_seen_turn")
            last_seen = continuity.get("last_seen_turn")
            if first_seen is None:
                continue
            try:
                gap = max(current_turn - int(last_seen or first_seen), 0)
            except (TypeError, ValueError):
                gap = 0
            if gap < cls.RESURFACE_AFTER_TURNS:
                continue

            director_rows = cls._matching_director_rows(character, director_plan)
            level = str(card.get("card_level", ""))
            score = gap + {
                "player_defined": 220,
                "important": 180,
                "recurring": 120,
            }.get(level, 60)
            if card.get("origin") == "player":
                score += 80
            if director_rows:
                score += 200
            if cls._relations_to_targets(character, {pov_character_id}):
                score += 70

            goals = card.get("goals", {}) if isinstance(card.get("goals"), dict) else {}
            rows.append(
                (
                    score,
                    character_id,
                    {
                        "priority_score": score,
                        "character_id": character_id,
                        "name": character_display_name(card),
                        "role": card.get("identity", {}).get("role"),
                        "card_level": card.get("card_level"),
                        "story_status": card.get("story_status"),
                        "last_seen_turn": last_seen,
                        "turns_since_seen": gap,
                        "current_state": cls._compact_current_state_for_debt(
                            character.get("current_state", {})
                        ),
                        "current_goal_or_activity": (
                            character.get("current_state", {}).get("current_goal")
                            or character.get("current_state", {}).get("current_activity")
                            or goals.get("immediate")
                        ),
                        "goal_toward_pov": goals.get("toward_pov"),
                        "relationship_to_pov": cls._relations_to_targets(
                            character, {pov_character_id}
                        ),
                        "director_agenda_matches": director_rows,
                        "instruction": (
                            "Long absence increases director attention, not POV knowledge and not a "
                            "mandatory cameo. Resurface through a plausible message, consequence, "
                            "meeting, report, conflict or arrival when causal conditions fit."
                        ),
                    },
                )
            )

        rows.sort(key=lambda item: (-item[0], item[1]))
        return [
            entry for _score, _character_id, entry in rows[: cls.MAX_RESURFACING_DEBT]
        ]

    @classmethod
    def _inject_resurfacing_pulses(
        cls,
        *,
        memory: dict[str, Any],
        resurfacing_debt: list[dict[str, Any]],
        before_state: dict[str, Any],
        chronology: list[dict[str, Any]],
        pov_character_id: str,
        relevance_terms: set[str],
    ) -> None:
        pulse = list(memory.get("offscreen_cast_pulse", []))
        existing_ids = {
            str(item.get("character_id", ""))
            for item in pulse
            if isinstance(item, dict)
        }
        by_id = {
            str(item.get("character_id", "")): item
            for item in before_state.get("characters", [])
            if isinstance(item, dict) and item.get("character_id")
        }
        director_plan = before_state.get("director_plan", {})
        additions = 0

        for debt in resurfacing_debt:
            if additions >= cls.MAX_RESURFACING_PULSE_ADDITIONS:
                break
            character_id = str(debt.get("character_id", ""))
            if not character_id or character_id in existing_ids:
                continue
            character = by_id.get(character_id)
            if not character:
                continue
            director_rows = cls._matching_director_rows(character, director_plan)
            entry = cls._offscreen_pulse_entry(
                character,
                score=int(debt.get("priority_score") or 0),
                director_rows=director_rows,
                pov_character_id=pov_character_id,
                chronology=chronology,
            )
            entry["knowledge_snapshot"] = cls._working_knowledge(
                entry.get("knowledge_snapshot", {}),
                relevance_terms=relevance_terms,
                limit=cls.MAX_OFFSCREEN_KNOWLEDGE_ENTRIES,
            )
            entry["resurfacing_debt"] = {
                "turns_since_seen": debt.get("turns_since_seen"),
                "last_seen_turn": debt.get("last_seen_turn"),
            }
            pulse.append(entry)
            existing_ids.add(character_id)
            additions += 1

        memory["offscreen_cast_pulse"] = pulse

    @classmethod
    def _build_active_memory(
        cls,
        *,
        before_state: dict[str, Any],
        payload: dict[str, Any],
        chronology: list[dict[str, Any]],
        player_input: str,
    ) -> dict[str, Any]:
        memory = super()._build_active_memory(
            before_state=before_state,
            payload=payload,
            chronology=chronology,
            player_input=player_input,
        )
        novel = before_state.get("novel", {})
        pov_character_id = str(novel.get("pov_character_id", ""))
        continuity_by_id = cls._continuity_by_id(payload)
        relevance_terms = cls._packet_relevance_terms(
            before_state=before_state,
            payload=payload,
            player_input=player_input,
        )
        current_turn = int(payload.get("turn_number") or 1)

        pov_memory = memory.get("pov_long_term_memory")
        if isinstance(pov_memory, dict):
            pov_memory["knowledge"] = cls._working_knowledge(
                pov_memory.get("knowledge", {}),
                relevance_terms=relevance_terms,
            )

        for lens in memory.get("scene_npc_lenses", []):
            if isinstance(lens, dict):
                lens["knowledge"] = cls._working_knowledge(
                    lens.get("knowledge", {}),
                    relevance_terms=relevance_terms,
                )

        for activated in memory.get("activated_lore", []):
            if not isinstance(activated, dict):
                continue
            character = activated.get("character")
            if isinstance(character, dict):
                character["knowledge"] = cls._working_knowledge(
                    character.get("knowledge", {}),
                    relevance_terms=relevance_terms,
                )
                activated["full_knowledge_source"] = (
                    "Railway character dossier; the packet carries a bounded working view."
                )

        for pulse in memory.get("offscreen_cast_pulse", []):
            if isinstance(pulse, dict):
                pulse["knowledge_snapshot"] = cls._working_knowledge(
                    pulse.get("knowledge_snapshot", {}),
                    relevance_terms=relevance_terms,
                    limit=cls.MAX_OFFSCREEN_KNOWLEDGE_ENTRIES,
                )

        cast_debt = cls._cast_debt(
            before_state=before_state,
            payload=payload,
            continuity_by_id=continuity_by_id,
            pov_character_id=pov_character_id,
        )
        resurfacing_debt = cls._resurfacing_debt(
            before_state=before_state,
            payload=payload,
            continuity_by_id=continuity_by_id,
            pov_character_id=pov_character_id,
        )

        cls._inject_resurfacing_pulses(
            memory=memory,
            resurfacing_debt=resurfacing_debt,
            before_state=before_state,
            chronology=chronology,
            pov_character_id=pov_character_id,
            relevance_terms=relevance_terms,
        )

        memory["story_compass"] = cls._story_compass(
            novel, current_turn=current_turn
        )
        memory["cast_debt"] = cast_debt
        memory["resurfacing_debt"] = resurfacing_debt
        memory["memory_contract"] = (
            str(memory.get("memory_contract", ""))
            + " LONG-SESSION CONTRACT. story_compass is mandatory director context: the whole "
            "declared genre mix and questionnaire priorities remain active even after hundreds of "
            "turns. cast_debt keeps important not-yet-introduced characters visible to the director; "
            "resurfacing_debt keeps established important characters from disappearing merely because "
            "recent scenes focused elsewhere. Neither debt forces an implausible entrance. "
            "Knowledge blocks may be bounded working views. Omission from a working view is never "
            "deletion, ignorance or a retcon; complete memory remains authoritative in Railway."
        ).strip()
        return memory

    @classmethod
    def _compact_packet_character_knowledge(
        cls,
        payload: dict[str, Any],
        *,
        relevance_terms: set[str],
    ) -> None:
        state = payload.get("state", {})
        if isinstance(state, dict):
            for character in state.get("characters", []):
                if isinstance(character, dict) and "knowledge" in character:
                    character["knowledge"] = cls._working_knowledge(
                        character.get("knowledge", {}),
                        relevance_terms=relevance_terms,
                    )

    @classmethod
    def _context_manifest(
        cls,
        *,
        payload: dict[str, Any],
        before_state: dict[str, Any],
        pre_compaction_chunk_count: int,
    ) -> dict[str, Any]:
        memory = payload.get("active_memory", {})
        total_knowledge_entries = 0
        for character in before_state.get("characters", []):
            entries = (
                character.get("knowledge", {}).get("entries", [])
                if isinstance(character, dict)
                and isinstance(character.get("knowledge"), dict)
                else []
            )
            if isinstance(entries, list):
                total_knowledge_entries += len(entries)
        return {
            "version": cls.LONG_SESSION_PACKET_VERSION,
            "policy": "preserve full canon in Railway; send bounded writer projections",
            "authoritative_data_deleted": False,
            "pre_compaction_chunk_count": pre_compaction_chunk_count,
            "stored_character_knowledge_entries": total_knowledge_entries,
            "working_knowledge_entry_cap_per_loaded_character": (
                cls.MAX_WORKING_KNOWLEDGE_ENTRIES
            ),
            "cast_debt_count": len(memory.get("cast_debt", []))
            if isinstance(memory, dict)
            else 0,
            "resurfacing_debt_count": len(memory.get("resurfacing_debt", []))
            if isinstance(memory, dict)
            else 0,
        }

    def _augment_turn_packet_locked(
        self,
        session_id: str,
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            pending.get("long_session_packet_version")
            == self.LONG_SESSION_PACKET_VERSION
        ):
            return self._packet_chunk_response(session_id, pending, 0)

        super()._augment_turn_packet_locked(session_id, pending)

        raw = "".join(pending.get("chunks", []))
        if not raw:
            raise ServiceError(500, "TURN_PACKET_CORRUPT", "Turn packet has no content")
        payload = json.loads(raw)
        before_state = pending.get("before_state", {})
        _chronology_manifest, _parts, chronology = self._read_chronology_locked(session_id)
        chronology = self._effective_chronology(chronology)
        pre_compaction_chunk_count = len(pending.get("chunks", []))

        payload["active_memory"] = self._build_active_memory(
            before_state=before_state,
            payload=payload,
            chronology=chronology,
            player_input=str(pending.get("player_input", "")),
        )
        relevance_terms = self._packet_relevance_terms(
            before_state=before_state,
            payload=payload,
            player_input=str(pending.get("player_input", "")),
        )
        self._compact_packet_character_knowledge(
            payload,
            relevance_terms=relevance_terms,
        )
        payload["context_manifest"] = self._context_manifest(
            payload=payload,
            before_state=before_state,
            pre_compaction_chunk_count=pre_compaction_chunk_count,
        )
        payload["instruction"] = (
            str(payload.get("instruction", ""))
            + " For long sessions, read active_memory.story_compass before choosing scene pressure. "
            "Check cast_debt and resurfacing_debt before defaulting to the same recently dominant "
            "characters or genre. Use working knowledge as a retrieval view only: do not contradict "
            "older canon just because an entry is omitted from this packet."
        ).strip()

        text = json.dumps(payload, ensure_ascii=False, indent=2)
        chunks = _split_text(text, self.settings.packet_chunk_chars)
        pending.update(
            {
                "chunks": chunks,
                "content_sha256": sha256(text.encode("utf-8")).hexdigest(),
                "last_delivered_chunk_index": 0,
                "all_chunks_delivered": len(chunks) == 1,
                "long_session_packet_version": self.LONG_SESSION_PACKET_VERSION,
                "pre_compaction_chunk_count": pre_compaction_chunk_count,
                "post_compaction_chunk_count": len(chunks),
            }
        )
        self.storage._write_json_batch_locked(
            session_id, {"pending_turn.json": pending}
        )
        return self._packet_chunk_response(session_id, pending, 0)
