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
def runtime_audit(token: str) -> Any:
    """Protected mechanical audit of every Railway novella session."""

    if not _recovery_token_ok(token):
        return JSONResponse(
            status_code=403,
            content={"error": {"code": "RECOVERY_FORBIDDEN", "message": "Invalid token"}},
        )
    return audit_runtime(app.state.service)
