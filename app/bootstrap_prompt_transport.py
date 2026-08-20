from __future__ import annotations

import hashlib
from typing import Any


BOOTSTRAP_PROMPT_CHUNK_SIZE = 4500
BOOTSTRAP_PROMPT_TEXT_FILE = "pending_bootstrap_prompt.md"
BOOTSTRAP_PROMPT_TRANSPORT_FILE = "pending_bootstrap_prompt_transport.json"
BOOTSTRAP_PROMPT_TRANSPORT_VERSION = "v9.4-session-chunks"


class BootstrapPromptTransportError(ValueError):
    def __init__(self, detail: str | dict[str, Any], *, status_code: int = 409):
        super().__init__(str(detail))
        self.detail = detail
        self.status_code = status_code


def split_bootstrap_prompt(text: str, chunk_size: int = BOOTSTRAP_PROMPT_CHUNK_SIZE) -> list[str]:
    """Split without changing a single character so concatenation is lossless."""
    text = text or ""
    if chunk_size < 1000:
        raise ValueError("bootstrap prompt chunk_size must be at least 1000")
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


def _prompt_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _transport_metadata(text: str) -> tuple[dict[str, Any], list[str]]:
    chunks = split_bootstrap_prompt(text)
    return {
        "version": BOOTSTRAP_PROMPT_TRANSPORT_VERSION,
        "bootstrap_prompt_sha256": _prompt_sha256(text),
        "bootstrap_prompt_chars": len(text),
        "bootstrap_prompt_bytes": len(text.encode("utf-8")),
        "chunk_size": BOOTSTRAP_PROMPT_CHUNK_SIZE,
        "chunk_count": len(chunks),
    }, chunks


def store_bootstrap_prompt_transport(
    storage: Any,
    session_id: str,
    prompt: str,
) -> tuple[dict[str, Any], list[str]]:
    metadata, chunks = _transport_metadata(prompt)
    storage.write_json(session_id, BOOTSTRAP_PROMPT_TRANSPORT_FILE, metadata)
    return metadata, chunks


def load_bootstrap_prompt_chunks(storage: Any, session_id: str) -> tuple[dict[str, Any], list[str]]:
    prompt_path = storage.session_dir(session_id) / BOOTSTRAP_PROMPT_TEXT_FILE
    if not prompt_path.exists():
        raise FileNotFoundError(f"No stored bootstrap prompt for session {session_id}")
    prompt = prompt_path.read_text(encoding="utf-8")
    metadata, chunks = _transport_metadata(prompt)
    stored_metadata = storage.read_json(session_id, BOOTSTRAP_PROMPT_TRANSPORT_FILE, default={})
    if stored_metadata != metadata:
        storage.write_json(session_id, BOOTSTRAP_PROMPT_TRANSPORT_FILE, metadata)
    return metadata, chunks


def build_create_session_prompt_response(
    storage: Any,
    session_id: str,
    prompt: str,
    *,
    response: dict[str, Any],
) -> dict[str, Any]:
    metadata, chunks = store_bootstrap_prompt_transport(storage, session_id, prompt)
    has_more = len(chunks) > 1
    return {
        **response,
        # This list is intentionally omitted from the large Action response.
        # Canonical files are already persisted before this bounded response is built.
        "files_created": [],
        "bootstrap_prompt": chunks[0],
        "bootstrap_prompt_bytes": metadata["bootstrap_prompt_bytes"],
        "bootstrap_prompt_sha256": metadata["bootstrap_prompt_sha256"],
        "bootstrap_prompt_chunk_count": len(chunks),
        "has_more_bootstrap_prompt_chunks": has_more,
    }


def get_bootstrap_prompt_chunk(
    storage: Any,
    session_id: str,
    chunk_index: int,
    *,
    expected_prompt_sha256: str | None = None,
) -> dict[str, Any]:
    session = storage.read_json(session_id, "session.json")
    status = session.get("status")
    if status not in {"bootstrap_pending", "bootstrap_review_pending"}:
        raise BootstrapPromptTransportError(
            f"Bootstrap prompt is no longer available for setup. Current status: {status}",
            status_code=409,
        )

    metadata, chunks = load_bootstrap_prompt_chunks(storage, session_id)
    current_sha256 = str(metadata["bootstrap_prompt_sha256"])
    if expected_prompt_sha256 and expected_prompt_sha256 != current_sha256:
        raise BootstrapPromptTransportError(
            {
                "code": "stale_bootstrap_prompt_sha256",
                "expected_bootstrap_prompt_sha256": current_sha256,
                "received_bootstrap_prompt_sha256": expected_prompt_sha256,
                "recovery": "Use the hash returned by the original createSession response. Do not create a second session.",
            },
            status_code=409,
        )

    if chunk_index < 0 or chunk_index >= len(chunks):
        raise BootstrapPromptTransportError(
            {
                "code": "bootstrap_prompt_chunk_out_of_range",
                "chunk_index": chunk_index,
                "chunk_count": len(chunks),
            },
            status_code=416,
        )

    has_more = chunk_index + 1 < len(chunks)
    return {
        "session_id": session_id,
        "status": status,
        "bootstrap_prompt_sha256": current_sha256,
        "bootstrap_prompt_chars": metadata["bootstrap_prompt_chars"],
        "bootstrap_prompt_bytes": metadata["bootstrap_prompt_bytes"],
        "chunk_index": chunk_index,
        "chunk_count": len(chunks),
        "bootstrap_prompt_chunk": chunks[chunk_index],
        "has_more": has_more,
        "next_chunk_index": chunk_index + 1 if has_more else None,
        "diagnostics": {
            "bootstrap_prompt_transport": {
                "version": metadata["version"],
                "chunk_size": metadata["chunk_size"],
                "returned_chunk_index": chunk_index,
                "next_required_action": (
                    f"Call getBootstrapPromptChunk with chunk_index={chunk_index + 1} and the same session_id. Do not call createSession again."
                    if has_more
                    else "Concatenate bootstrap_prompt from createSession with every bootstrap_prompt_chunk in numeric order, verify the SHA-256, then build the preview. Do not call createSession again."
                ),
            }
        },
    }
