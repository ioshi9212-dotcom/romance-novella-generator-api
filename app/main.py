from pathlib import Path
from typing import Any
import hashlib
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.openapi.utils import get_openapi

from app.bootstrap_normalizer import normalize_bootstrap_json
from app.config import get_settings
from app.id_utils import now_iso
from app.models import ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, TurnRequest, TurnResponse
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
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description="Railway API for generated novella sessions: preview gate, compact turn prompt, rendered scene response, state storage.",
        routes=app.routes,
    )
    schema["servers"] = [{"url": RAILWAY_PUBLIC_URL, "description": "Railway production"}]
    for hidden_path in [
        "/api/v1/sessions/{session_id}/memory",
        "/api/v1/sessions/{session_id}/scene-contract",
        "/api/v1/sessions/{session_id}/bootstrap-result",
        "/api/v1/sessions/latest",
        "/api/v1/sessions",
    ]:
        # listSessions is hidden by include_in_schema=False; do not remove createSession.
        if hidden_path == "/api/v1/sessions":
            continue
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
    exact = {"подтверждаю", "ок", "okay", "ok", "сохраняй", "запускай", "подходит", "оставляем", "да", "начинаем", "начнем", "начнём", "поехали"}
    if normalized.strip(".!") in {item.replace("ё", "е") for item in exact}:
        return True
    phrases = ["да подтверждаю", "все подходит", "всё подходит", "можно сохранять", "можно запускать", "оставляем так", "подтверждаю все", "подтверждаю всё"]
    return any(phrase.replace("ё", "е") in normalized for phrase in phrases)

def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _new_turn_id() -> str:
    return "turn_" + uuid.uuid4().hex[:12]

def _save_pending_turn(manager: SessionManager, session_id: str, player_input: str, expected_turn_number: int) -> dict[str, Any]:
    pending = {
        "turn_id": _new_turn_id(),
        "status": "pending",
        "player_input": player_input,
        "player_input_sha256": _hash_text(player_input),
        "expected_turn_number": expected_turn_number,
        "created_at": now_iso(),
    }
    manager.storage.write_json(session_id, "pending_turn.json", pending)
    return pending

def _load_pending_turn(manager: SessionManager, session_id: str) -> dict[str, Any]:
    pending = manager.storage.read_json(session_id, "pending_turn.json", default={})
    return pending if isinstance(pending, dict) else {}

def _extract_turn_id_from_scene_response(scene_response: dict[str, Any]) -> str | None:
    """Compatibility layer for old Custom GPT Actions imports.

    Some already-imported Actions schemas expose only `scene_response` and reject a
    top-level `turn_id` parameter. In that case GPT may place the id inside the
    scene_response object, or omit it entirely even though the backend has a
    single pending turn. This helper lets the backend stay strict about pending
    turn matching without breaking old Action schemas.
    """
    if not isinstance(scene_response, dict):
        return None
    for key in ("turn_id", "_turn_id", "pending_turn_id"):
        value = scene_response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    diagnostics = scene_response.get("diagnostics")
    if isinstance(diagnostics, dict):
        value = diagnostics.get("turn_id") or diagnostics.get("pending_turn_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = scene_response.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("turn_id") or metadata.get("pending_turn_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _require_pending_turn_match(manager: SessionManager, session_id: str, request_turn_id: str | None, normalized_scene_response: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    pending = _load_pending_turn(manager, session_id)
    if not pending or not pending.get("turn_id"):
        raise HTTPException(status_code=409, detail="No pending turn. Call processTurn before applyTurnResult.")
    if pending.get("status") == "applied":
        raise HTTPException(status_code=409, detail="This turn was already applied. Call processTurn for the next player input.")

    # Backward-compatible fallback: if the imported Action cannot pass top-level
    # turn_id, bind to the single pending turn. The player_input check below still
    # prevents applying a scene generated from stale context.
    if not request_turn_id:
        request_turn_id = str(pending.get("turn_id") or "").strip()

    if request_turn_id != pending.get("turn_id"):
        raise HTTPException(status_code=409, detail="Stale or mismatched turn_id. Do not apply a scene_response from an old scene_prompt.")

    expected_input = str(pending.get("player_input") or "").strip()
    actual_input = str(normalized_scene_response.get("player_input") or "").strip()
    if not actual_input:
        raise HTTPException(status_code=422, detail="scene_response.player_input is required and must match the pending turn input.")
    if actual_input != expected_input:
        raise HTTPException(status_code=409, detail="scene_response.player_input does not match the pending processTurn input.")

    current_turn_number = int(((bundle.get("current_state") or {}).get("turn_number", 0)) or 0)
    expected_turn_number = int(pending.get("expected_turn_number") or (current_turn_number + 1))
    if expected_turn_number != current_turn_number + 1:
        raise HTTPException(status_code=409, detail="Pending turn number is stale. Call processTurn again.")
    return pending

def _mark_pending_turn_applied(manager: SessionManager, session_id: str, pending: dict[str, Any]) -> None:
    manager.storage.write_json(session_id, "pending_turn.json", {**pending, "status": "applied", "applied_at": now_iso()})

@app.get("/health", operation_id="health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "engine_version": settings.engine_version,
        "data_dir": str(settings.data_dir),
        "mode": "gpt_actions",
        "api_key_required": bool(settings.api_key),
    }

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
    try:
        return SessionManager().get_memory(session_id)["session"]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get("/api/v1/sessions/{session_id}/memory", dependencies=[Depends(require_api_key)], include_in_schema=False)
def get_memory(session_id: str) -> dict:
    try:
        return SessionManager().get_memory(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.post("/api/v1/sessions/{session_id}/bootstrap-result", dependencies=[Depends(require_api_key)], include_in_schema=False)
def apply_bootstrap_result_disabled(session_id: str) -> dict:
    raise HTTPException(status_code=410, detail="bootstrap-result is disabled in v9. Use bootstrap-preview and bootstrap-confirm.")

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
        raise HTTPException(status_code=409, detail="Bootstrap preview is not explicitly confirmed.")
    try:
        return SessionManager().confirm_bootstrap_preview(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

@app.get("/api/v1/sessions/{session_id}/scene-contract", dependencies=[Depends(require_api_key)], include_in_schema=False)
def get_scene_contract(session_id: str) -> dict:
    from app.scene_contract_builder import build_scene_contract
    try:
        manager = SessionManager()
        bundle = manager.get_memory(session_id)
        _require_active_session(bundle, "building a scene contract")
        return build_scene_contract(bundle)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.post("/api/v1/sessions/{session_id}/turn", response_model=TurnResponse, dependencies=[Depends(require_api_key)], operation_id="processTurn")
def process_turn(session_id: str, request: TurnRequest) -> dict:
    player_input = (request.player_input or "").strip()
    if not player_input:
        raise HTTPException(status_code=422, detail="player_input is empty; do not write a scene from stale context.")

    manager = SessionManager()
    try:
        bundle = manager.get_memory(session_id)
        _require_active_session(bundle, "processing a turn")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if request.mode == "debug_stub":
        result = process_turn_debug_stub(bundle, player_input)
        apply_result = StateUpdater(manager.storage).apply_scene_response(session_id, result["scene_response"])
        return {
            "session_id": session_id,
            "status": apply_result["status"],
            "scene": result["scene"],
            "scene_prompt": None,
            "turn_id": None,
            "expected_turn_number": apply_result.get("next_builder_hints", {}).get("maintenance", {}).get("last_saved_turn_number"),
            "diagnostics": result["diagnostics"] | {"apply_result": apply_result},
        }

    expected_turn_number = int(((bundle.get("current_state") or {}).get("turn_number", 0)) or 0) + 1
    pending = _save_pending_turn(manager, session_id, player_input, expected_turn_number)
    result = process_turn_gpt_actions(bundle, player_input)
    diagnostics = result["diagnostics"] | {
        "turn_id": pending["turn_id"],
        "expected_turn_number": expected_turn_number,
        "next_required_action": "Generate scene_response, then call applyTurnResult with this turn_id.",
    }
    return {
        "session_id": session_id,
        "status": result["status"],
        "scene": None,
        "scene_prompt": result["scene_prompt"],
        "turn_id": pending["turn_id"],
        "expected_turn_number": expected_turn_number,
        "diagnostics": diagnostics,
    }

@app.post("/api/v1/sessions/{session_id}/apply-turn-result", response_model=ApplyTurnResultResponse, dependencies=[Depends(require_api_key)], operation_id="applyTurnResult")
def apply_turn_result(session_id: str, request: ApplyTurnResultRequest) -> dict:
    manager = SessionManager()
    updater = StateUpdater(manager.storage)
    try:
        bundle = manager.get_memory(session_id)
        _require_active_session(bundle, "applying a turn result")
        raw_scene_response = dict(request.scene_response or {})
        compatible_turn_id = request.turn_id or _extract_turn_id_from_scene_response(raw_scene_response)
        normalized_scene_response = normalize_scene_response(raw_scene_response, bundle)
        pending = _require_pending_turn_match(manager, session_id, compatible_turn_id, normalized_scene_response, bundle)
        errors = validate_scene_response(normalized_scene_response)
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        result = updater.apply_scene_response(session_id, normalized_scene_response)
        _mark_pending_turn_applied(manager, session_id, pending)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    rendered_text = normalized_scene_response["scene"]["rendered_text"]
    return {
        "session_id": session_id,
        "status": result["status"],
        "message_to_user": rendered_text,
        "rendered_text": rendered_text,
        "must_show_to_user": True,
        "applied": result["applied"],
        "rejected": result["rejected"],
        "next_builder_hints": result["next_builder_hints"],
    }

from app.novella_openapi_actions import install_openapi_actions
install_openapi_actions(app)
