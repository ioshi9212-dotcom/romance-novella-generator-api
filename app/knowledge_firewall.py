from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

from app.service import ServiceError


# These labels intentionally accept both English and common legacy values already used by
# generated sessions. New writes are normalized by the runtime but old state is never rewritten
# merely because the vocabulary changed.
DIRECT_ACQUISITION_TYPES = {
    "observed",
    "seen",
    "heard",
    "overheard",
    "witnessed",
    "told_directly",
    "read_in_scene",
    "discovered",
    "found",
    "noticed",
    "personally_observed",
    "personally_heard",
}
REMOTE_ACQUISITION_TYPES = {
    "received_message",
    "text_message",
    "phone_call",
    "voice_message",
    "email",
    "remote_report",
    "reported_by",
    "told_indirectly",
    "offscreen_report",
}
INFERENCE_ACQUISITION_TYPES = {
    "inferred",
    "deduced",
    "concluded",
}
BACKGROUND_ACQUISITION_TYPES = {
    "pre_story",
    "background",
    "initial",
    "known_before_story",
}
INACTIVE_KNOWLEDGE_STATUSES = {
    "inactive",
    "invalid",
    "invalidated",
    "unsupported",
    "superseded",
    "retracted",
    "obsolete",
    "corrected",
    "false",
}


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def _knowledge_entries(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        return []
    result: list[dict[str, Any]] = []
    for key in ("entries", "wrong_beliefs"):
        values = document.get(key, [])
        if isinstance(values, list):
            result.extend(item for item in values if isinstance(item, dict))
    return result


def _entry_id(entry: dict[str, Any]) -> str:
    for key in ("knowledge_id", "belief_id", "fact_id", "entry_id", "id"):
        value = entry.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _entry_active(entry: dict[str, Any]) -> bool:
    return _norm(entry.get("status", "active")) not in INACTIVE_KNOWLEDGE_STATUSES


def _acquisition_type(entry: dict[str, Any]) -> str:
    return _norm(entry.get("acquisition_type") or entry.get("source_type"))


def _source_character(entry: dict[str, Any]) -> str:
    return str(entry.get("source_character_id") or "").strip()


def _source_description(entry: dict[str, Any]) -> str:
    return str(
        entry.get("source_description")
        or entry.get("source")
        or entry.get("acquisition_detail")
        or ""
    ).strip()


def _event_to_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    return {}


def _event_ref_index(events: list[Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in events:
        event = _event_to_dict(raw)
        for ref in event.get("knowledge_update_refs", []) or []:
            value = str(ref).strip()
            if value:
                result[value].append(event)
    return dict(result)


def _character_name(character: dict[str, Any]) -> str:
    identity = character.get("card", {}).get("identity", {})
    if isinstance(identity, dict):
        return str(identity.get("name") or identity.get("full_name") or "").strip()
    return ""


def active_knowledge_permissions(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a compact per-character allow-list for the scene writer.

    This is deliberately IDs + short fact text, not another complete knowledge document. The
    complete document remains in state.characters[*].knowledge; the allow-list makes the boundary
    salient without doubling packet size.
    """

    result: list[dict[str, Any]] = []
    for character in state.get("characters", []) or []:
        if not isinstance(character, dict):
            continue
        entries = [
            entry
            for entry in _knowledge_entries(character.get("knowledge", {}))
            if _entry_active(entry)
        ]
        result.append(
            {
                "character_id": str(character.get("character_id") or ""),
                "name": _character_name(character),
                "active_knowledge": [
                    {
                        "knowledge_id": _entry_id(entry),
                        "fact": str(entry.get("fact") or entry.get("belief") or "")[:500],
                        "acquisition_type": _acquisition_type(entry),
                        "source_character_id": _source_character(entry) or None,
                        "source_turn": entry.get("source_turn") or entry.get("learned_turn"),
                        "status": entry.get("status", "active"),
                    }
                    for entry in entries
                ],
            }
        )
    return result


def apply_turn_memory_boundaries(payload: dict[str, Any]) -> dict[str, Any]:
    """Make objective truth, director-only secrets and personal knowledge visibly separate."""

    story_bible = payload.get("story_bible")
    if not isinstance(story_bible, dict):
        story_bible = {}
        payload["story_bible"] = story_bible

    hidden_lore = story_bible.pop("hidden_lore", {})
    story_direction = story_bible.pop("story_direction", {})
    objective_memory = payload.pop("story_memory", [])

    payload["director_only_context"] = {
        "hidden_lore": hidden_lore,
        "story_direction": story_direction,
        "objective_chronology_memory": objective_memory,
        "rule": (
            "AUTHOR/DIRECTOR ONLY. These are truths and planning material available to the writer, "
            "not automatically to any character. Hidden lore stays hidden until an in-story "
            "acquisition/reveal gives a specific character that knowledge. Objective chronology "
            "records what really happened; it is not a shared mind."
        ),
    }
    state = payload.get("state", {})
    payload["character_knowledge_permissions"] = active_knowledge_permissions(
        state if isinstance(state, dict) else {}
    )
    payload["memory_boundaries"] = {
        "objective_truth": {
            "sources": [
                "director_only_context.objective_chronology_memory",
                "continuity_window",
                "recent_scene_history",
            ],
            "meaning": "What objectively happened. Writer memory only; not proof an NPC knows it.",
        },
        "director_only": {
            "sources": [
                "director_only_context.hidden_lore",
                "director_only_context.story_direction",
            ],
            "meaning": "Secrets/plans. Never leak through dialogue, narration-as-knowledge or NPC behavior before a real reveal/source.",
        },
        "character_knowledge": {
            "source": "state.characters[*].knowledge",
            "allow_list": "character_knowledge_permissions",
            "meaning": (
                "The only persistent personal knowledge for each character. A chronology event, "
                "POV thought, another character's conversation or hidden lore does NOT become this "
                "character's memory merely because the writer can see it."
            ),
        },
        "current_scene_exception": (
            "A character may additionally react to information they personally perceive in the "
            "current scene. If that information matters beyond the instant, commit it to that "
            "character's knowledge with an explicit acquisition source."
        ),
    }
    payload["instruction"] = (
        str(payload.get("instruction", ""))
        + " KNOWLEDGE FIREWALL: before any NPC mentions, remembers, reacts to, plans around or "
        "quotes a non-obvious fact, check that NPC's own active knowledge or a perception/source "
        "that occurs in this scene. Never promote objective chronology, POV-only speech/thought, "
        "another NPC's private conversation, hidden_lore or director_plan into character knowledge. "
        "If Emily told Ethan something while Ren was absent, Ren cannot repeat or react to it later "
        "unless Ren separately learned it and that source exists in his knowledge. Do not invent a "
        "retroactive source merely to justify a draft error. A model continuity mistake is not an "
        "in-world mystery and must not be rationalized by making the POV look confused or wrong."
    ).strip()
    return payload


def validate_turn_knowledge_updates(
    *,
    before_state: dict[str, Any],
    request: Any,
    turn_number: int,
) -> None:
    """Reject new personal knowledge without an explicit in-story acquisition path.

    The validator intentionally applies only to newly-created/reactivated knowledge entries. Old
    sessions may contain legacy entries without provenance; those are audited separately instead of
    making an old session unplayable immediately after deployment.
    """

    previous_by_character: dict[str, dict[str, dict[str, Any]]] = {}
    for character in before_state.get("characters", []) or []:
        if not isinstance(character, dict):
            continue
        character_id = str(character.get("character_id") or "")
        previous_by_character[character_id] = {
            _entry_id(entry): entry
            for entry in _knowledge_entries(character.get("knowledge", {}))
            if _entry_id(entry)
        }

    ref_index = _event_ref_index(list(getattr(request, "events", []) or []))

    for update in list(getattr(request.state_updates, "characters", []) or []):
        knowledge = getattr(update, "knowledge", None)
        if not isinstance(knowledge, dict):
            continue
        owner_id = str(update.character_id)
        previous_entries = previous_by_character.get(owner_id, {})
        for entry in _knowledge_entries(knowledge):
            knowledge_id = _entry_id(entry)
            if not knowledge_id:
                raise ServiceError(
                    422,
                    "KNOWLEDGE_ID_REQUIRED",
                    f"New knowledge for {owner_id} requires a stable knowledge_id/belief_id",
                )
            previous = previous_entries.get(knowledge_id)
            newly_active = previous is None or (
                not _entry_active(previous) and _entry_active(entry)
            )
            if not newly_active:
                continue

            acquisition = _acquisition_type(entry)
            if not acquisition or acquisition in {"unknown", "legacy", "legacy_unknown"}:
                raise ServiceError(
                    422,
                    "KNOWLEDGE_SOURCE_REQUIRED",
                    f"New knowledge {knowledge_id} for {owner_id} needs acquisition_type",
                )
            if acquisition in BACKGROUND_ACQUISITION_TYPES:
                raise ServiceError(
                    422,
                    "RUNTIME_BACKGROUND_KNOWLEDGE_FORBIDDEN",
                    f"{knowledge_id} cannot be introduced as pre-story/background knowledge on turn {turn_number}",
                )

            source_events = ref_index.get(knowledge_id, [])
            if not source_events:
                raise ServiceError(
                    422,
                    "KNOWLEDGE_EVENT_REF_REQUIRED",
                    f"Chronology event must include knowledge_update_refs=['{knowledge_id}'] for new knowledge owned by {owner_id}",
                )

            if acquisition in DIRECT_ACQUISITION_TYPES:
                witnessed = any(
                    owner_id in list(event.get("participants_present", []) or [])
                    for event in source_events
                )
                if not witnessed:
                    raise ServiceError(
                        422,
                        "KNOWLEDGE_WITNESS_REQUIRED",
                        f"{owner_id} cannot acquire {knowledge_id} by {acquisition} without being a participant in its source event",
                    )

            source_character_id = _source_character(entry)
            source_description = _source_description(entry)
            if acquisition == "told_directly":
                if not source_character_id and not source_description:
                    raise ServiceError(
                        422,
                        "KNOWLEDGE_SPEAKER_REQUIRED",
                        f"Directly told knowledge {knowledge_id} needs the speaker/source",
                    )
                if source_character_id and not any(
                    source_character_id in list(event.get("participants_present", []) or [])
                    and owner_id in list(event.get("participants_present", []) or [])
                    for event in source_events
                ):
                    raise ServiceError(
                        422,
                        "KNOWLEDGE_SPEAKER_NOT_PRESENT",
                        f"Source {source_character_id} and listener {owner_id} must share the source event for {knowledge_id}",
                    )

            if acquisition in REMOTE_ACQUISITION_TYPES:
                if not source_character_id and not source_description:
                    raise ServiceError(
                        422,
                        "KNOWLEDGE_REMOTE_SOURCE_REQUIRED",
                        f"Remote knowledge {knowledge_id} for {owner_id} needs an explicit sender/source",
                    )

            if acquisition in INFERENCE_ACQUISITION_TYPES:
                owner_has_source_event = any(
                    owner_id in list(event.get("participants_present", []) or [])
                    for event in source_events
                )
                basis = entry.get("basis_knowledge_ids") or entry.get("basis")
                if not owner_has_source_event and not basis:
                    raise ServiceError(
                        422,
                        "KNOWLEDGE_INFERENCE_BASIS_REQUIRED",
                        f"Inference {knowledge_id} for {owner_id} needs a witnessed source event or explicit basis",
                    )

            # Stamp source coordinates into the entry itself. The event receives its permanent
            # event_id later in the same atomic commit, while turn/scene/time are already stable.
            entry.setdefault("source_turn", turn_number)
            entry.setdefault("source_scene_id", str(getattr(request, "scene_id", "")))
            entry.setdefault("learned_at", str(getattr(request, "story_datetime", "")))
            entry["provenance_status"] = "verified_current_turn"


def knowledge_provenance_issues(
    state: dict[str, Any], chronology: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Mechanically flag knowledge that needs human/model audit; never delete it here."""

    ref_index = _event_ref_index(chronology)
    issues: list[dict[str, Any]] = []
    for character in state.get("characters", []) or []:
        if not isinstance(character, dict):
            continue
        owner_id = str(character.get("character_id") or "")
        name = _character_name(character)
        for entry in _knowledge_entries(character.get("knowledge", {})):
            if not _entry_active(entry):
                continue
            knowledge_id = _entry_id(entry)
            acquisition = _acquisition_type(entry)
            if not knowledge_id:
                issues.append(
                    {
                        "issue_id": f"{owner_id}:missing-id:{len(issues)}",
                        "severity": "warning",
                        "reason": "active_knowledge_missing_id",
                        "character_id": owner_id,
                        "character_name": name,
                        "knowledge_id": None,
                        "fact": str(entry.get("fact") or entry.get("belief") or "")[:700],
                    }
                )
                continue

            linked_events = ref_index.get(knowledge_id, [])
            if acquisition in BACKGROUND_ACQUISITION_TYPES:
                continue
            if not acquisition or acquisition in {"unknown", "legacy", "legacy_unknown"}:
                issues.append(
                    {
                        "issue_id": f"{owner_id}:{knowledge_id}:missing-source-type",
                        "severity": "review",
                        "reason": "legacy_unprovenanced",
                        "character_id": owner_id,
                        "character_name": name,
                        "knowledge_id": knowledge_id,
                        "fact": str(entry.get("fact") or entry.get("belief") or "")[:700],
                    }
                )
                continue

            has_source_coordinates = bool(
                entry.get("source_turn")
                or entry.get("learned_turn")
                or entry.get("source_scene_id")
            )
            if not linked_events and not has_source_coordinates:
                issues.append(
                    {
                        "issue_id": f"{owner_id}:{knowledge_id}:no-source-event",
                        "severity": "review",
                        "reason": "knowledge_has_no_traceable_source",
                        "character_id": owner_id,
                        "character_name": name,
                        "knowledge_id": knowledge_id,
                        "fact": str(entry.get("fact") or entry.get("belief") or "")[:700],
                        "acquisition_type": acquisition,
                    }
                )

            if acquisition in DIRECT_ACQUISITION_TYPES and linked_events:
                if not any(
                    owner_id in list(event.get("participants_present", []) or [])
                    for event in linked_events
                ):
                    issues.append(
                        {
                            "issue_id": f"{owner_id}:{knowledge_id}:impossible-direct",
                            "severity": "error",
                            "reason": "direct_knowledge_owner_absent_from_source_event",
                            "character_id": owner_id,
                            "character_name": name,
                            "knowledge_id": knowledge_id,
                            "fact": str(entry.get("fact") or entry.get("belief") or "")[:700],
                            "acquisition_type": acquisition,
                            "source_event_ids": [
                                event.get("event_id") for event in linked_events if event.get("event_id")
                            ],
                            "source_event_participants": [
                                list(event.get("participants_present", []) or [])
                                for event in linked_events
                            ],
                        }
                    )

            if acquisition == "told_directly" and not (
                _source_character(entry) or _source_description(entry)
            ):
                issues.append(
                    {
                        "issue_id": f"{owner_id}:{knowledge_id}:missing-speaker",
                        "severity": "error",
                        "reason": "direct_report_missing_source",
                        "character_id": owner_id,
                        "character_name": name,
                        "knowledge_id": knowledge_id,
                        "fact": str(entry.get("fact") or "")[:700],
                    }
                )
    return issues


def apply_audit_memory_boundaries(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = payload.get("state", {})
    chronology = payload.get("chronology", [])
    issues = knowledge_provenance_issues(
        state if isinstance(state, dict) else {},
        chronology if isinstance(chronology, list) else [],
    )
    payload["memory_boundaries"] = {
        "chronology": "Objective truth about what happened. Never equivalent to what every character knows.",
        "hidden_lore": "Director-only truth. Never character knowledge until a real reveal/acquisition exists.",
        "character_knowledge": "Per-character state.characters[*].knowledge only; audit source/provenance independently for each owner.",
    }
    payload["knowledge_provenance_audit"] = {
        "issues": issues,
        "issue_ids": [item["issue_id"] for item in issues],
        "instruction": (
            "Check each listed knowledge item against the full turns and chronology. Objective truth "
            "is not enough: determine exactly how THIS character learned it. For an unsupported "
            "entry, preserve audit history but mark the knowledge inactive/unsupported or correct "
            "its provenance. Never invent a retroactive witness/source solely to keep an erroneous "
            "scene line canonical. Do not resolve a continuity error by making POV confused, lying "
            "or irrational unless the actual recorded story established that independently."
        ),
    }
    payload["instruction"] = (
        str(payload.get("instruction", ""))
        + " Perform the knowledge_provenance_audit as a separate pass. Chronology is objective "
        "truth, hidden_lore is director-only, and each character knowledge file is an independent "
        "epistemic state. Never copy facts across these layers without an acquisition source."
    ).strip()
    return payload, issues


def copy_issue_list(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return deepcopy(issues)
