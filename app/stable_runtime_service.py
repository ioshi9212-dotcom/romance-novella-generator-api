from __future__ import annotations

from typing import Any

from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.service import ServiceError


class StableRuntimeNovellaService(EnhancedWriterNovellaService):
    """Production wrapper that makes interrupted long-session Action flows resumable.

    Railway remains authoritative. A pending turn is never silently discarded. If ChatGPT ran out
    of Action budget after reading only part of a packet (or after reading all of it but before
    commitTurn), the next getTurnPacket call resumes that exact pending turn instead of returning
    TURN_ALREADY_PENDING and trapping the chat in technical status messages.
    """

    @staticmethod
    def _packet_chunk_response(
        session_id: str, pending: dict[str, Any], chunk_index: int
    ) -> dict[str, Any]:
        response = EnhancedWriterNovellaService._packet_chunk_response(
            session_id, pending, chunk_index
        )
        if response["has_more"]:
            next_index = response["next_chunk_index"]
            action = (
                "getTurnPacketChunk"
                if response["packet_type"] == "turn"
                else "getAuditPacketChunk"
            )
            response["next_required_action"] = (
                "Do not reply to the player with progress, delay, packet, Railway or save-status "
                "text. Immediately continue the same operation: call "
                f"{action} with chunk_index {next_index} and keep reading in order until "
                "all_chunks_delivered=true."
            )
        elif response["packet_type"] == "turn":
            response["next_required_action"] = (
                "All turn-packet chunks are loaded. Do not send a technical/status reply. "
                "Generate the scene, call commitTurn, and only after commit succeeds show the "
                "committed scene to the player."
            )
        else:
            response["next_required_action"] = (
                "All audit-packet chunks are loaded. Do not send a technical/status reply. "
                "Complete the audit, call commitAudit, then continue gameplay."
            )
        return response

    def _resume_pending_locked(
        self,
        session_id: str,
        *,
        pending: dict[str, Any],
        pending_path: str,
        packet_type: str,
        request_changed: bool = False,
    ) -> dict[str, Any]:
        if pending.get("status") != "active":
            raise ServiceError(409, "PACKET_NOT_PENDING", "Packet is no longer active")
        chunks = pending.get("chunks", [])
        if not isinstance(chunks, list) or not chunks:
            raise ServiceError(500, "PACKET_CORRUPT", "Active packet has no stored chunks")

        last_delivered = self._last_delivered_chunk_index(pending)
        if last_delivered < len(chunks) - 1:
            response = self._deliver_packet_chunk_locked(
                session_id,
                pending,
                chunk_index=last_delivered + 1,
                pending_path=pending_path,
                error_prefix=packet_type.upper(),
            )
        else:
            response = self._packet_chunk_response(
                session_id,
                pending,
                last_delivered,
            )

        if request_changed and packet_type == "turn":
            response["next_required_action"] = (
                "An earlier player input already owns the pending unsaved turn. The newest player "
                "message is not a new gameplay turn yet. Finish reading/committing the existing "
                "pending turn first. Do not output a technical status message. "
                + response["next_required_action"]
            )
        return response

    def get_turn_packet(self, session_id: str, request: Any) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_turn.json", default={}
            )
            if isinstance(pending, dict) and pending.get("status") == "active":
                same_request = (
                    pending.get("player_input") == request.player_input
                    and pending.get("mode") == request.mode
                    and pending.get("client_request_id") == request.client_request_id
                )
                return self._resume_pending_locked(
                    session_id,
                    pending=pending,
                    pending_path="pending_turn.json",
                    packet_type="turn",
                    request_changed=not same_request,
                )
        return super().get_turn_packet(session_id, request)

    def get_audit_packet(self, session_id: str) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )
            if isinstance(pending, dict) and pending.get("status") == "active":
                return self._resume_pending_locked(
                    session_id,
                    pending=pending,
                    pending_path="pending_audit.json",
                    packet_type="audit",
                )
        return super().get_audit_packet(session_id)
