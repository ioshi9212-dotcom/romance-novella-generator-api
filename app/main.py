import hashlib
import hmac
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.enhanced_writer_service import EnhancedWriterNovellaService
from app.models import (
    ChronologyPageResponse,
    CommitAuditRequest,
    CommitAuditResponse,
    CommitTurnRequest,
    CommitTurnResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    PacketChunkResponse,
    SceneCharacterBundleChunkResponse,
    SceneCharacterBundleRequest,
    TurnPacketRequest,
)
from app.service import NovellaService, ServiceError
from app.session_transfer import (
    FinalizeSessionTransferResponse,
    StartSessionTransferRequest,
    StartSessionTransferResponse,
    UploadSessionTransferChunkRequest,
    UploadSessionTransferChunkResponse,
    finalize_session_transfer,
    start_session_transfer,
    upload_session_transfer_chunk,
)

settings = get_settings()
app = FastAPI(
    title="Interactive Novella State Runtime",
    version="1.0.0",
    description=(
        "Session-scoped Railway storage for a Custom GPT visual novella. "
        "The API stores state and never calls an OpenAI model."
    ),
    servers=[{"url": settings.public_base_url, "description": "Railway production"}],
)
app.state.service = EnhancedWriterNovellaService(settings)

# One-time recovery gate. Only the SHA-256 digest is committed; the secret token itself
# never lives in the public repository. This route is intentionally excluded from OpenAPI.
_RECOVERY_TOKEN_SHA256 = "6297d6aa76d4489b58f299e3bbd3e546feee74f9b6c35189f597a3a20d8ddf9a"


def service_for(request: Request) -> NovellaService:
    return request.app.state.service


@app.exception_handler(ServiceError)
async def handle_service_error(_request: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.detail}},
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return useful validation failures without echoing the submitted novella."""
    validation_errors = exc.errors()
    issues = [
        {
            "location": ".".join(str(part) for part in error.get("loc", ())),
            "message": str(error.get("msg", "Invalid value"))[:1000],
            "type": str(error.get("type", "validation_error"))[:200],
        }
        for error in validation_errors[:50]
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "REQUEST_VALIDATION_FAILED",
                "message": "The request does not match the required schema.",
                "issues": issues,
                "truncated": len(validation_errors) > len(issues),
            }
        },
    )


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


def _recovery_token_ok(token: str) -> bool:
    supplied_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(supplied_digest, _RECOVERY_TOKEN_SHA256)


@app.get("/internal/recover-session", include_in_schema=False, response_model=None)
def recover_session(
    request: Request,
    token: str = Query(min_length=16),
    pov_name: str | None = Query(default=None, min_length=1, max_length=120),
    last_completed_turn: int | None = Query(default=None, ge=0),
    turn_number: int | None = Query(default=None, ge=1),
    contains: str | None = Query(default=None, min_length=1, max_length=300),
    title_contains: str | None = Query(default=None, min_length=1, max_length=160),
) -> Any:
    """Recover a lost session by metadata and/or actual stored turn content."""

    if not _recovery_token_ok(token):
        return JSONResponse(
            status_code=403,
            content={"error": {"code": "RECOVERY_FORBIDDEN", "message": "Invalid token"}},
        )

    service = service_for(request)
    wanted_name = pov_name.strip().casefold() if pov_name else None
    wanted_title = title_contains.strip().casefold() if title_contains else None
    terms = [
        part.strip().casefold()
        for part in (contains or "").split("|")
        if part.strip()
    ]
    matches: list[dict[str, Any]] = []

    for session_dir in service.storage.sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        session_id = session_dir.name
        try:
            session = service.storage.read_json(session_id, "session.json", default={})
            if not isinstance(session, dict):
                continue
            if (
                last_completed_turn is not None
                and int(session.get("last_completed_turn", -1)) != last_completed_turn
            ):
                continue

            novel = service.storage.read_json(session_id, "state/novel.json", default={})
            if not isinstance(novel, dict):
                novel = {}
            title = str(novel.get("title", ""))
            if wanted_title and wanted_title not in title.casefold():
                continue

            pov_character_id = str(novel.get("pov_character_id", ""))
            pov_display_name = ""
            if pov_character_id:
                card = service.storage.read_json(
                    session_id,
                    f"characters/{pov_character_id}/card.json",
                    default={},
                )
                identity = card.get("identity", {}) if isinstance(card, dict) else {}
                pov_display_name = str(identity.get("name", "")).strip()
            if wanted_name and wanted_name not in pov_display_name.casefold():
                continue

            matched_turns: list[dict[str, Any]] = []
            if turn_number is not None:
                turn_numbers = [turn_number]
            elif terms:
                turns_dir = session_dir / "turns"
                turn_numbers = []
                if turns_dir.is_dir():
                    for turn_path in sorted(turns_dir.glob("turn_*.json")):
                        stem = turn_path.stem.removeprefix("turn_")
                        if stem.isdigit():
                            turn_numbers.append(int(stem))
            else:
                turn_numbers = []

            for candidate_turn in turn_numbers:
                turn = service.storage.read_json(
                    session_id,
                    f"turns/turn_{candidate_turn:06d}.json",
                    default={},
                )
                if not isinstance(turn, dict) or not turn:
                    continue
                haystack = "\n".join(
                    str(turn.get(key, ""))
                    for key in ("scene_output", "summary", "player_input", "story_datetime", "scene_id")
                ).casefold()
                if terms and not all(term in haystack for term in terms):
                    continue
                scene_output = str(turn.get("scene_output", ""))
                matched_turns.append(
                    {
                        "turn_number": int(turn.get("turn_number", candidate_turn)),
                        "story_datetime": turn.get("story_datetime"),
                        "scene_id": turn.get("scene_id"),
                        "summary": str(turn.get("summary", ""))[:600],
                        "scene_preview": scene_output[:900],
                    }
                )

            if (turn_number is not None or terms) and not matched_turns:
                continue

            matches.append(
                {
                    "session_id": session_id,
                    "title": title,
                    "pov_character_id": pov_character_id,
                    "pov_name": pov_display_name,
                    "last_completed_turn": int(session.get("last_completed_turn", 0)),
                    "updated_at": session.get("updated_at"),
                    "audit_required": bool(session.get("audit_required", False)),
                    "matched_turns": matched_turns[:20],
                }
            )
        except (FileNotFoundError, OSError, TypeError, ValueError):
            continue

    matches.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {"count": len(matches), "matches": matches[:30]}


@app.post(
    "/api/v1/sessions",
    operation_id="createSession",
    response_model=CreateSessionResponse,
    summary="Legacy direct creation of one novella session",
    description=(
        "Kept only for already-installed legacy Action schemas. Current runtime contract 2.0 "
        "must use startSessionTransfer, upload every chunk, and finalizeSessionTransfer so a "
        "large setup cannot be silently abbreviated."
    ),
)
def create_session(payload: CreateSessionRequest, request: Request) -> dict[str, Any]:
    if payload.runtime_contract_version == "2.0":
        raise ServiceError(
            409,
            "SESSION_TRANSFER_REQUIRED",
            "Do not send current novella setup in one createSession call. Serialize the full "
            "CreateSessionRequest, call startSessionTransfer, upload every ordered chunk, then "
            "call finalizeSessionTransfer. Do not shorten any confirmed data.",
        )
    return service_for(request).create_session(payload)


@app.post(
    "/api/v1/session-transfers",
    operation_id="startSessionTransfer",
    response_model=StartSessionTransferResponse,
    summary="Start verified transfer of a complete confirmed novella",
    description=(
        "For runtime contract 2.0, serialize one complete CreateSessionRequest as JSON and split "
        "the exact text into ordered chunks no larger than max_chunk_chars."
    ),
)
def start_transfer(
    payload: StartSessionTransferRequest, request: Request
) -> dict[str, Any]:
    return start_session_transfer(service_for(request), payload)


@app.post(
    "/api/v1/session-transfers/{transfer_id}/chunks",
    operation_id="uploadSessionTransferChunk",
    response_model=UploadSessionTransferChunkResponse,
    summary="Store the next exact piece of the confirmed novella",
    description=(
        "Upload every substring in order from chunk_index 0. Identical retries are safe; skipped "
        "or changed chunks are rejected."
    ),
)
def upload_transfer_chunk(
    transfer_id: str,
    payload: UploadSessionTransferChunkRequest,
    request: Request,
) -> dict[str, Any]:
    return upload_session_transfer_chunk(service_for(request), transfer_id, payload)


@app.post(
    "/api/v1/session-transfers/{transfer_id}/finalize",
    operation_id="finalizeSessionTransfer",
    response_model=FinalizeSessionTransferResponse,
    summary="Validate, persist and verify the complete novella",
    description=(
        "Only this operation creates a runtime-contract 2.0 session. It reassembles the exact "
        "JSON, rejects abbreviated state, atomically stores every document, and verifies them "
        "before returning session_id."
    ),
)
def finalize_transfer(transfer_id: str, request: Request) -> dict[str, Any]:
    return finalize_session_transfer(service_for(request), transfer_id)


@app.post(
    "/api/v1/sessions/{session_id}/turn-packet",
    operation_id="getTurnPacket",
    response_model=PacketChunkResponse,
    summary="Get the authoritative packet required to write one scene",
    description=(
        "Reads the exact session state, rules, builder, chronology and current unaudited turns. "
        "If the 15-turn audit is due, this action returns AUDIT_REQUIRED and no scene may be written."
    ),
)
def get_turn_packet(
    session_id: str, payload: TurnPacketRequest, request: Request
) -> dict[str, Any]:
    return service_for(request).get_turn_packet(session_id, payload)


@app.get(
    "/api/v1/sessions/{session_id}/turn-packets/{packet_id}/chunks/{chunk_index}",
    operation_id="getTurnPacketChunk",
    response_model=PacketChunkResponse,
    summary="Read another ordered chunk of a turn packet",
)
def get_turn_packet_chunk(
    session_id: str,
    packet_id: str,
    chunk_index: int,
    request: Request,
) -> dict[str, Any]:
    return service_for(request).get_turn_packet_chunk(
        session_id, packet_id, chunk_index
    )


@app.post(
    "/api/v1/sessions/{session_id}/turn-packets/{packet_id}/scene-characters/{character_id}/bundle",
    operation_id="getSceneCharacterBundle",
    response_model=SceneCharacterBundleChunkResponse,
    summary="Load one known offscreen character who will enter the pending scene",
    description=(
        "Use only after every turn-packet chunk was read and the story now causes this "
        "already-known character to physically enter the scene. Returns only that character's "
        "complete card, current state, knowledge and directional relationships. Read every "
        "bundle chunk before commitTurn."
    ),
)
def get_scene_character_bundle(
    session_id: str,
    packet_id: str,
    character_id: str,
    payload: SceneCharacterBundleRequest,
    request: Request,
) -> dict[str, Any]:
    return service_for(request).get_scene_character_bundle(
        session_id, packet_id, character_id, payload
    )


@app.get(
    "/api/v1/sessions/{session_id}/turn-packets/{packet_id}/scene-character-bundles/{bundle_id}/chunks/{chunk_index}",
    operation_id="getSceneCharacterBundleChunk",
    response_model=SceneCharacterBundleChunkResponse,
    summary="Read the next ordered chunk of one entering character's dossier",
    description=(
        "Read in strict order until all_chunks_delivered is true. commitTurn remains blocked "
        "while any requested scene-character bundle is incomplete."
    ),
)
def get_scene_character_bundle_chunk(
    session_id: str,
    packet_id: str,
    bundle_id: str,
    chunk_index: int,
    request: Request,
) -> dict[str, Any]:
    return service_for(request).get_scene_character_bundle_chunk(
        session_id, packet_id, bundle_id, chunk_index
    )


@app.post(
    "/api/v1/sessions/{session_id}/turns/commit",
    operation_id="commitTurn",
    response_model=CommitTurnResponse,
    summary="Atomically commit the generated scene and every state change",
    description=(
        "Must succeed before the scene is shown to the player. The scene, chronology, state, "
        "character knowledge and relationships are stored in one session transaction."
    ),
)
def commit_turn(
    session_id: str, payload: CommitTurnRequest, request: Request
) -> dict[str, Any]:
    return service_for(request).commit_turn(session_id, payload)


@app.get(
    "/api/v1/sessions/{session_id}/audit-packet",
    operation_id="getAuditPacket",
    response_model=PacketChunkResponse,
    summary="Get the mandatory packet for the next 15-turn audit",
    description=(
        "Returns all 15 complete current turn revisions, the full compact chronology and current "
        "state. The next scene remains blocked until commitAudit succeeds."
    ),
)
def get_audit_packet(session_id: str, request: Request) -> dict[str, Any]:
    return service_for(request).get_audit_packet(session_id)


@app.get(
    "/api/v1/sessions/{session_id}/audit-packets/{packet_id}/chunks/{chunk_index}",
    operation_id="getAuditPacketChunk",
    response_model=PacketChunkResponse,
    summary="Read another ordered chunk of an audit packet",
)
def get_audit_packet_chunk(
    session_id: str,
    packet_id: str,
    chunk_index: int,
    request: Request,
) -> dict[str, Any]:
    return service_for(request).get_audit_packet_chunk(
        session_id, packet_id, chunk_index
    )


@app.post(
    "/api/v1/sessions/{session_id}/audits/commit",
    operation_id="commitAudit",
    response_model=CommitAuditResponse,
    summary="Commit a completed 15-turn audit and release the scene gate",
    description=(
        "All checklist fields must be true. Repairs, compaction and chronology corrections are "
        "stored atomically before another turn packet is allowed."
    ),
)
def commit_audit(
    session_id: str, payload: CommitAuditRequest, request: Request
) -> dict[str, Any]:
    return service_for(request).commit_audit(session_id, payload)


@app.get(
    "/api/v1/sessions/{session_id}/chronology",
    operation_id="getChronologyPage",
    response_model=ChronologyPageResponse,
    summary="Read the session chronology in order",
)
def get_chronology_page(
    session_id: str,
    request: Request,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    include_inactive: bool = Query(
        default=False,
        description="Include superseded and hidden source events for diagnostics only.",
    ),
) -> dict[str, Any]:
    return service_for(request).get_chronology_page(
        session_id, cursor, limit, include_inactive
    )


def _ensure_object_properties(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object" and "properties" not in value:
            value["properties"] = {}
        for child in value.values():
            _ensure_object_properties(child)
    elif isinstance(value, list):
        for child in value:
            _ensure_object_properties(child)


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["servers"] = [
        {"url": settings.public_base_url, "description": "Railway production"}
    ]
    schema["security"] = []
    schema["components"] = schema.get("components", {})
    schema["components"].pop("securitySchemes", None)
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict):
                operation["security"] = []
    _ensure_object_properties(schema)
    create_schema = schema.get("components", {}).get("schemas", {}).get(
        "CreateSessionRequest", {}
    )
    required = create_schema.setdefault("required", [])
    for field_name in ("runtime_contract_version", "setup_source", "director_plan"):
        if field_name not in required:
            required.append(field_name)
    version_property = create_schema.get("properties", {}).get(
        "runtime_contract_version"
    )
    if isinstance(version_property, dict):
        description = version_property.get("description")
        version_property.clear()
        version_property.update({"type": "string", "enum": ["2.0"]})
        if description:
            version_property["description"] = description
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
