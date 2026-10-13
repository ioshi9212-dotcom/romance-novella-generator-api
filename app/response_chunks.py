"""Lossless 16k-character transport for oversized GPT Actions responses.

A large response is serialized ONCE and stored as immutable UTF-8 chunks.
Only small metadata is rewritten as the client reads chunks. This store is
separate from every novel session, so preparing a turn does not mutate canon.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .storage_paths import storage_root

CHUNK_CHARS = 16_000
TTL_SECONDS = 24 * 60 * 60


def _folder() -> Path:
    return storage_root() / ".response_chunks"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".partial_")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def _locked():
    root = _folder()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield root
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _prune(root: Path, now: float) -> None:
    """Garbage-collect only expired snapshots; incomplete reads have 24 hours."""
    for meta_path in root.glob("*.json"):
        try:
            if now - meta_path.stat().st_mtime < TTL_SECONDS:
                continue
            meta_path.unlink(missing_ok=True)
            (root / (meta_path.stem + ".bin")).unlink(missing_ok=True)
        except OSError:
            continue


def _envelope(read_id: str, meta: dict[str, Any], index: int, content: str) -> dict[str, Any]:
    count = len(meta["offsets"])
    read = set(meta["read_chunks"])
    following = next((i for i in range(count) if i not in read), None)
    return {
        "chunked": True,
        "read_id": read_id,
        "source": meta["source"],
        "chunk_index": index,
        "chunk_count": count,
        "chunk_chars_max": CHUNK_CHARS,
        "total_chars": meta["total_chars"],
        "sha256": meta["sha256"],
        "content": content,
        "next_chunk_index": following,
        "all_chunks_read": following is None,
        "instruction": (
            "Part of one JSON response. Chunk 0 is included. Read every remaining "
            "index via getResponseChunk using this read_id; join content in index "
            "order to recover the exact original JSON. Never treat a fragment "
            "as the complete game context."
        ),
    }


def present(payload: dict[str, Any], source: str) -> dict[str, Any]:
    """Keep existing response format for small payloads; snapshot larger ones."""
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= CHUNK_CHARS:
        return payload

    segments = [serialized[i:i + CHUNK_CHARS] for i in range(0, len(serialized), CHUNK_CHARS)]
    binary = bytearray()
    offsets: list[list[int]] = []
    hashes: list[str] = []
    for piece in segments:
        raw = piece.encode("utf-8")
        offsets.append([len(binary), len(raw)])
        binary.extend(raw)
        hashes.append(_hash(raw))

    read_id = uuid.uuid4().hex
    meta = {
        "source": source,
        "created": time.time(),
        "total_chars": len(serialized),
        "sha256": _hash(bytes(binary)),
        "offsets": offsets,
        "chunk_sha256": hashes,
        "read_chunks": [0],
    }
    with _locked() as root:
        _prune(root, time.time())
        _atomic(root / (read_id + ".bin"), bytes(binary))
        _atomic(root / (read_id + ".json"), json.dumps(meta, separators=(",", ":")).encode("utf-8"))
    return _envelope(read_id, meta, 0, segments[0])


def read_chunk(read_id: str, chunk_index: int) -> dict[str, Any]:
    """Read only the requested byte range; never reparse the full snapshot."""
    if len(read_id) != 32 or any(ch not in "0123456789abcdef" for ch in read_id):
        raise HTTPException(422, "Invalid read_id")
    if chunk_index < 0:
        raise HTTPException(422, "chunk_index must be nonnegative")

    with _locked() as root:
        meta_path = root / (read_id + ".json")
        data_path = root / (read_id + ".bin")
        if not meta_path.is_file() or not data_path.is_file():
            raise HTTPException(404, "Response snapshot not found or expired")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if time.time() - meta["created"] > TTL_SECONDS:
                raise HTTPException(410, "Response snapshot expired; repeat original read")
            if chunk_index >= len(meta["offsets"]):
                raise HTTPException(404, "Response chunk index out of range")
            position, length = meta["offsets"][chunk_index]
            with data_path.open("rb") as stream:
                stream.seek(position)
                raw = stream.read(length)
            if len(raw) != length or _hash(raw) != meta["chunk_sha256"][chunk_index]:
                raise HTTPException(409, "Response snapshot corrupted; repeat original read")
            content = raw.decode("utf-8")
            read = set(meta["read_chunks"])
            if chunk_index not in read:
                read.add(chunk_index)
                meta["read_chunks"] = sorted(read)
                _atomic(meta_path, json.dumps(meta, separators=(",", ":")).encode("utf-8"))
            return _envelope(read_id, meta, chunk_index, content)
        except HTTPException:
            raise
        except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
            raise HTTPException(409, "Unreadable response snapshot; repeat original read") from exc
