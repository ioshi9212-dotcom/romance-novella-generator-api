from __future__ import annotations

from typing import Any

from app.enhanced_writer_service import EnhancedWriterNovellaService


class PovStableWriterService(EnhancedWriterNovellaService):
    """Experimental long-session tuning that keeps POV and story continuity active."""

    RECENT_FULL_SCENES = 4

    @staticmethod
    def _parse_player_input(text: str) -> dict[str, Any]:
        parsed = EnhancedWriterNovellaService._parse_player_input(text)
        parsed["instruction"] = (
            "spoken segments are POV speech aloud. stage_direction segments are not speech "
            "and are not messages by themselves. A stage direction becomes communication "
            "only when it explicitly says the POV speaks, writes, sends or otherwise "
            "communicates something. Never merge an unrelated stage direction into the "
            "preceding spoken line. This parsing describes what the player explicitly supplied; "
            "it does not limit the POV's natural presence in the rest of the scene. Keep the POV "
            "visibly involved through natural reactions, movement and short neutral replies when "
            "they do not create a new meaningful decision or change the player's intent."
        )
        return parsed

    @classmethod
    def _relationship_lens(cls, before_state: dict[str, Any]) -> dict[str, Any]:
        lens = super()._relationship_lens(before_state)
        lens["instruction"] = (
            "Relationships are living causal state, not fixed labels and not decorative footer "
            "numbers. Re-evaluate the current scene for each present NPC. If something in the "
            "scene genuinely changes trust, sympathy, closeness, attraction, jealousy, respect, "
            "resentment, suspicion, fear or another relationship-specific dimension, update that "
            "dimension instead of mechanically carrying the old value forward. A meaningful new "
            "dimension may be created when the relationship develops in a new direction; do not "
            "limit every relationship forever to the dimensions created at session start. Several "
            "dimensions may coexist and move independently, including in opposite directions. "
            "Do not force a change when nothing happened, but do not freeze values merely because "
            "they have been stable for several turns. Absence of a dimension is not zero. A value "
            "of 0 is latent/absent state and should normally be omitted from the visible footer; "
            "show it only if the current scene is actively establishing or changing that dimension. "
            "Do not create generic 'interest' as filler. Use character, goals, knowledge, current "
            "state and the actual scene to decide what changes and why."
        )
        return lens

    @classmethod
    def _registry_with_continuity(
        cls,
        before_state: dict[str, Any],
        payload: dict[str, Any],
        chronology: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        registry = super()._registry_with_continuity(before_state, payload, chronology)
        current_turn = int(payload.get("turn_number", 0) or 0)
        continuity = {
            str(item.get("character_id", "")): item
            for item in payload.get("character_continuity_index", [])
            if item.get("character_id")
        }

        for entry in registry:
            character_id = str(entry.get("character_id", ""))
            info = continuity.get(character_id, {})
            last_seen = info.get("last_seen_turn")
            try:
                turns_absent = (
                    max(current_turn - int(last_seen), 0)
                    if current_turn and last_seen is not None
                    else None
                )
            except (TypeError, ValueError):
                turns_absent = None

            entry["turns_absent"] = turns_absent
            is_player_defined = entry.get("origin") == "player" or entry.get("card_level") == "player_defined"
            if is_player_defined:
                entry["story_presence_priority"] = "player_defined"
                entry["story_presence_instruction"] = (
                    "This character was explicitly created by the player and must remain an active "
                    "part of the story. Do not forget, silently retire or replace them because they "
                    "have been offscreen. They do not need to appear in every scene, but their goals, "
                    "relationships, offscreen life and plausible opportunities to return must remain "
                    "in director planning. If they have been absent for many turns, look for a natural "
                    "story reason to bring them back, contact the POV, affect another character, create "
                    "a consequence or otherwise re-enter the narrative. Do not force an illogical cameo."
                )
                if turns_absent is not None and turns_absent >= 15:
                    entry["long_absence"] = True
                    entry["return_consideration"] = (
                        "Long absence detected. Actively consider a natural return or offscreen impact "
                        "using this character's established goals and relationships."
                    )
                else:
                    entry["long_absence"] = False
        return registry
