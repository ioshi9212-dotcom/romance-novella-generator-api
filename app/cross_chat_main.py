from __future__ import annotations

from typing import Any

from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.main import app, settings
from app.service import ServiceError


class CrossChatResumeNovellaService(EnhancedWriterNovellaService):
    """Replay an existing pending packet from chunk zero in a new chat.

    This keeps the existing API and session format unchanged. It never creates a
    replacement turn for an already-pending player input and never discards canon.
    """

    def _restart_pending_packet_locked(
        self,
        session_id: str,
        *,
        pending: dict[str, Any],
        pending_path: str,
    ) -> dict[str, Any]:
        if pending.get("status") != "active":
            raise ServiceError(409, "PACKET_NOT_PENDING", "Packet is no longer active")
        chunks = pending.get("chunks", [])
        if not isinstance(chunks, list) or not chunks:
            raise ServiceError(500, "PACKET_CORRUPT", "Active packet has no stored chunks")

        pending["last_delivered_chunk_index"] = 0
        pending["all_chunks_delivered"] = len(chunks) == 1
        self.storage._write_json_batch_locked(session_id, {pending_path: pending})
        return self._packet_chunk_response(session_id, pending, 0)

    def get_turn_packet(self, session_id: str, request: Any) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(session_id, "pending_turn.json", default={})
            if isinstance(pending, dict) and pending.get("status") == "active":
                same_pending_turn = (
                    pending.get("player_input") == request.player_input
                    and pending.get("mode") == request.mode
                )
                if not same_pending_turn:
                    raise ServiceError(
                        409,
                        "TURN_ALREADY_PENDING",
                        "A different turn is already pending and must be committed first",
                    )
                pending["client_request_id"] = request.client_request_id
                return self._restart_pending_packet_locked(
                    session_id,
                    pending=pending,
                    pending_path="pending_turn.json",
                )
        return super().get_turn_packet(session_id, request)

    def get_audit_packet(self, session_id: str) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(session_id, "pending_audit.json", default={})
            if isinstance(pending, dict) and pending.get("status") == "active":
                return self._restart_pending_packet_locked(
                    session_id,
                    pending=pending,
                    pending_path="pending_audit.json",
                )
        return super().get_audit_packet(session_id)


app.state.service = CrossChatResumeNovellaService(settings)
