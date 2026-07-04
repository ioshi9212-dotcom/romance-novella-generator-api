import re
import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"session_{stamp}_{uuid.uuid4().hex[:8]}"


def slugify_id(value: str, fallback: str = "item") -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-zа-яё0-9]+", "_", value, flags=re.IGNORECASE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or f"{fallback}_{uuid.uuid4().hex[:6]}"


def pair_id(a: str, b: str) -> str:
    left, right = sorted([a, b])
    return f"{left}__{right}"
