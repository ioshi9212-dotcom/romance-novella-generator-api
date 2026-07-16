from __future__ import annotations

import hashlib
from typing import Any

from app.id_utils import now_iso


BOOTSTRAP_PREVIEW_CHUNK_SIZE = 12_000
PENDING_PREVIEW_TRANSPORT_FILE = "pending_setup_preview_chunks.json"


class BootstrapPreviewChunkError(ValueError):
    def __init__(self, detail: str | dict[str, Any], *, status_code: int = 409):
        super().__init__(str(detail))
        self.detail = detail
        self.status_code = status_code


def split_bootstrap_preview(text: str, chunk_size: int = BOOTSTRAP_PREVIEW_CHUNK_SIZE) -> list[str]:
    text = text or ""
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            newline = text.rfind("\n", start + max(2_000, chunk_size // 2), end)
            if newline > start:
                end = newline + 1
        chunks.append(text[start:end])
        start = end
    return chunks or [""]


def _build_transport(session_id: str, preview: str) -> dict[str, Any]:
    chunks = split_bootstrap_preview(preview)
    digest = hashlib.sha256(preview.encode("utf-8")).hexdigest()
    return {
        "version": "novella.bootstrap_preview_transport.v1",
        "session_id": session_id,
        "preview_id": f"preview_{digest[:16]}",
        "preview_sha256": digest,
        "preview_length": len(preview),
        "chunk_size": BOOTSTRAP_PREVIEW_CHUNK_SIZE,
        "chunk_count": len(chunks),
        "chunks": chunks,
        "retrieved_chunk_indexes": [0],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def prepare_bootstrap_preview_transport(
    manager: Any,
    session_id: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    full_preview = str(
        response.get("user_visible_preview")
        or response.get("preview")
        or response.get("message_to_user")
        or ""
    )
    transport = _build_transport(session_id, full_preview)
    manager.storage.write_json(session_id, PENDING_PREVIEW_TRANSPORT_FILE, transport)

    chunks = transport["chunks"]
    first_chunk = chunks[0]
    chunk_count = len(chunks)
    has_more = chunk_count > 1
    diagnostics = dict(response.get("diagnostics") or {})
    diagnostics["preview_transport"] = {
        "chunked": has_more,
        "preview_id": transport["preview_id"],
        "preview_sha256": transport["preview_sha256"],
        "preview_length": transport["preview_length"],
        "chunk_size": transport["chunk_size"],
        "chunk_count": chunk_count,
        "returned_chunk_index": 0,
        "next_chunk_index": 1 if has_more else None,
        "instruction": (
            "Call getBootstrapPreviewChunk for every remaining index, concatenate preview_chunk values in order, "
            "then show the complete preview exactly once. Do not ask for confirmation before all chunks are loaded."
            if has_more
            else "Show message_to_user exactly once and wait for explicit confirmation."
        ),
    }

    return {
        **response,
        # Keep legacy aliases populated, but only with one bounded chunk so the
        # Action response cannot triple the entire long preview.
        "message_to_user": first_chunk,
        "preview": first_chunk,
        "user_visible_preview": first_chunk,
        "preview_id": transport["preview_id"],
        "preview_chunk": first_chunk,
        "preview_chunk_index": 0,
        "preview_chunk_count": chunk_count,
        "has_more_preview_chunks": has_more,
        "next_preview_chunk_index": 1 if has_more else None,
        "next_user_action": (
            "Загрузи все оставшиеся части через getBootstrapPreviewChunk, собери их по порядку и только затем покажи полный черновик пользователю."
            if has_more
            else response.get("next_user_action")
        ),
        "diagnostics": diagnostics,
    }


def _load_transport(manager: Any, session_id: str) -> dict[str, Any]:
    transport = manager.storage.read_json(session_id, PENDING_PREVIEW_TRANSPORT_FILE, default={})
    if isinstance(transport, dict) and isinstance(transport.get("chunks"), list) and transport.get("chunks"):
        return transport

    preview_path = manager.storage.session_dir(session_id) / "pending_setup_preview.md"
    if not preview_path.exists():
        raise BootstrapPreviewChunkError("No stored bootstrap preview chunks.", status_code=404)
    repaired = _build_transport(session_id, preview_path.read_text(encoding="utf-8"))
    repaired["recovered_at"] = now_iso()
    manager.storage.write_json(session_id, PENDING_PREVIEW_TRANSPORT_FILE, repaired)
    return repaired


def get_bootstrap_preview_chunk(
    manager: Any,
    session_id: str,
    *,
    preview_id: str,
    chunk_index: int,
) -> dict[str, Any]:
    transport = _load_transport(manager, session_id)
    if preview_id != transport.get("preview_id"):
        raise BootstrapPreviewChunkError(
            "Stale or mismatched preview_id. Create/finalize the bootstrap preview again."
        )

    chunks = transport.get("chunks") or []
    if chunk_index < 0 or chunk_index >= len(chunks):
        raise BootstrapPreviewChunkError(
            f"chunk_index out of range. Available: 0..{len(chunks) - 1}",
            status_code=416,
        )

    retrieved = {
        int(index)
        for index in transport.get("retrieved_chunk_indexes", [])
        if isinstance(index, int) or str(index).isdigit()
    }
    retrieved.add(chunk_index)
    transport["retrieved_chunk_indexes"] = sorted(retrieved)
    transport["updated_at"] = now_iso()
    manager.storage.write_json(session_id, PENDING_PREVIEW_TRANSPORT_FILE, transport)

    has_more = chunk_index < len(chunks) - 1
    return {
        "session_id": session_id,
        "preview_id": preview_id,
        "chunk_index": chunk_index,
        "chunk_count": len(chunks),
        "preview_chunk": chunks[chunk_index],
        "has_more": has_more,
        "next_chunk_index": chunk_index + 1 if has_more else None,
        "diagnostics": {
            "preview_sha256": transport.get("preview_sha256"),
            "preview_length": transport.get("preview_length"),
            "retrieved_chunk_indexes": sorted(retrieved),
            "instruction": "Concatenate preview_chunk values in index order and show the complete preview exactly once.",
        },
    }


def require_complete_bootstrap_preview_delivery(manager: Any, session_id: str) -> None:
    transport = _load_transport(manager, session_id)
    chunk_count = int(transport.get("chunk_count") or len(transport.get("chunks") or []))
    retrieved = {
        int(index)
        for index in transport.get("retrieved_chunk_indexes", [])
        if isinstance(index, int) or str(index).isdigit()
    }
    missing = [index for index in range(chunk_count) if index not in retrieved]
    if missing:
        raise BootstrapPreviewChunkError(
            {
                "code": "bootstrap_preview_chunks_not_loaded",
                "preview_id": transport.get("preview_id"),
                "missing_chunk_indexes": missing,
                "recovery": "Call getBootstrapPreviewChunk for every missing index before confirming the preview.",
            }
        )
