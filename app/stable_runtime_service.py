from __future__ import annotations

from typing import Any

from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.service import ServiceError, _split_text


class StableRuntimeNovellaService(EnhancedWriterNovellaService):
    """Keep long-session packets readable within one Custom GPT turn.

    The authoritative full state is still stored in pending_turn.before_state. This layer only
    changes how already-built packet text is chunked and how strongly the Action response tells
    the caller to keep reading before replying to the player.
    """

    STABILITY_PACKET_VERSION = 1

    def _repack_active_packet_locked(
        self,
        session_id: str,
        *,
        pending_path: str,
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        if pending.get("status") != "active":
            return pending
        chunks = pending.get("chunks", [])
        if not isinstance(chunks, list) or not chunks:
            return pending

        raw = "".join(str(chunk) for chunk in chunks)
        target_chunks = _split_text(raw, self.settings.packet_chunk_chars)
        already_current = (
            pending.get("stability_packet_version") == self.STABILITY_PACKET_VERSION
            and chunks == target_chunks
        )
        if already_current:
            return pending

        previous_count = len(chunks)
        pending["chunks"] = target_chunks
        pending["last_delivered_chunk_index"] = 0
        pending["all_chunks_delivered"] = len(target_chunks) == 1
        pending["stability_packet_version"] = self.STABILITY_PACKET_VERSION
        pending["stability_repacked_from_chunk_count"] = previous_count
        pending["stability_chunk_chars"] = self.settings.packet_chunk_chars
        self.storage._write_json_batch_locked(session_id, {pending_path: pending})
        return pending

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
                "Do not reply to the player and do not restart the packet. Immediately call "
                f"{action} with chunk_index {next_index}, then keep reading in order until "
                "all_chunks_delivered=true."
            )
        elif response["packet_type"] == "turn":
            response["next_required_action"] = (
                "All turn packet chunks are loaded. Do not send a progress/status message to the "
                "player. Generate the scene, call commitTurn, and reply only after commit succeeds."
            )
        else:
            response["next_required_action"] = (
                "All audit packet chunks are loaded. Do not send a progress/status message to the "
                "player. Complete the audit and call commitAudit before requesting a turn."
            )
        return response

    def get_turn_packet(self, session_id: str, request: Any) -> dict[str, Any]:
        super().get_turn_packet(session_id, request)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_turn.json", default={}
            )
            if pending.get("status") != "active":
                raise ServiceError(409, "TURN_NOT_PENDING", "Turn packet is no longer active")
            pending = self._repack_active_packet_locked(
                session_id,
                pending_path="pending_turn.json",
                pending=pending,
            )
            return self._packet_chunk_response(session_id, pending, 0)

    def get_audit_packet(self, session_id: str) -> dict[str, Any]:
        super().get_audit_packet(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )
            if pending.get("status") != "active":
                raise ServiceError(409, "AUDIT_NOT_PENDING", "Audit packet is no longer active")
            pending = self._repack_active_packet_locked(
                session_id,
                pending_path="pending_audit.json",
                pending=pending,
            )
            return self._packet_chunk_response(session_id, pending, 0)

    def get_turn_packet_chunk(
        self,
        session_id: str,
        packet_id: str,
        chunk_index: int,
    ) -> dict[str, Any]:
        pending = self.storage.read_json(session_id, "pending_turn.json", default={})
        if (
            isinstance(pending, dict)
            and pending.get("status") == "active"
            and pending.get("packet_id") == packet_id
            and pending.get("stability_packet_version") == self.STABILITY_PACKET_VERSION
        ):
            next_index = self._last_delivered_chunk_index(pending) + 1
            if chunk_index > next_index:
                # A retry may still remember an index from the pre-repack packet. Serve the
                # actual next chunk instead of trapping the conversation in an out-of-order loop.
                chunk_index = next_index
        return super().get_turn_packet_chunk(session_id, packet_id, chunk_index)

    def get_audit_packet_chunk(
        self,
        session_id: str,
        packet_id: str,
        chunk_index: int,
    ) -> dict[str, Any]:
        pending = self.storage.read_json(session_id, "pending_audit.json", default={})
        if (
            isinstance(pending, dict)
            and pending.get("status") == "active"
            and pending.get("packet_id") == packet_id
            and pending.get("stability_packet_version") == self.STABILITY_PACKET_VERSION
        ):
            next_index = self._last_delivered_chunk_index(pending) + 1
            if chunk_index > next_index:
                chunk_index = next_index
        return super().get_audit_packet_chunk(session_id, packet_id, chunk_index)
