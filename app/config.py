import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    data_dir: Path = Field(default=Path("./data"))
    public_base_url: str = Field(default="https://web-production-4310e.up.railway.app")
    packet_chunk_chars: int = Field(default=28_000, ge=4_000, le=50_000)


def _split_text(text: str, chunk_size: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]


def _repack_active_pending_packets(data_dir: Path, chunk_size: int) -> None:
    """Shrink the unread tail of old active packets without invalidating progress.

    Earlier deployments used 12k chunks. Long-session continuity packets can therefore need too
    many consecutive Custom GPT Action calls. Existing active packets live on the Railway volume,
    so changing the configured chunk size alone would not help them. On startup we keep every
    already-delivered chunk byte-for-byte and only re-split the unread tail into larger chunks.
    The next remembered chunk index therefore remains valid and no already-read content is marked
    as read by mistake.
    """

    sessions_dir = data_dir / "sessions"
    if not sessions_dir.is_dir():
        return

    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        for filename in ("pending_turn.json", "pending_audit.json"):
            path = session_dir / filename
            if not path.is_file():
                continue
            try:
                pending = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(pending, dict) or pending.get("status") != "active":
                continue
            chunks = pending.get("chunks")
            if not isinstance(chunks, list) or not chunks:
                continue

            try:
                last_delivered = int(pending.get("last_delivered_chunk_index", 0))
            except (TypeError, ValueError):
                last_delivered = 0
            last_delivered = min(max(last_delivered, 0), len(chunks) - 1)
            delivered_prefix = [str(item) for item in chunks[: last_delivered + 1]]
            unread_text = "".join(str(item) for item in chunks[last_delivered + 1 :])
            unread_chunks = _split_text(unread_text, chunk_size) if unread_text else []
            repacked = delivered_prefix + unread_chunks
            if repacked == chunks:
                continue

            pending["chunks"] = repacked
            pending["last_delivered_chunk_index"] = last_delivered
            pending["all_chunks_delivered"] = last_delivered == len(repacked) - 1
            pending["runtime_repacked"] = True
            pending["runtime_repacked_from_chunk_count"] = len(chunks)
            pending["runtime_chunk_chars"] = chunk_size

            temp_path = path.with_suffix(path.suffix + ".tmp")
            try:
                temp_path.write_text(
                    json.dumps(pending, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                os.replace(temp_path, path)
            except OSError:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    configured_chunk_chars = int(os.getenv("PACKET_CHUNK_CHARS", "28000"))
    # Production packets grew after continuity/registry/audit hardening. Very small chunks
    # force too many consecutive Custom GPT Action calls and leave otherwise valid turns stuck
    # behind TURN_PACKET_INCOMPLETE. Direct Settings construction stays flexible for tests.
    effective_chunk_chars = max(configured_chunk_chars, 28_000)
    _repack_active_pending_packets(data_dir, effective_chunk_chars)
    return Settings(
        data_dir=data_dir,
        public_base_url=os.getenv(
            "PUBLIC_BASE_URL",
            "https://web-production-4310e.up.railway.app",
        ).rstrip("/"),
        packet_chunk_chars=effective_chunk_chars,
    )
