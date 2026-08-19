from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.service import ServiceError, _split_text


class StableRuntimeNovellaService(EnhancedWriterNovellaService):
    """Production wrapper that makes interrupted long-session Action flows resumable.

    Railway remains authoritative. A pending turn is never silently discarded. If ChatGPT ran out
    of Action budget after reading only part of a packet (or after reading all of it but before
    commitTurn), the next getTurnPacket call resumes that exact pending turn instead of returning
    TURN_ALREADY_PENDING and trapping the chat in technical status messages.
    """

    COMPACT_PACKET_VERSION = 1

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

    def _compact_fresh_packet_locked(
        self,
        session_id: str,
        *,
        pending_path: str,
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        """Compact JSON before the first Action response actually leaves this method.

        Base/enhanced services serialize packets with indentation for readability. For Custom GPT
        Actions that whitespace is pure transport cost. Re-serializing the exact same JSON with
        compact separators preserves every field and value while reducing both total packet size
        and the number of chunks. This is only done for a freshly-created packet whose chunk zero
        has not yet been returned to the caller.
        """

        if pending.get("compact_packet_version") == self.COMPACT_PACKET_VERSION:
            return pending
        chunks = pending.get("chunks", [])
        if not isinstance(chunks, list) or not chunks:
            return pending
        raw = "".join(str(chunk) for chunk in chunks)
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return pending
        compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        new_chunks = _split_text(compact, self.settings.packet_chunk_chars)
        pending["chunks"] = new_chunks
        pending["content_sha256"] = sha256(compact.encode("utf-8")).hexdigest()
        pending["last_delivered_chunk_index"] = 0
        pending["all_chunks_delivered"] = len(new_chunks) == 1
        pending["compact_packet_version"] = self.COMPACT_PACKET_VERSION
        pending["compact_packet_chars"] = len(compact)
        self.storage._write_json_batch_locked(session_id, {pending_path: pending})
        return pending

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

        # Build/augment the fresh packet first, then compact it before returning chunk zero.
        super().get_turn_packet(session_id, request)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_turn.json", default={}
            )
            if pending.get("status") != "active":
                raise ServiceError(409, "TURN_NOT_PENDING", "Turn packet is no longer active")
            pending = self._compact_fresh_packet_locked(
                session_id,
                pending_path="pending_turn.json",
                pending=pending,
            )
            return self._packet_chunk_response(session_id, pending, 0)

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

        super().get_audit_packet(session_id)
        with self.storage.session_transaction(session_id):
            pending = self.storage.read_json(
                session_id, "pending_audit.json", default={}
            )
            if pending.get("status") != "active":
                raise ServiceError(409, "AUDIT_NOT_PENDING", "Audit packet is no longer active")
            pending = self._compact_fresh_packet_locked(
                session_id,
                pending_path="pending_audit.json",
                pending=pending,
            )
            return self._packet_chunk_response(session_id, pending, 0)
