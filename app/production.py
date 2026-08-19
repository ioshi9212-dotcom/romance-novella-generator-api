"""Railway production entrypoint.

The public API/OpenAPI remains defined in app.main. Production swaps only the service
implementation so interrupted packet reads can resume instead of deadlocking a chat.
"""

from typing import Any

from fastapi.responses import JSONResponse

from app.main import _recovery_token_ok, app, settings
from app.runtime_integrity import audit_runtime
from app.stable_runtime_service import StableRuntimeNovellaService

app.state.service = StableRuntimeNovellaService(settings)


@app.get("/internal/runtime-audit", include_in_schema=False, response_model=None)
def runtime_audit(
    token: str,
    summary_only: bool = False,
    knowledge_only: bool = False,
    session_id: str | None = None,
) -> Any:
    """Protected mechanical audit of every Railway novella session."""

    if not _recovery_token_ok(token):
        return JSONResponse(
            status_code=403,
            content={"error": {"code": "RECOVERY_FORBIDDEN", "message": "Invalid token"}},
        )

    result = audit_runtime(app.state.service)
    sessions = list(result.get("sessions", []))
    if session_id:
        sessions = [item for item in sessions if item.get("session_id") == session_id]
    if knowledge_only:
        sessions = [
            item
            for item in sessions
            if int(item.get("knowledge_provenance", {}).get("issue_count", 0) or 0) > 0
        ]

    if summary_only:
        return {
            "summary": result.get("summary", {}),
            "packet_chunk_chars": result.get("packet_chunk_chars"),
            "matched_session_count": len(sessions),
            "sessions": [
                {
                    "session_id": item.get("session_id"),
                    "title": item.get("title"),
                    "pov_name": item.get("pov_name"),
                    "last_completed_turn": item.get("last_completed_turn"),
                    "last_audited_turn": item.get("last_audited_turn"),
                    "audit_required": item.get("audit_required"),
                    "knowledge_issue_count": item.get("knowledge_provenance", {}).get(
                        "issue_count", 0
                    ),
                    "knowledge_error_count": item.get("knowledge_provenance", {}).get(
                        "error_count", 0
                    ),
                    "runtime_errors": item.get("errors", []),
                }
                for item in sessions
            ],
        }

    result["sessions"] = sessions
    result["matched_session_count"] = len(sessions)
    return result
