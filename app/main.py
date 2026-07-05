from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.openapi.utils import get_openapi

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.config import get_settings
from app.models import (
    ApplyTurnResultRequest,
    ApplyTurnResultResponse,
    BootstrapPreviewRequest,
    BootstrapPreviewResponse,
    BootstrapConfirmRequest,
    BootstrapConfirmResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    TurnRequest,
    TurnResponse,
)
from app.scene_response_normalizer import normalize_scene_response
from app.session_manager import SessionManager
from app.state_updater import StateUpdater
from app.turn_processor import process_turn_debug_stub, process_turn_gpt_actions
from app.validators import validate_bootstrap_result, validate_scene_response

RAILWAY_PUBLIC_URL = "https://web-production-4310e.up.railway.app"

app = FastAPI(title="Romance Novella Generator API", version="gpt-actions-v9", servers=[{"url": RAILWAY_PUBLIC_URL, "description": "Railway production"}])


def _ensure_object_properties(schema_part: Any) -> None:
    if isinstance(schema_part, dict):
        if schema_part.get("type") == "object" and "properties" not in schema_part:
            schema_part["properties"] = {}
        for value in schema_part.values():
            _ensure_object_properties(value)
    elif isinstance(schema_part, list):
        for item in schema_part:
            _ensure_object_properties(item)


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description="Railway API for generated novella sessions: preview gate, compact turn prompt, state storage.", routes=app.routes)
    schema["servers"] = [{"url": RAILWAY_PUBLIC_URL, "description": "Railway production"}]
    for hidden_path in [
        "/api/v1/sessions/{session_id}/memory",
        "/api/v1/sessions/{session_id}/scene-contract",
        "/api/v1/sessions/{session_id}/bootstrap-result",
        "/api/v1/sessions/latest",
    ]:
        schema.get("paths", {}).pop(hidden_path, None)
    _ensure_object_properties(schema)
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _require_active_session(bundle: dict, action: str) -> None:
    status = (bundle.get("session") or {}).get("status")
    if status != "active":
        raise HTTPException(status_code=409, detail=f"Session must be active before {action}. Current status: {status}")


def _is_explicit_confirmation(text: str) -> bool:
    normalized = " ".join((text or "").strip().lower().replace("ё", "е").split())
    if not normalized:
        return False
    negative_markers = ["не подтверждаю", "не сохраняй", "не запускай", "нет", "стоп", "правки", "исправь", "измени"]
    if any(marker in normalized for marker in negative_markers):
        return False
    exact = {"подтверждаю", "ок", "okay", "ok", "сохраняй", "запускай", "подходит", "оставляем", "да"}
    if normalized.strip(".!") in exact:
        return True
    phrases = ["да подтверждаю", "все подходит", "всё подходит", "можно сохранять", "можно запускать", "оставляем так", "подтверждаю все", "подтверждаю всё"]
    return any(phrase in normalized for phrase in phrases)


@app.get("/health", operation_id="health")
def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "engine_version": settings.engine_version, "data_dir": str(settings.data_dir), "mode": "gpt_actions", "api_key_required": bool(settings.api_key)}


@app.post("/api/v1/sessions", response_model=CreateSessionResponse, dependencies=[Depends(require_api_key)], operation_id="createSession")
def create_session(request: CreateSessionRequest) -> dict:
    return SessionManager().create_session(request)


@app.get("/api/v1/start-questionnaire", dependencies=[Depends(require_api_key)], operation_id="getStartQuestionnaire")
def get_start_questionnaire() -> dict:
    path = Path(__file__).resolve().parent.parent / "prompts" / "start_questionnaire.md"
    return {"questionnaire": path.read_text(encoding="utf-8")}


@app.get("/api/v1/sessions", dependencies=[Depends(require_api_key)], operation_id="listSessions", include_in_schema=False)
def list_sessions() -> dict:
    return {"sessions": SessionManager().list_sessions()}


@app.get("/api/v1/sessions/latest", dependencies=[Depends(require_api_key)], include_in_schema=False)
def get_latest_session() -> dict:
    manager = SessionManager()
    latest = manager.get_latest_session_id(prefer_active=True)
    if not latest:
        raise HTTPException(status_code=404, detail="No sessions found")
    return {"session_id": latest, "session": manager.get_memory(latest)["session"]}


@app.get("/api/v1/sessions/{session_id}", dependencies=[Depends(require_api_key)], operation_id="getSession")
def get_session(session_id: str) -> dict:
    manager = SessionManager()
    try:
        return manager.get_memory(session_id)["session"]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/memory", dependencies=[Depends(require_api_key)], include_in_schema=False)
def get_memory(session_id: str) -> dict:
    manager = SessionManager()
    try:
        return manager.get_memory(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/sessions/{session_id}/bootstrap-result", dependencies=[Depends(require_api_key)], include_in_schema=False)
def apply_bootstrap_result_disabled(session_id: str) -> dict:
    raise HTTPException(status_code=410, detail="bootstrap-result is disabled in v9. Use bootstrap-preview, wait for explicit user confirmation, then bootstrap-confirm.")


@app.post("/api/v1/sessions/{session_id}/bootstrap-preview", response_model=BootstrapPreviewResponse, dependencies=[Depends(require_api_key)], operation_id="createBootstrapPreview")
def create_bootstrap_preview(session_id: str, request: BootstrapPreviewRequest) -> dict:
    normalized_bootstrap = normalize_bootstrap_json(request.bootstrap_json)
    errors = validate_bootstrap_result(normalized_bootstrap)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    try:
        return SessionManager().save_bootstrap_preview(session_id, normalized_bootstrap)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/api/v1/sessions/{session_id}/bootstrap-confirm", response_model=BootstrapConfirmResponse, dependencies=[Depends(require_api_key)], operation_id="confirmBootstrapPreview")
def confirm_bootstrap_preview(session_id: str, request: BootstrapConfirmRequest) -> dict:
    if not _is_explicit_confirmation(request.confirmation_text):
        raise HTTPException(status_code=409, detail="Bootstrap preview is not explicitly confirmed. Use confirmation_text such as 'подтверждаю', 'ок', 'сохраняй', 'запускай'.")
    try:
        return SessionManager().confirm_bootstrap_preview(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/scene-contract", dependencies=[Depends(require_api_key)], include_in_schema=False)
def get_scene_contract(session_id: str) -> dict:
    from app.scene_contract_builder import build_scene_contract
    manager = SessionManager()
    try:
        bundle = manager.get_memory(session_id)
        _require_active_session(bundle, "building a scene contract")
        return build_scene_contract(bundle)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/sessions/{session_id}/turn", response_model=TurnResponse, dependencies=[Depends(require_api_key)], operation_id="processTurn")
def process_turn(session_id: str, request: TurnRequest) -> dict:
    manager = SessionManager()
    try:
        bundle = manager.get_memory(session_id)
        _require_active_session(bundle, "processing a turn")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if request.mode == "debug_stub":
        result = process_turn_debug_stub(bundle, request.player_input)
        apply_result = StateUpdater(manager.storage).apply_scene_response(session_id, result["scene_response"])
        return {"session_id": session_id, "status": apply_result["status"], "scene": result["scene"], "scene_prompt": None, "diagnostics": result["diagnostics"] | {"apply_result": apply_result}}
    result = process_turn_gpt_actions(bundle, request.player_input)
    return {"session_id": session_id, "status": result["status"], "scene": None, "scene_prompt": result["scene_prompt"], "diagnostics": result["diagnostics"]}


@app.post("/api/v1/sessions/{session_id}/apply-turn-result", response_model=ApplyTurnResultResponse, dependencies=[Depends(require_api_key)], operation_id="applyTurnResult")
def apply_turn_result(session_id: str, request: ApplyTurnResultRequest) -> dict:
    manager = SessionManager()
    updater = StateUpdater(manager.storage)
    try:
        bundle = manager.get_memory(session_id)
        _require_active_session(bundle, "applying a turn result")
        normalized_scene_response = normalize_scene_response(request.scene_response, bundle)
        errors = validate_scene_response(normalized_scene_response)
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        result = updater.apply_scene_response(session_id, normalized_scene_response)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"session_id": session_id, "status": result["status"], "applied": result["applied"], "rejected": result["rejected"], "next_builder_hints": result["next_builder_hints"]}
