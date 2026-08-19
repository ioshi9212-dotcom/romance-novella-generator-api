from __future__ import annotations

from typing import Any

from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.service import ServiceError


class ResumableSessionNovellaService(EnhancedWriterNovellaService):
    """Replay an existing uncommitted packet from chunk zero when a chat reconnects.

    No public API or schema changes are introduced. Railway remains authoritative and no
    committed turn is rewritten. Re-entering getTurnPacket/getAuditPacket while a packet is
    already active simply restarts delivery of that stored packet from the beginning so a new
    chat can read the complete context before committing it.
    """

    def _restart_pending_packet_locked(
        self,
        session_id: str,
        *,
        pending: dict[str, Any],
        pending_path: str,
        packet_type: str,
    ) -> dict[str, Any]:
        if pending.get("status") != "active":
            raise ServiceError(409, "PACKET_NOT_PENDING", "Packet is no longer active")

        chunks = pending.get("chunks", [])
        if not isinstance(chunks, list) or not chunks:
            raise ServiceError(500, "PACKET_CORRUPT", "Active packet has no stored chunks")

        pending["last_delivered_chunk_index"] = 0
        pending["all_chunks_delivered"] = len(chunks) == 1

        if packet_type == "turn":
            # Scene-character bundles belong only to the uncommitted draft attempt. A new chat
            # must load any entering offscreen character again from the same before_state.
            pending["loaded_scene_character_ids"] = []
            pending["scene_character_bundles"] = {}

        self.storage._write_json_batch_locked(
            session_id,
            {pending_path: pending},
        )
        return self._packet_chunk_response(session_id, pending, 0)

    def get_turn_packet(self, session_id: str, request: Any) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_turn.json", default={}
            )
            if isinstance(pending, dict) and pending.get("status") == "active":
                return self._restart_pending_packet_locked(
                    session_id,
                    pending=pending,
                    pending_path="pending_turn.json",
                    packet_type="turn",
                )
        return super().get_turn_packet(session_id, request)

    def get_audit_packet(self, session_id: str) -> dict[str, Any]:
        self._require_session(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )
            if isinstance(pending, dict) and pending.get("status") == "active":
                return self._restart_pending_packet_locked(
                    session_id,
                    pending=pending,
                    pending_path="pending_audit.json",
                    packet_type="audit",
                )
        return super().get_audit_packet(session_id)
