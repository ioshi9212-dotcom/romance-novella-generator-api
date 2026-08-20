from __future__ import annotations

import json
import shutil
import threading
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any, ClassVar, Iterator

from pydantic import BaseModel, Field, ValidationError

from app.models import CreateSessionRequest
from app.service import NovellaService, ServiceError, _new_id, now_iso
from app.storage import safe_component


MAX_TRANSFER_CHUNKS = 256
MAX_TRANSFER_CHUNK_CHARS = 6_000
MAX_TRANSFER_TOTAL_CHARS = 1_500_000


class StartSessionTransferRequest(BaseModel):
    total_chunks: int = Field(ge=1, le=MAX_TRANSFER_CHUNKS)
    payload_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="Optional SHA-256 of the complete serialized CreateSessionRequest.",
    )


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
    received_chars: int
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
    creation_verified: bool
    payload_chars: int
    payload_sha256: str
    stored_document_count: int
    next_required_action: str


class _TransferLocks:
    guard: ClassVar[threading.Lock] = threading.Lock()
    locks: ClassVar[dict[str, threading.RLock]] = {}

    @classmethod
    @contextmanager
    def locked(cls, transfer_id: str) -> Iterator[None]:
        with cls.guard:
            lock = cls.locks.setdefault(transfer_id, threading.RLock())
        with lock:
            yield


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
    except ValueError as exc:  # pragma: no cover - guarded by safe_component.
        raise ServiceError(400, "INVALID_TRANSFER_ID", "Unsafe transfer_id") from exc
    return path


def _read_meta(
    service: NovellaService, transfer_id: str
) -> tuple[Path, dict[str, Any]]:
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


def _next_missing_index(meta: dict[str, Any]) -> int | None:
    received = meta.get("received", {})
    return next(
        (
            index
            for index in range(int(meta["total_chunks"]))
            if str(index) not in received
        ),
        None,
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
        except FileExistsError:  # pragma: no cover - cryptographically improbable.
            continue
    else:  # pragma: no cover
        raise ServiceError(500, "TRANSFER_ID_FAILURE", "Could not allocate transfer_id")

    (path / "chunks").mkdir(parents=False, exist_ok=False)
    meta = {
        "transfer_id": transfer_id,
        "status": "uploading",
        "total_chunks": request.total_chunks,
        "payload_sha256": request.payload_sha256.lower()
        if request.payload_sha256
        else None,
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
        "next_required_action": (
            "Upload chunk_index 0. Continue without replying to the player until every chunk "
            "is accepted and finalizeSessionTransfer succeeds."
        ),
    }


def upload_session_transfer_chunk(
    service: NovellaService,
    transfer_id: str,
    request: UploadSessionTransferChunkRequest,
) -> dict[str, Any]:
    with _TransferLocks.locked(transfer_id):
        path, meta = _read_meta(service, transfer_id)
        if meta.get("status") == "complete":
            raise ServiceError(
                409, "TRANSFER_ALREADY_FINALIZED", "Transfer is already finalized"
            )
        if meta.get("status") != "uploading":
            raise ServiceError(
                409, "TRANSFER_NOT_UPLOADABLE", "Transfer is not accepting chunks"
            )

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
        next_index = _next_missing_index(meta)
        if existing is not None:
            if existing.get("sha256") != digest:
                raise ServiceError(
                    409,
                    "TRANSFER_CHUNK_CONFLICT",
                    "This chunk_index was already uploaded with different content",
                )
        elif request.chunk_index != next_index:
            raise ServiceError(
                409,
                "TRANSFER_CHUNK_OUT_OF_ORDER",
                f"Upload chunk_index {next_index} next; no data was accepted",
            )
        else:
            new_total = int(meta.get("total_chars", 0)) + len(request.content)
            if new_total > MAX_TRANSFER_TOTAL_CHARS:
                raise ServiceError(
                    413,
                    "TRANSFER_TOO_LARGE",
                    f"Transfer exceeds {MAX_TRANSFER_TOTAL_CHARS} characters",
                )
            service.storage._write_text_atomic(
                path / "chunks" / f"{request.chunk_index:04d}.txt",
                request.content,
            )
            received[key] = {"sha256": digest, "chars": len(request.content)}
            meta["total_chars"] = new_total
            meta["updated_at"] = now_iso()
            _write_meta(service, path, meta)

        next_index = _next_missing_index(meta)
        complete = next_index is None
        return {
            "transfer_id": transfer_id,
            "accepted_chunk_index": request.chunk_index,
            "received_chunks": len(received),
            "total_chunks": total_chunks,
            "received_chars": int(meta.get("total_chars", 0)),
            "complete": complete,
            "next_chunk_index": next_index,
            "next_required_action": (
                "Call finalizeSessionTransfer now. Do not reply to the player yet."
                if complete
                else f"Upload chunk_index {next_index} next. Do not reply to the player."
            ),
        }


def _expected_stored_paths(payload: CreateSessionRequest) -> set[str]:
    paths = {
        "session.json",
        "manifest.json",
        "chronology/manifest.json",
        "chronology/chronology_0001.json",
        "state/novel.json",
        "state/hidden_lore.json",
        "state/plot_state.json",
        "state/director_plan.json",
        "state/world_state.json",
        "state/scene_state.json",
    }
    if payload.setup_source is not None:
        paths.add("state/setup_source.json")
    for character in payload.characters:
        prefix = f"characters/{character.character_id}"
        paths.update(
            {
                f"{prefix}/card.json",
                f"{prefix}/current_state.json",
                f"{prefix}/relationships.json",
                f"{prefix}/knowledge.json",
            }
        )
    paths.update(f"locations/{item.location_id}.json" for item in payload.locations)
    paths.update(f"objects/{item.object_id}.json" for item in payload.objects)
    return paths


def _verify_session_files(
    service: NovellaService, session_id: str, payload: CreateSessionRequest
) -> int:
    root = service.storage.session_dir(session_id)
    expected = _expected_stored_paths(payload)
    missing = sorted(path for path in expected if not (root / path).is_file())
    if missing:
        raise ServiceError(
            500,
            "SESSION_WRITE_INCOMPLETE",
            "Railway did not persist every required document: " + ", ".join(missing[:20]),
        )
    for relative in expected:
        try:
            value = json.loads((root / relative).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ServiceError(
                500,
                "SESSION_WRITE_INVALID",
                f"Stored document is unreadable: {relative}",
            ) from exc
        if not isinstance(value, dict):
            raise ServiceError(
                500,
                "SESSION_WRITE_INVALID",
                f"Stored document is not an object: {relative}",
            )
    if payload.setup_source is not None:
        stored_source = service.storage.read_json(
            session_id, "state/setup_source.json", default={}
        )
        clean_source = {
            key: value
            for key, value in stored_source.items()
            if key not in {"session_id", "_meta"}
        }
        expected_source = payload.setup_source.model_dump(mode="json")
        if clean_source != expected_source:
            raise ServiceError(
                500,
                "SESSION_WRITE_MISMATCH",
                "Stored setup_source differs from the exact confirmed player source",
            )
    return len(expected)


def finalize_session_transfer(
    service: NovellaService, transfer_id: str
) -> dict[str, Any]:
    with _TransferLocks.locked(transfer_id):
        path, meta = _read_meta(service, transfer_id)
        if meta.get("status") == "complete":
            response = meta.get("final_response")
            if isinstance(response, dict):
                return response
            raise ServiceError(
                500, "TRANSFER_CORRUPT", "Finalized transfer has no session response"
            )
        if meta.get("status") != "uploading":
            raise ServiceError(
                409, "TRANSFER_NOT_FINALIZABLE", "Transfer cannot be finalized"
            )

        next_index = _next_missing_index(meta)
        if next_index is not None:
            raise ServiceError(
                409,
                "TRANSFER_INCOMPLETE",
                f"Upload every chunk before finalizing; next missing chunk is {next_index}",
            )

        total_chunks = int(meta["total_chunks"])
        try:
            raw = "".join(
                (path / "chunks" / f"{index:04d}.txt").read_text(encoding="utf-8")
                for index in range(total_chunks)
            )
        except OSError as exc:
            raise ServiceError(
                500, "TRANSFER_CHUNK_MISSING", "Stored transfer chunk is missing"
            ) from exc

        actual_digest = sha256(raw.encode("utf-8")).hexdigest()
        expected_digest = meta.get("payload_sha256")
        if expected_digest and expected_digest != actual_digest:
            raise ServiceError(
                409,
                "TRANSFER_DIGEST_MISMATCH",
                "Reassembled transfer payload does not match payload_sha256",
            )

        try:
            payload = CreateSessionRequest.model_validate_json(raw)
        except ValidationError as exc:
            errors = exc.errors(include_input=False)[:30]
            detail = "; ".join(
                f"{'.'.join(str(part) for part in item.get('loc', ()))}: "
                f"{item.get('msg', 'invalid')}"
                for item in errors
            )
            raise ServiceError(
                422,
                "TRANSFER_PAYLOAD_INVALID",
                "Reassembled createSession payload is invalid: " + detail[:5000],
            ) from exc

        if payload.runtime_contract_version != "2.0":
            raise ServiceError(
                422,
                "TRANSFER_CONTRACT_REQUIRED",
                'Chunked setup requires runtime_contract_version: "2.0"',
            )

        response = service.create_session(payload)
        session_id = str(response["session_id"])
        document_count = _verify_session_files(service, session_id, payload)
        receipt = {
            "transfer_id": transfer_id,
            "payload_sha256": actual_digest,
            "payload_chars": len(raw),
            "total_chunks": total_chunks,
            "stored_document_count": document_count,
            "creation_verified": True,
            "verified_at": now_iso(),
        }
        service.storage.write_json_batch(
            session_id, {"creation_receipt.json": receipt}
        )
        final_response = {
            "transfer_id": transfer_id,
            **response,
            "creation_verified": True,
            "payload_chars": len(raw),
            "payload_sha256": actual_digest,
            "stored_document_count": document_count,
            "next_required_action": (
                "Creation is complete and verified. Keep the exact session_id, then call "
                "getTurnPacket for the opening scene. Do not show transfer details to the player."
            ),
        }
        meta["status"] = "complete"
        meta["finalized_at"] = now_iso()
        meta["final_response"] = final_response
        _write_meta(service, path, meta)
        shutil.rmtree(path / "chunks", ignore_errors=True)
        return final_response
