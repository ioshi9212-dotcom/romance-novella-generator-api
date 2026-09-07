from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from typing import Any

from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.service import NovellaService, ServiceError, _new_id, _split_text


class FastAuditNovellaService(EnhancedWriterNovellaService):
    """Keep turn memory compact while preserving important cast continuity.

    The model already has the 15 visible turns in the current chat. Railway therefore sends
    only a compact audit snapshot of what is already persisted, and turn packets additionally
    surface a small set of relevant offstage cast candidates without loading their full dossiers.
    """

    FAST_AUDIT_VERSION = 2
    CAST_CONTEXT_VERSION = 1
    CAST_CANDIDATE_LIMIT = 8
    CHRONOLOGY_SKIP_SENTINEL = "__NO_CHRONOLOGY_EVENT__"

    @staticmethod
    def _clip_text(value: Any, limit: int = 600) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: max(limit - 1, 1)].rstrip() + "…"

    @classmethod
    def _compact_list(
        cls,
        value: Any,
        *,
        max_items: int = 5,
        item_limit: int = 350,
    ) -> list[Any]:
        if not isinstance(value, list):
            return []
        result: list[Any] = []
        for item in value[:max_items]:
            if isinstance(item, str):
                result.append(cls._clip_text(item, item_limit))
            elif isinstance(item, dict):
                result.append(cls._compact_mapping(item, max_items=6, text_limit=item_limit))
            else:
                result.append(deepcopy(item))
        return result

    @classmethod
    def _compact_mapping(
        cls,
        value: Any,
        *,
        max_items: int = 12,
        text_limit: int = 500,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        preferred = (
            "current_location_id",
            "location_id",
            "location",
            "current_goal",
            "goal",
            "immediate_goal",
            "intention",
            "activity",
            "condition",
            "mood",
            "availability",
            "schedule",
            "status",
            "pov_familiarity",
        )
        ordered_keys = [key for key in preferred if key in value]
        ordered_keys.extend(key for key in value if key not in ordered_keys)
        result: dict[str, Any] = {}
        for key in ordered_keys[:max_items]:
            item = value[key]
            if isinstance(item, str):
                result[key] = cls._clip_text(item, text_limit)
            elif isinstance(item, list):
                result[key] = cls._compact_list(
                    item, max_items=5, item_limit=min(text_limit, 350)
                )
            elif isinstance(item, dict):
                result[key] = cls._compact_mapping(
                    item, max_items=8, text_limit=min(text_limit, 350)
                )
            else:
                result[key] = deepcopy(item)
        return result

    @classmethod
    def _relation_to_pov(
        cls,
        character: dict[str, Any],
        pov_character_id: str,
    ) -> dict[str, Any] | None:
        for relation in character.get("relationships", {}).get("relations", []):
            if str(relation.get("target_character_id", "")) != pov_character_id:
                continue
            return {
                "relationship_type": cls._clip_text(
                    relation.get("relationship_type"), 300
                ),
                "current_dynamic": cls._clip_text(
                    relation.get("current_dynamic"), 650
                ),
                "dimensions": cls._compact_list(
                    relation.get("dimensions", []), max_items=8, item_limit=250
                ),
                "beliefs_about_pov": cls._compact_list(
                    relation.get("beliefs_about_target", []), max_items=4
                ),
                "unresolved_with_pov": cls._compact_list(
                    relation.get("unresolved_between_them", []), max_items=4
                ),
                "dynamic_constraints": cls._compact_list(
                    relation.get("dynamic_constraints", []), max_items=4
                ),
            }
        return None

    @classmethod
    def _compact_cast_candidate(
        cls,
        character: dict[str, Any],
        *,
        pov_character_id: str,
        last_seen_turn: int | None,
        history_end: int,
        active_story_reference: bool,
        relevance_score: int,
    ) -> dict[str, Any]:
        card = character.get("card", {})
        identity = card.get("identity", {})
        personality = card.get("personality") or {}
        preferences = card.get("preferences") or {}
        goals = card.get("goals") or {}
        absence = None if last_seen_turn is None else max(history_end - last_seen_turn, 0)
        return {
            "character_id": character.get("character_id"),
            "name": identity.get("name"),
            "card_level": card.get("card_level"),
            "story_status": card.get("story_status"),
            "role": cls._clip_text(identity.get("role"), 350),
            "card_hint": cls._clip_text(card.get("card_hint"), 650),
            "last_seen_turn": last_seen_turn,
            "turns_since_seen": absence,
            "never_seen": last_seen_turn is None,
            "active_story_reference": active_story_reference,
            "relevance_score": relevance_score,
            "personality": {
                "outward_mask": cls._clip_text(personality.get("outward_mask"), 500),
                "inner_character": cls._clip_text(personality.get("inner_character"), 650),
                "temperament": cls._clip_text(personality.get("temperament"), 350),
                "speech": cls._clip_text(personality.get("speech"), 500),
            },
            "preferences": {
                "likes": cls._compact_list(preferences.get("likes", []), max_items=4),
                "dislikes": cls._compact_list(preferences.get("dislikes", []), max_items=4),
                "likes_in_people": cls._compact_list(
                    preferences.get("likes_in_people", []), max_items=4
                ),
                "dislikes_in_people": cls._compact_list(
                    preferences.get("dislikes_in_people", []), max_items=4
                ),
            },
            "goals": {
                "personal": cls._clip_text(goals.get("personal"), 650),
                "immediate": cls._clip_text(goals.get("immediate"), 500),
                "toward_pov": cls._clip_text(goals.get("toward_pov"), 500),
                "story_function": cls._clip_text(goals.get("story_function"), 650),
                "possible_arc": cls._clip_text(goals.get("possible_arc"), 650),
            },
            "biography": cls._compact_list(card.get("biography", []), max_items=4),
            "constraints": cls._compact_list(card.get("constraints", []), max_items=5),
            "current_state": cls._compact_mapping(character.get("current_state", {})),
            "relationship_to_pov": cls._relation_to_pov(
                character, pov_character_id
            ),
        }

    @classmethod
    def _cast_candidate_context(
        cls,
        before_state: dict[str, Any],
        payload: dict[str, Any],
        *,
        history_end: int,
    ) -> dict[str, Any]:
        scene_state = before_state.get("scene_state", {})
        present_ids = {
            str(item) for item in scene_state.get("present_character_ids", []) if item
        }
        pov_character_id = str(before_state.get("novel", {}).get("pov_character_id", ""))
        continuity = {
            str(item.get("character_id")): item
            for item in payload.get("character_continuity_index", [])
            if item.get("character_id")
        }
        reference_payload = {
            "active_plot": payload.get("story_bible", {}).get("active_plot", {}),
            "story_direction": payload.get("story_bible", {}).get("story_direction", {}),
            "player_input": payload.get("player_input", ""),
        }
        reference_text = json.dumps(
            reference_payload, ensure_ascii=False, default=str
        ).casefold()
        base_scores = {"important": 55, "player_defined": 50, "recurring": 38}
        candidates: list[tuple[int, dict[str, Any]]] = []

        for character in before_state.get("characters", []):
            character_id = str(character.get("character_id", ""))
            if not character_id or character_id == pov_character_id or character_id in present_ids:
                continue
            card = character.get("card", {})
            if card.get("record_status") != "active":
                continue
            level = str(card.get("card_level", ""))
            if level not in base_scores:
                continue
            story_status = str(card.get("story_status", ""))
            if story_status in {"dead", "retired"}:
                continue

            name = str(card.get("identity", {}).get("name", "")).strip()
            active_reference = bool(
                character_id.casefold() in reference_text
                or (name and name.casefold() in reference_text)
            )
            if story_status == "not_introduced" and not active_reference:
                continue

            continuity_item = continuity.get(character_id, {})
            raw_last_seen = continuity_item.get("last_seen_turn")
            try:
                last_seen = int(raw_last_seen) if raw_last_seen is not None else None
            except (TypeError, ValueError):
                last_seen = None
            absence = history_end + 1 if last_seen is None else max(history_end - last_seen, 0)

            score = base_scores[level]
            if active_reference:
                score += 45
            if story_status == "active":
                score += 12
            elif story_status == "offstage":
                score += 8
            elif story_status == "missing":
                score += 4
            score += min(absence, 20)
            if card.get("origin") == "player":
                score += 4

            candidates.append(
                (
                    score,
                    cls._compact_cast_candidate(
                        character,
                        pov_character_id=pov_character_id,
                        last_seen_turn=last_seen,
                        history_end=history_end,
                        active_story_reference=active_reference,
                        relevance_score=score,
                    ),
                )
            )

        candidates.sort(
            key=lambda item: (
                item[0],
                item[1].get("turns_since_seen") or 0,
                str(item[1].get("name", "")),
            ),
            reverse=True,
        )
        selected = [item for _score, item in candidates[: cls.CAST_CANDIDATE_LIMIT]]
        return {
            "candidates": selected,
            "candidate_count": len(selected),
            "instruction": (
                "These are relevant offstage cast candidates, not mandatory cameos. Before choosing "
                "who can naturally initiate contact, re-enter, interrupt, call, message or affect the "
                "next beat, use their personality, goals, current_state, relationship_to_pov and "
                "story function. Do not rotate characters mechanically and do not reveal a hidden "
                "future character early merely because they are listed. If a listed known character "
                "will physically enter the scene, load their full scene-character bundle before "
                "using them. Important/recurring characters with unresolved goals should not silently "
                "disappear for many turns without an offscreen reason, consequence or closed arc."
            ),
        }

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

    def _augment_turn_packet_locked(
        self,
        session_id: str,
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        if pending.get("cast_context_version") == self.CAST_CONTEXT_VERSION:
            return self._packet_chunk_response(session_id, pending, 0)

        super()._augment_turn_packet_locked(session_id, pending)
        raw = "".join(pending.get("chunks", []))
        if not raw:
            raise ServiceError(500, "TURN_PACKET_CORRUPT", "Turn packet has no content")
        payload = json.loads(raw)
        before_state = pending.get("before_state", {})
        history_end = max(int(pending.get("turn_number", 1)) - 1, 0)
        payload["offstage_cast_context"] = self._cast_candidate_context(
            before_state,
            payload,
            history_end=history_end,
        )
        payload["chronology_policy"] = {
            "skip_event_sentinel": self.CHRONOLOGY_SKIP_SENTINEL,
            "instruction": (
                "Chronology stores durable canon, not a minute-by-minute activity log. Record only "
                "facts that future scenes may need: decisions, promises, conflicts, discoveries, "
                "reveals, relationship changes, meaningful conversations, consequential movement, "
                "injury, acquisition/loss of important objects, agreements, deadlines and other "
                "story consequences. Routine eating, showering, dressing, smoking, sleeping, waking, "
                "ordinary commuting and similar self-care are not chronology events unless they "
                "cause or reveal something important. Group related facts compactly instead of one "
                "event per action. The transport schema still requires at least one events item; if "
                "this turn establishes no chronology-worthy fact, send exactly one placeholder event "
                "whose event text is __NO_CHRONOLOGY_EVENT__. Railway removes that placeholder before "
                "persistence, so the turn may correctly create zero chronology events."
            ),
        }
        payload["instruction"] = (
            str(payload.get("instruction", ""))
            + " Apply chronology_policy strictly: never invent a trivial chronology fact merely to "
            "satisfy the commit envelope. Use offstage_cast_context before deciding which established "
            "NPC may naturally matter in the next beat; their questionnaire data is causal context, "
            "not decoration."
        ).strip()

        text = json.dumps(payload, ensure_ascii=False, indent=2)
        chunks = _split_text(text, self.settings.packet_chunk_chars)
        pending.update(
            {
                "chunks": chunks,
                "content_sha256": sha256(text.encode("utf-8")).hexdigest(),
                "last_delivered_chunk_index": 0,
                "all_chunks_delivered": len(chunks) == 1,
                "cast_context_version": self.CAST_CONTEXT_VERSION,
            }
        )
        self.storage._write_json_batch_locked(
            session_id, {"pending_turn.json": pending}
        )
        return self._packet_chunk_response(session_id, pending, 0)

    def get_audit_packet(self, session_id: str) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            session = self._require_session(session_id)
            pending = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )

            # Replace an old packet created by a previous fast-audit contract version.
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
            pov_character_id = str(state.get("novel", {}).get("pov_character_id", ""))
            continuity_index = self._character_continuity_index_locked(
                session_id,
                before_state=state,
                chronology=chronology,
                pov_character_id=pov_character_id or None,
                history_end=turn_to,
            )
            cast_audit_context = self._cast_candidate_context(
                state,
                {
                    "character_continuity_index": continuity_index,
                    "story_bible": {
                        "active_plot": self._clean(state.get("plot_state", {})),
                        "story_direction": self._active_story_direction(
                            state.get("director_plan", {})
                        ),
                    },
                    "player_input": "",
                },
                history_end=turn_to,
            )

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
                "cast_continuity_audit": {
                    **cast_audit_context,
                    "instruction": (
                        "Review these offstage active cast members only as a continuity signal. Do "
                        "not force a cameo just to rotate the cast. If an important/recurring/player-"
                        "defined character has unresolved goals or active plot relevance but has been "
                        "absent for many turns, make sure the persisted state/director plan still "
                        "contains a concrete offscreen goal, consequence, contact window or reason for "
                        "absence. If their function is actually finished, close/retire that line "
                        "explicitly instead of silently forgetting the character."
                    ),
                },
                "audit_targets": audit_targets,
                "instruction": (
                    "FAST AUDIT. The 15 committed scenes are already visible in the current chat; "
                    "do not reread full scenes from Railway and do not perform multi-pass analysis. "
                    "Make one quick comparison of those visible 15 turns against this persisted "
                    "snapshot. Check only: (1) missing important chronology events, (2) missing or "
                    "unsupported character knowledge/relationship memory, (3) obvious current state "
                    "contradictions with the latest scene, and (4) cast_continuity_audit for important "
                    "active NPCs that may have been silently dropped. Add only missing/corrective data. "
                    "Do not re-audit hidden lore, locations, card promotion or minor NPC lifecycle "
                    "unless an obvious contradiction is visible in these 15 turns. Do not compact "
                    "chronology by default. Exception: if this cycle contains multiple legacy routine-"
                    "only entries such as eating, showering or sleeping with no story consequence, "
                    "they may be compacted into one short daypart-level summary while preserving every "
                    "meaningful conversation, decision, reveal and consequence. After this single pass "
                    "call commitAudit immediately. For backward-compatible request schema, set every "
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

    def commit_turn(self, session_id: str, request: Any) -> dict[str, Any]:
        filtered_events = []
        for event in request.events:
            if str(event.event).strip() != self.CHRONOLOGY_SKIP_SENTINEL:
                filtered_events.append(event)
                continue
            if (
                event.consequences
                or event.knowledge_update_refs
                or event.minor_npcs
                or event.supersedes_event_id
            ):
                raise ServiceError(
                    422,
                    "CHRONOLOGY_SENTINEL_HAS_DATA",
                    "The no-chronology sentinel cannot carry consequences, knowledge refs, minor NPCs or supersedes data",
                )
        clean_request = request.model_copy(
            update={"events": filtered_events},
            deep=True,
        )
        return super().commit_turn(session_id, clean_request)

    def commit_audit(self, session_id: str, request: Any) -> dict[str, Any]:
        """Use the stable base commit path, skipping legacy exhaustive evidence gates."""
        return NovellaService.commit_audit(self, session_id, request)
