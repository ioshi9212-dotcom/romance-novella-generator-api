"""Railway production entrypoint.

The public API/OpenAPI remains defined in app.main. Production swaps only the service
implementation so interrupted packet reads can resume instead of deadlocking a chat.
"""

from app.main import app, settings
from app.stable_runtime_service import StableRuntimeNovellaService

app.state.service = StableRuntimeNovellaService(settings)
