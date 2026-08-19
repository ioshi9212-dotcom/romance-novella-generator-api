"""Railway entrypoint for the isolated chat-transfer fix.

The public FastAPI app and OpenAPI remain exactly the same as app.main. Only the service
implementation is swapped so an already-active uncommitted packet can be replayed from chunk zero.
"""

from app.main import app, settings
from app.resumable_session_service import ResumableSessionNovellaService

app.state.service = ResumableSessionNovellaService(settings)
