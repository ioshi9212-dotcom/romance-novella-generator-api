from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app import bootstrap as bootstrap_service
from app import sessions as session_service
from app import turns as turn_service
from app.config import ACTION_TOKEN, ENVIRONMENT, ROOT_DIR, ensure_data_dirs
from app.models import (
    AbortTurnRequest,
    AbortTurnResponse,
    BootstrapPartRequest,
    BootstrapSaveResponse,
    BootstrapValidationResponse,
    CommitTurnRequest,
    CreateSessionRequest,
    PrepareTurnRequest,
    PrepareTurnResponse,
    QuestionnaireRequest,
    SessionSummary,
    TurnReceipt,
)


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str


bearer = HTTPBearer(auto_error=False)


def require_action_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    if not ACTION_TOKEN:
        raise HTTPException(status_code=503, detail="ACTION_TOKEN is not configured")
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials, ACTION_TOKEN)
    ):
        raise HTTPException(status_code=401, detail="Invalid action token")


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_data_dirs()
    yield


app = FastAPI(
    title="Novel Runtime API",
    version="1.0.0",
    description="Persistent session runtime for a Custom GPT novella generator.",
    docs_url=None if ENVIRONMENT == "production" else "/docs",
    redoc_url=None if ENVIRONMENT == "production" else "/redoc",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    ensure_data_dirs()
    return HealthResponse(
        status="ok",
        service="novel-runtime",
        environment=ENVIRONMENT,
    )


@app.get("/openapi-actions.yaml", response_class=PlainTextResponse, include_in_schema=False)
def action_schema() -> PlainTextResponse:
    content = (ROOT_DIR / "openapi-actions.yaml").read_text(encoding="utf-8")
    return PlainTextResponse(content=content, media_type="application/yaml")


auth = [Depends(require_action_token)]


@app.post("/v1/sessions", response_model=SessionSummary, dependencies=auth, tags=["sessions"])
def create_session(request: CreateSessionRequest) -> SessionSummary:
    return session_service.create_session(request)


@app.get("/v1/sessions", response_model=list[SessionSummary], dependencies=auth, tags=["sessions"])
def list_sessions(limit: int = Query(default=20, ge=1, le=50)) -> list[SessionSummary]:
    return session_service.list_sessions(limit)


@app.get(
    "/v1/sessions/{session_id}",
    response_model=SessionSummary,
    dependencies=auth,
    tags=["sessions"],
)
def get_session_status(session_id: str) -> SessionSummary:
    return session_service.get_session_summary(session_id)


@app.put(
    "/v1/sessions/{session_id}/questionnaire",
    response_model=SessionSummary,
    dependencies=auth,
    tags=["bootstrap"],
)
def save_questionnaire(session_id: str, request: QuestionnaireRequest) -> SessionSummary:
    return bootstrap_service.save_questionnaire(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/bootstrap/parts",
    response_model=BootstrapSaveResponse,
    dependencies=auth,
    tags=["bootstrap"],
)
def save_bootstrap_part(
    session_id: str,
    request: BootstrapPartRequest,
) -> BootstrapSaveResponse:
    return bootstrap_service.save_bootstrap_part(session_id, request)


@app.post(
    "/v1/sessions/{session_id}/bootstrap/validate",
    response_model=BootstrapValidationResponse,
    dependencies=auth,
    tags=["bootstrap"],
)
def validate_bootstrap(session_id: str) -> BootstrapValidationResponse:
    return bootstrap_service.validate_session_bootstrap(session_id)


@app.post(
    "/v1/sessions/{session_id}/bootstrap/confirm",
    response_model=SessionSummary,
    dependencies=auth,
    tags=["bootstrap"],
)
def confirm_bootstrap(session_id: str) -> SessionSummary:
    return bootstrap_service.confirm_bootstrap(session_id)


@app.post(
    "/v1/sessions/{session_id}/turns",
    response_model=PrepareTurnResponse,
    dependencies=auth,
    tags=["turns"],
)
def prepare_turn(session_id: str, request: PrepareTurnRequest) -> PrepareTurnResponse:
    return turn_service.prepare_turn(session_id, request)


@app.get(
    "/v1/sessions/{session_id}/turns/{turn_id}/chunks/{chunk_index}",
    response_model=PrepareTurnResponse,
    dependencies=auth,
    tags=["turns"],
)
def get_turn_chunk(
    session_id: str,
    turn_id: str,
    chunk_index: int,
) -> PrepareTurnResponse:
    return turn_service.get_turn_chunk(session_id, turn_id, chunk_index)


@app.post(
    "/v1/sessions/{session_id}/turns/{turn_id}/commit",
    response_model=TurnReceipt,
    dependencies=auth,
    tags=["turns"],
)
def commit_turn(
    session_id: str,
    turn_id: str,
    request: CommitTurnRequest,
) -> TurnReceipt:
    return turn_service.commit_turn(session_id, turn_id, request)


@app.post(
    "/v1/sessions/{session_id}/turns/{turn_id}/abort",
    response_model=AbortTurnResponse,
    dependencies=auth,
    tags=["turns"],
)
def abort_turn(
    session_id: str,
    turn_id: str,
    request: AbortTurnRequest,
) -> AbortTurnResponse:
    return turn_service.abort_turn(session_id, turn_id, request.reason)
