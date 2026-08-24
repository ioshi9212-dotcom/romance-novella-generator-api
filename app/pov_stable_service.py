from __future__ import annotations

from typing import Any

from app.enhanced_writer_service import EnhancedWriterNovellaService


class PovStableWriterService(EnhancedWriterNovellaService):
    """Experimental long-session tuning that keeps POV active without hard validators."""

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
