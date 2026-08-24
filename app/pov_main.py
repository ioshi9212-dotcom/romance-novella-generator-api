from app.main import app, settings
from app.pov_stable_service import PovStableWriterService


# Branch-only entrypoint: keep the production app/routes unchanged and swap only
# the service implementation used by this experimental deployment.
app.state.service = PovStableWriterService(settings)
