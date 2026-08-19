from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.knowledge_firewall import (
    apply_audit_memory_boundaries,
    apply_turn_memory_boundaries,
    validate_turn_knowledge_updates,
)
from app.service import ServiceError, _split_text


class StableRuntimeNovellaService(EnhancedWriterNovellaService):
    """Production wrapper for resumable packets and strict epistemic boundaries."""

    COMPACT_PACKET_VERSION = 2

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
                "Complete the audit, including knowledge provenance, call commitAudit, then "
                "continue gameplay."
            )
        return response

    def _prepare_fresh_payload(
        self,
        pending: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        packet_type = str(pending.get("packet_type") or payload.get("packet_type") or "")
        if packet_type == "turn":
            apply_turn_memory_boundaries(payload)
            pending["knowledge_firewall_version"] = 1
        elif packet_type == "audit":
            payload, issues = apply_audit_memory_boundaries(payload)
            issue_ids = [str(item.get("issue_id")) for item in issues if item.get("issue_id")]
            pending["knowledge_firewall_version"] = 1
            pending["knowledge_provenance_issue_ids"] = issue_ids
            pending["knowledge_provenance_error_ids"] = [
                str(item.get("issue_id"))
                for item in issues
                if item.get("issue_id") and item.get("severity") == "error"
            ]
            verification = payload.setdefault("required_findings_verification", {})
            if isinstance(verification, dict):
                verification["knowledge_provenance_checked_ids"] = issue_ids
            audit_block = payload.get("knowledge_provenance_audit")
            if isinstance(audit_block, dict):
                audit_block["required_verification_field"] = (
                    "findings.verification.knowledge_provenance_checked_ids"
                )
        return payload

    def _compact_fresh_packet_locked(
        self,
        session_id: str,
        *,
        pending_path: str,
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply memory boundaries and compact JSON before chunk zero leaves the server."""

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
        payload = self._prepare_fresh_payload(pending, payload)
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

    def commit_turn(self, session_id: str, request: Any) -> dict[str, Any]:
        """Block chronology-to-NPC memory leaks before the atomic base commit."""

        pending = self.storage.read_json(session_id, "pending_turn.json", default={})
        if (
            isinstance(pending, dict)
            and pending.get("status") == "active"
            and pending.get("turn_id") == request.turn_id
        ):
            before_state = pending.get("before_state", {})
            if isinstance(before_state, dict):
                validate_turn_knowledge_updates(
                    before_state=before_state,
                    request=request,
                    turn_number=int(pending.get("turn_number", 0) or 0),
                )
        return super().commit_turn(session_id, request)

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

    @staticmethod
    def _require_knowledge_audit_verification(
        request: Any,
        required_issue_ids: list[str],
        error_issue_ids: list[str],
    ) -> None:
        if not required_issue_ids:
            return
        findings = request.findings if isinstance(request.findings, dict) else {}
        verification = findings.get("verification")
        if not isinstance(verification, dict):
            raise ServiceError(
                422,
                "AUDIT_KNOWLEDGE_PROVENANCE_INCOMPLETE",
                "findings.verification is required for knowledge provenance audit",
            )
        checked = {
            str(item)
            for item in verification.get("knowledge_provenance_checked_ids", [])
        }
        missing = sorted(set(required_issue_ids) - checked)
        if missing:
            raise ServiceError(
                422,
                "AUDIT_KNOWLEDGE_PROVENANCE_INCOMPLETE",
                "Knowledge provenance audit did not check: " + ", ".join(missing),
            )
        if error_issue_ids:
            actions = findings.get("knowledge_provenance_actions")
            if not isinstance(actions, dict):
                raise ServiceError(
                    422,
                    "AUDIT_KNOWLEDGE_REPAIR_REQUIRED",
                    "findings.knowledge_provenance_actions must state the repair/evidence for every provenance error",
                )
            unresolved = [issue_id for issue_id in error_issue_ids if not actions.get(issue_id)]
            if unresolved:
                raise ServiceError(
                    422,
                    "AUDIT_KNOWLEDGE_REPAIR_REQUIRED",
                    "Knowledge provenance errors have no repair/evidence action: "
                    + ", ".join(unresolved),
                )

    def commit_audit(self, session_id: str, request: Any) -> dict[str, Any]:
        pending = self.storage.read_json(session_id, "pending_audit.json", default={})
        if (
            isinstance(pending, dict)
            and pending.get("status") == "active"
            and pending.get("audit_id") == request.audit_id
        ):
            self._require_knowledge_audit_verification(
                request,
                [str(item) for item in pending.get("knowledge_provenance_issue_ids", [])],
                [str(item) for item in pending.get("knowledge_provenance_error_ids", [])],
            )
        return super().commit_audit(session_id, request)
