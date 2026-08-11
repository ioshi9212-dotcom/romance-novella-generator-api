from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.config import get_settings
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
from app.writer_service import WriterFirstNovellaService

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
app.state.service = WriterFirstNovellaService(settings)


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
    """Return useful validation failures without echoing the submitted novella.

    Pydantic includes the rejected input subtree in every error by default. A
    model-level error can therefore repeat an entire character card and make a
    GPT Action response larger than the connector limit.
    """
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


@app.post(
    "/api/v1/sessions",
    operation_id="createSession",
    response_model=CreateSessionResponse,
    summary="Create one new novella session after player confirmation",
    description=(
        "Call only after the player explicitly confirms the setup preview. Returns a random "
        "session_id that is mandatory for every later action."
    ),
)
def create_session(payload: CreateSessionRequest, request: Request) -> dict[str, Any]:
    return service_for(request).create_session(payload)


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
    # The deployed server keeps accepting legacy createSession payloads, but every
    # newly imported Action schema must opt into the current contract and provide a
    # substantive director plan. This separates backwards compatibility from the
    # guarantees advertised to the current Custom GPT.
    create_schema = schema.get("components", {}).get("schemas", {}).get(
        "CreateSessionRequest", {}
    )
    required = create_schema.setdefault("required", [])
    for field_name in ("runtime_contract_version", "director_plan"):
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
