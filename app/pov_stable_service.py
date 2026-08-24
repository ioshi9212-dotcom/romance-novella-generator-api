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
