from __future__ import annotations

import hashlib
import json
from typing import Any


BOOTSTRAP_PREVIEW_CHUNK_SIZE = 4500
BOOTSTRAP_PREVIEW_INLINE_LIMIT = 6000
PREVIEW_TEXT_FILE = "pending_setup_preview.md"
PREVIEW_TRANSPORT_FILE = "pending_setup_preview_transport.json"

BOOTSTRAP_PREVIEW_TRANSPORT_RULES = """
ТРАНСПОРТ BOOTSTRAP ЧЕРЕЗ ACTIONS
- Создай один цельный bootstrap и передай его единственным полем bootstrap_json в createBootstrapPreview.
- Не разворачивай protagonist, characters, story_plan и другие корневые разделы в отдельные Action kwargs.
- scene_history и turns передай пустыми списками. Технические relationships, knowledge, npc_state и continuity можно оставить пустыми: сервер их достроит.
- Если preview разбит на части, дочитай getBootstrapPreviewChunk по порядку, склей без изменений и только затем покажи пользователю.
- Если createBootstrapPreview потерян с ResponseTooLargeError, возьми preview_transport из debugSessionDump и получи части с chunk_index=0; bootstrap повторно не сохраняй.
- Не подтверждай preview и не запускай сцену, пока пользователь не увидел полный склеенный текст и явно его не подтвердил.
""".strip()


class BootstrapPreviewTransportError(ValueError):
    def __init__(self, detail: str | dict[str, Any], *, status_code: int = 409):
        super().__init__(str(detail))
        self.detail = detail
        self.status_code = status_code


def split_bootstrap_preview(text: str, chunk_size: int = BOOTSTRAP_PREVIEW_CHUNK_SIZE) -> list[str]:
    text = text or ""
    if chunk_size < 1000:
        raise ValueError("bootstrap preview chunk_size must be at least 1000")
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            minimum_break = start + max(1000, chunk_size // 2)
            paragraph_break = text.rfind("\n\n", minimum_break, end)
            line_break = text.rfind("\n", minimum_break, end)
            chosen_break = paragraph_break + 2 if paragraph_break >= minimum_break else line_break + 1
            if chosen_break > start:
                end = chosen_break
        chunks.append(text[start:end])
        start = end
    return chunks or [""]


def _preview_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _transport_metadata(text: str, chunk_size: int) -> tuple[dict[str, Any], list[str]]:
    chunks = split_bootstrap_preview(text, chunk_size)
    return {
        "version": "novella.bootstrap_preview_transport.v1",
        "preview_id": _preview_id(text),
        "preview_chars": len(text),
        "chunk_size": chunk_size,
        "chunk_count": len(chunks),
    }, chunks


def load_bootstrap_preview_chunks(storage: Any, session_id: str) -> tuple[dict[str, Any], list[str]]:
    """Load a stored preview and migrate legacy oversized recovery chunks."""
    preview_path = storage.session_dir(session_id) / PREVIEW_TEXT_FILE
    if not preview_path.exists():
        raise FileNotFoundError(f"No stored bootstrap preview for session {session_id}")
    preview = preview_path.read_text(encoding="utf-8")
    stored_metadata = storage.read_json(session_id, PREVIEW_TRANSPORT_FILE, default={})
    try:
        stored_chunk_size = int((stored_metadata or {}).get("chunk_size") or BOOTSTRAP_PREVIEW_CHUNK_SIZE)
    except (TypeError, ValueError):
        stored_chunk_size = BOOTSTRAP_PREVIEW_CHUNK_SIZE
    if stored_chunk_size < 1000:
        stored_chunk_size = BOOTSTRAP_PREVIEW_CHUNK_SIZE
    # Deployments before v9.2 stored a 20k recovery chunk. Re-split it when the
    # saved preview is read so an already-created session can recover safely.
    chunk_size = (
        BOOTSTRAP_PREVIEW_CHUNK_SIZE
        if stored_chunk_size > BOOTSTRAP_PREVIEW_INLINE_LIMIT
        else stored_chunk_size
    )
    metadata, chunks = _transport_metadata(preview, chunk_size)
    if stored_metadata != metadata:
        storage.write_json(session_id, PREVIEW_TRANSPORT_FILE, metadata)
    return metadata, chunks


def build_bootstrap_preview_response(
    storage: Any,
    session_id: str,
    preview: str,
    *,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(preview) <= BOOTSTRAP_PREVIEW_INLINE_LIMIT:
        metadata, chunks = _transport_metadata(preview, BOOTSTRAP_PREVIEW_INLINE_LIMIT)
    else:
        metadata, chunks = _transport_metadata(preview, BOOTSTRAP_PREVIEW_CHUNK_SIZE)
    storage.write_json(session_id, PREVIEW_TRANSPORT_FILE, metadata)

    chunk_count = len(chunks)
    has_more = chunk_count > 1
    first_chunk = chunks[0]
    visible_text = first_chunk if has_more else preview
    next_required_action = (
        "Call getBootstrapPreviewChunk for chunk_index 1 through chunk_count-1 using this preview_id; concatenate message_to_user plus every preview_chunk in order; then show the complete preview exactly once and wait for explicit confirmation."
        if has_more
        else "Show message_to_user exactly once and wait for explicit confirmation."
    )

    response_diagnostics = dict(diagnostics or {})
    response_diagnostics["preview_transport"] = {
        **metadata,
        "chunked": has_more,
        "inline_limit": BOOTSTRAP_PREVIEW_INLINE_LIMIT,
        "returned_chunk_index": 0,
        "next_chunk_index": 1 if has_more else None,
        "next_required_action": next_required_action,
        "single_bootstrap_input": True,
    }

    response = {
        # Return the visible text exactly once. The old response copied the same
        # preview into three fields; an 8-character setup could therefore exceed
        # the Custom GPT Action response limit before chunking even started.
        "message_to_user": visible_text,
        "session_id": session_id,
        "status": "bootstrap_review_pending",
        "must_show_to_user": not has_more,
        "wait_for_confirmation": True,
        "next_user_action": (
            "Сначала получи и склей все части preview. Затем покажи полный текст и жди подтверждения."
            if has_more
            else "Напиши `подтверждаю`, если всё подходит, или скажи, что изменить."
        ),
        "can_confirm": not has_more,
        "preview_id": metadata["preview_id"],
        "preview_chars": metadata["preview_chars"],
        "preview_chunk_index": 0,
        "preview_chunk_count": chunk_count,
        "has_more_preview_chunks": has_more,
        "next_preview_chunk_index": 1 if has_more else None,
        "diagnostics": response_diagnostics,
    }
    response_diagnostics["preview_transport"]["response_json_chars"] = len(
        json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    )
    return response


def get_bootstrap_preview_chunk(
    storage: Any,
    session_id: str,
    chunk_index: int,
    *,
    expected_preview_id: str | None = None,
) -> dict[str, Any]:
    session = storage.read_json(session_id, "session.json")
    if session.get("status") != "bootstrap_review_pending":
        raise BootstrapPreviewTransportError(
            f"Bootstrap preview is not waiting for review. Current status: {session.get('status')}",
            status_code=409,
        )

    metadata, chunks = load_bootstrap_preview_chunks(storage, session_id)

    current_preview_id = str(metadata["preview_id"])
    if expected_preview_id and expected_preview_id != current_preview_id:
        raise BootstrapPreviewTransportError(
            {
                "code": "stale_bootstrap_preview_id",
                "expected_preview_id": current_preview_id,
                "received_preview_id": expected_preview_id,
                "recovery": "Use the preview_id returned by the latest createBootstrapPreview response.",
            },
            status_code=409,
        )

    if chunk_index < 0 or chunk_index >= len(chunks):
        raise BootstrapPreviewTransportError(
            {
                "code": "bootstrap_preview_chunk_out_of_range",
                "chunk_index": chunk_index,
                "chunk_count": len(chunks),
            },
            status_code=416,
        )

    has_more = chunk_index + 1 < len(chunks)
    return {
        "session_id": session_id,
        "status": "bootstrap_review_pending",
        "preview_id": current_preview_id,
        "preview_chars": metadata["preview_chars"],
        "chunk_index": chunk_index,
        "chunk_count": len(chunks),
        "preview_chunk": chunks[chunk_index],
        "has_more": has_more,
        "next_chunk_index": chunk_index + 1 if has_more else None,
        "must_show_to_user": False,
        "ready_to_show_full_preview": not has_more,
        "can_confirm": not has_more,
        "diagnostics": {
            "preview_transport": {
                **metadata,
                "returned_chunk_index": chunk_index,
                "next_chunk_index": chunk_index + 1 if has_more else None,
                "next_required_action": (
                    f"Call getBootstrapPreviewChunk with chunk_index={chunk_index + 1} and the same preview_id. Do not show an isolated chunk."
                    if has_more
                    else "Concatenate chunk 0 and every preview_chunk in numerical order, show the complete preview exactly once, then wait for explicit user confirmation."
                ),
            }
        },
    }
