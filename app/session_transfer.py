import json
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.models import CreateSessionRequest
from app.service import NovellaService, ServiceError, _new_id, now_iso
from app.storage import safe_component


MAX_TRANSFER_CHUNKS = 256
MAX_TRANSFER_CHUNK_CHARS = 8_000
MAX_TRANSFER_TOTAL_CHARS = 2_000_000


class StartSessionTransferRequest(BaseModel):
    total_chunks: int = Field(ge=1, le=MAX_TRANSFER_CHUNKS)
    payload_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class StartSessionTransferResponse(BaseModel):
    transfer_id: str
    total_chunks: int
    max_chunk_chars: int
    next_chunk_index: int
    next_required_action: str


class UploadSessionTransferChunkRequest(BaseModel):
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=MAX_TRANSFER_CHUNK_CHARS)


class UploadSessionTransferChunkResponse(BaseModel):
    transfer_id: str
    accepted_chunk_index: int
    received_chunks: int
    total_chunks: int
    complete: bool
    next_chunk_index: int | None
    next_required_action: str


class FinalizeSessionTransferResponse(BaseModel):
    transfer_id: str
    session_id: str
    status: str
    state_revision: int
    next_turn_number: int
    cycle_position: int
    next_required_action: str


def _transfer_root(service: NovellaService) -> Path:
    root = service.settings.data_dir / "session_transfers"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _transfer_dir(service: NovellaService, transfer_id: str) -> Path:
    safe_id = safe_component(transfer_id, "transfer_id")
    root = _transfer_root(service).resolve()
    path = (root / safe_id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ServiceError(400, "INVALID_TRANSFER_ID", "Unsafe transfer_id") from exc
    return path


def _read_meta(service: NovellaService, transfer_id: str) -> tuple[Path, dict[str, Any]]:
    path = _transfer_dir(service, transfer_id)
    meta_path = path / "meta.json"
    if not meta_path.exists():
        raise ServiceError(404, "TRANSFER_NOT_FOUND", "Session transfer was not found")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServiceError(500, "TRANSFER_CORRUPT", "Transfer metadata is invalid") from exc
    if not isinstance(meta, dict) or meta.get("transfer_id") != transfer_id:
        raise ServiceError(500, "TRANSFER_CORRUPT", "Transfer metadata is invalid")
    return path, meta


def _write_meta(service: NovellaService, path: Path, meta: dict[str, Any]) -> None:
    service.storage._write_text_atomic(
        path / "meta.json",
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
    )


def start_session_transfer(
    service: NovellaService, request: StartSessionTransferRequest
) -> dict[str, Any]:
    root = _transfer_root(service)
    for _ in range(10):
        transfer_id = _new_id("transfer", 18)
        path = root / transfer_id
        try:
            path.mkdir(parents=False, exist_ok=False)
            break
        except FileExistsError:
            continue
    else:  # pragma: no cover
        raise ServiceError(500, "TRANSFER_ID_FAILURE", "Could not allocate transfer_id")

    (path / "chunks").mkdir(parents=False, exist_ok=False)
    meta = {
        "transfer_id": transfer_id,
        "status": "uploading",
        "total_chunks": request.total_chunks,
        "payload_sha256": request.payload_sha256,
        "received": {},
        "total_chars": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    _write_meta(service, path, meta)
    return {
        "transfer_id": transfer_id,
        "total_chunks": request.total_chunks,
        "max_chunk_chars": MAX_TRANSFER_CHUNK_CHARS,
        "next_chunk_index": 0,
        "next_required_action": "Call uploadSessionTransferChunk with chunk_index 0.",
    }


def upload_session_transfer_chunk(
    service: NovellaService,
    transfer_id: str,
    request: UploadSessionTransferChunkRequest,
) -> dict[str, Any]:
    path, meta = _read_meta(service, transfer_id)
    if meta.get("status") == "complete":
        raise ServiceError(409, "TRANSFER_ALREADY_FINALIZED", "Transfer is already finalized")
    if meta.get("status") != "uploading":
        raise ServiceError(409, "TRANSFER_NOT_UPLOADABLE", "Transfer is not accepting chunks")

    total_chunks = int(meta["total_chunks"])
    if request.chunk_index >= total_chunks:
        raise ServiceError(
            422,
            "TRANSFER_CHUNK_OUT_OF_RANGE",
            f"chunk_index must be between 0 and {total_chunks - 1}",
        )

    digest = sha256(request.content.encode("utf-8")).hexdigest()
    received = meta.setdefault("received", {})
    key = str(request.chunk_index)
    existing = received.get(key)
    chunk_path = path / "chunks" / f"{request.chunk_index:04d}.txt"
    if existing is not None:
        if existing.get("sha256") != digest:
            raise ServiceError(
                409,
                "TRANSFER_CHUNK_CONFLICT",
                "This chunk_index was already uploaded with different content",
            )
    else:
        new_total = int(meta.get("total_chars", 0)) + len(request.content)
        if new_total > MAX_TRANSFER_TOTAL_CHARS:
            raise ServiceError(
                413,
                "TRANSFER_TOO_LARGE",
                f"Transfer exceeds {MAX_TRANSFER_TOTAL_CHARS} characters",
            )
        service.storage._write_text_atomic(chunk_path, request.content)
        received[key] = {"sha256": digest, "chars": len(request.content)}
        meta["total_chars"] = new_total
        meta["updated_at"] = now_iso()
        _write_meta(service, path, meta)

    received_indexes = sorted(int(index) for index in received)
    complete = len(received_indexes) == total_chunks
    next_index = next(
        (index for index in range(total_chunks) if str(index) not in received),
        None,
    )
    return {
        "transfer_id": transfer_id,
        "accepted_chunk_index": request.chunk_index,
        "received_chunks": len(received_indexes),
        "total_chunks": total_chunks,
        "complete": complete,
        "next_chunk_index": next_index,
        "next_required_action": (
            "Call finalizeSessionTransfer."
            if complete
            else f"Call uploadSessionTransferChunk with chunk_index {next_index}."
        ),
    }


def finalize_session_transfer(service: NovellaService, transfer_id: str) -> dict[str, Any]:
    path, meta = _read_meta(service, transfer_id)
    if meta.get("status") == "complete":
        response = meta.get("create_session_response")
        if isinstance(response, dict):
            return {"transfer_id": transfer_id, **response}
        raise ServiceError(500, "TRANSFER_CORRUPT", "Finalized transfer has no session response")

    total_chunks = int(meta["total_chunks"])
    received = meta.get("received", {})
    missing = [index for index in range(total_chunks) if str(index) not in received]
    if missing:
        raise ServiceError(
            409,
            "TRANSFER_INCOMPLETE",
            "Upload every chunk before finalizing; missing: " + ", ".join(map(str, missing[:30])),
        )

    try:
        raw = "".join(
            (path / "chunks" / f"{index:04d}.txt").read_text(encoding="utf-8")
            for index in range(total_chunks)
        )
    except OSError as exc:
        raise ServiceError(500, "TRANSFER_CHUNK_MISSING", "Stored transfer chunk is missing") from exc

    expected_digest = meta.get("payload_sha256")
    actual_digest = sha256(raw.encode("utf-8")).hexdigest()
    if expected_digest and expected_digest.lower() != actual_digest:
        raise ServiceError(
            409,
            "TRANSFER_DIGEST_MISMATCH",
            "Reassembled transfer payload does not match payload_sha256",
        )

    try:
        payload = CreateSessionRequest.model_validate_json(raw)
    except ValidationError as exc:
        first_errors = exc.errors(include_input=False)[:20]
        detail = "; ".join(
            f"{'.'.join(str(part) for part in item.get('loc', ()))}: {item.get('msg', 'invalid')}"
            for item in first_errors
        )
        raise ServiceError(
            422,
            "TRANSFER_PAYLOAD_INVALID",
            "Reassembled createSession payload is invalid: " + detail[:4000],
        ) from exc

    response = service.create_session(payload)
    meta["status"] = "complete"
    meta["finalized_at"] = now_iso()
    meta["create_session_response"] = response
    _write_meta(service, path, meta)
    shutil.rmtree(path / "chunks", ignore_errors=True)
    return {"transfer_id": transfer_id, **response}
