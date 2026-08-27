from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.fast_audit_service import FastAuditNovellaService
from app.service import NovellaService, ServiceError


class RecoveryNovellaService(FastAuditNovellaService):
    """Recover orphaned pending turns and preserve explicit POV speech."""

    _LOWER_BLOCK_MARKER = "\nЧто я могу сделать"
    _QUOTE_TRANSLATION = str.maketrans(
        {
            "«": '"',
            "»": '"',
            "“": '"',
            "”": '"',
            "„": '"',
            "‟": '"',
            "‘": "'",
            "’": "'",
            "‚": "'",
            "‛": "'",
        }
    )

    @classmethod
    def _normalize_visible_text(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).translate(
            cls._QUOTE_TRANSLATION
        )
        normalized = normalized.replace("\u00a0", " ")
        return re.sub(r"\s+", " ", normalized).strip()

    @classmethod
    def _main_scene_text(cls, scene_output: str) -> str:
        return scene_output.split(cls._LOWER_BLOCK_MARKER, 1)[0]

    @classmethod
    def _validate_scene_commit_context(
        cls,
        request: Any,
        pending: dict[str, Any],
        before_state: dict[str, Any],
        turn_number: int,
    ) -> None:
        NovellaService._validate_scene_commit_context(
            request, pending, before_state, turn_number
        )

        player_input_map = cls._parse_player_input(
            str(pending.get("player_input", ""))
        )
        spoken_segments = list(player_input_map.get("spoken_segments", []))
        if not spoken_segments:
            return

        normalized_scene = cls._normalize_visible_text(
            cls._main_scene_text(str(request.scene_output))
        )
        missing = [
            segment
            for segment in spoken_segments
            if cls._normalize_visible_text(str(segment)) not in normalized_scene
        ]
        if missing:
            raise ServiceError(
                422,
                "POV_SPOKEN_INPUT_MISSING",
                "Every spoken player_input segment must appear verbatim in the main scene before the choice blocks",
            )

    def _resume_pending_turn_locked(
        self,
        session_id: str,
        pending: dict[str, Any],
        *,
        restart_chunks: bool,
    ) -> dict[str, Any]:
        if not pending.get("chunks"):
            raise ServiceError(
                500, "TURN_PACKET_CORRUPT", "Pending turn packet has no content"
            )

        if restart_chunks and (
            pending.get("enhanced_packet_version") == self.ENHANCED_PACKET_VERSION
        ):
            pending["last_delivered_chunk_index"] = 0
            pending["all_chunks_delivered"] = len(pending.get("chunks", [])) == 1
            self.storage._write_json_batch_locked(
                session_id, {"pending_turn.json": pending}
            )

        return self._augment_turn_packet_locked(session_id, pending)

    def get_turn_packet(self, session_id: str, request: Any) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_turn.json", default={}
            )
            if isinstance(pending, dict) and pending.get("status") == "active":
                same_logical_request = (
                    pending.get("player_input") == request.player_input
                    and pending.get("mode") == request.mode
                )
                return self._resume_pending_turn_locked(
                    session_id,
                    pending,
                    restart_chunks=not same_logical_request,
                )

        return super().get_turn_packet(session_id, request)
