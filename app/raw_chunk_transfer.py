"""Lossless fallback for GPT Actions when file references contain local sandbox paths.

The model must supply base64 made directly from actual file bytes (e.g. Python).
Never accept a filename, synthesized source, PLACEHOLDER or checksum without
the full original bytes. All parts are persisted and validated before RAW moves.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

PART_LIMIT = 12288
MAX_BYTES = 5 * 1024 * 1024
MAX_PARTS = (MAX_BYTES + PART_LIMIT - 1) // PART_LIMIT


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".raw_part_")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def ingest_part(
    folder: Path, meta: dict[str, Any], payload: Any, *,
    append_source: Callable, repair_placeholder: Callable, RawPart: type,
    source_digest: Callable, atomic_json: Callable,
) -> dict[str, Any]:
    """Store one indexed chunk, never claim success before verified assembly."""
    if meta.get("этап") == "готово_к_игре" or int(meta.get("последний_ход", 0)) != 0:
        raise HTTPException(409, "RAW upload only before verification and gameplay")
    stage = meta.get("этап")
    if stage not in ("сбор", "вопросы", "готово_к_записи", "запись_и_сверка"):
        raise HTTPException(409, "Unknown RAW creation stage")
    if payload.mode == "append" and stage not in ("сбор", "вопросы"):
        raise HTTPException(409, "RAW intake closed; use recover only for a missing source")
    try:
        part = base64.b64decode(payload.chunk_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "Invalid base64 RAW part") from exc
    if not part or len(part) > PART_LIMIT:
        raise HTTPException(422, "RAW part must contain between 1 and 12288 original bytes")
    if payload.total_parts > MAX_PARTS or payload.part_index >= payload.total_parts:
        raise HTTPException(422, "Invalid RAW part count or index")
    if payload.total_parts * PART_LIMIT < payload.expected_bytes:
        raise HTTPException(422, "Too few RAW parts for expected byte length")

    upload_dir = folder / ".raw_uploads" / (payload.event_id + "_" + payload.mode + "_" + payload.expected_sha256)
    upload_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "event_id": payload.event_id,
        "mode": payload.mode,
        "expected_bytes": payload.expected_bytes,
        "expected_sha256": payload.expected_sha256,
        "total_parts": payload.total_parts,
        "file_name": payload.file_name,
    }
    manifest_path = upload_dir / "manifest.json"
    if manifest_path.is_file():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise HTTPException(409, "Inconsistent RAW upload metadata")
    else:
        _atomic_bytes(manifest_path, json.dumps(manifest, ensure_ascii=False).encode("utf-8"))

    done_path = upload_dir / "done.json"
    if done_path.is_file():
        return json.loads(done_path.read_text(encoding="utf-8"))

    destination = upload_dir / f"{payload.part_index:04d}.bin"
    if destination.is_file():
        if destination.read_bytes() != part:
            raise HTTPException(409, "RAW part index already used with different bytes")
    else:
        _atomic_bytes(destination, part)
    paths = [upload_dir / f"{i:04d}.bin" for i in range(payload.total_parts)]
    received = sum(p.is_file() for p in paths)
    if received < payload.total_parts:
        return {"status": "receiving", "event_id": payload.event_id,
                "received_parts": received, "total_parts": payload.total_parts}

    binary = b"".join(p.read_bytes() for p in paths)
    if len(binary) != payload.expected_bytes:
        raise HTTPException(409, "RAW_LENGTH_MISMATCH: no RAW has been written")
    checksum = hashlib.sha256(binary).hexdigest()
    if checksum != payload.expected_sha256:
        raise HTTPException(409, "RAW_SHA256_MISMATCH: no RAW has been written")
    try:
        text = binary.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "Original RAW must be UTF-8 without converting line breaks") from exc
    if text.strip().upper() == "PLACEHOLDER":
        raise HTTPException(422, "RAW_PLACEHOLDER_FORBIDDEN")

    if payload.mode == "repair":
        result = repair_placeholder(
            folder, meta, event_id=payload.event_id, text=text,
            byte_count=len(binary), sha256=checksum, RawPart=RawPart,
            source_digest=source_digest, atomic_json=atomic_json,
        )
    else:
        previous = meta.get("_raw_receipts", {}).get(payload.event_id)
        same = source_digest(RawPart(event_id=payload.event_id, text=text,
                                   file_name=payload.file_name))
        if previous is not None and previous != same:
            raise HTTPException(409, "Cannot overwrite a different RAW source")
        append_source(folder, meta, RawPart(event_id=payload.event_id, text=text,
                                          file_name=payload.file_name),
                      allow_recovery=payload.mode == "recover")
        if payload.mode == "recover":
            meta["_raw_repair_requires_review"] = True
            atomic_json(folder / "сессия.json", meta)
        if payload.event_id == "initial":
            meta["_initial_text_digest"] = checksum
            atomic_json(folder / "сессия.json", meta)
        result = {"status": "restored_review_required" if payload.mode == "recover" else "saved",
                  "event_id": payload.event_id, "bytes": len(binary), "sha256": checksum}

    answer = dict(result)
    answer["received_parts"] = payload.total_parts
    answer["total_parts"] = payload.total_parts
    _atomic_bytes(done_path, json.dumps(answer, ensure_ascii=False).encode("utf-8"))
    return answer
