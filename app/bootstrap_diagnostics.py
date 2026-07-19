from __future__ import annotations

from typing import Any
import uuid

from app.id_utils import now_iso


DEBUGGABLE_SESSION_STATUSES = {
    "bootstrap_pending",
    "bootstrap_review_pending",
    "active",
    "error",
}


def validation_error_item(error: Any) -> dict[str, str]:
    """Convert legacy validator strings into stable path/message objects."""
    text = " ".join(str(error or "").strip().split())
    path = "bootstrap"
    message = text or "Unknown bootstrap validation error."

    schema_prefix = "bootstrap_output.schema.json:"
    if text.startswith(schema_prefix):
        remainder = text[len(schema_prefix):]
        if ": " in remainder:
            path, message = remainder.split(": ", 1)
        else:
            path = remainder or path
    elif text.startswith("missing key:"):
        path = text.split(":", 1)[1].strip() or path
    elif " missing key:" in text:
        owner, missing = text.split(" missing key:", 1)
        path = ".".join(part for part in (owner.strip(), missing.strip()) if part)
    elif ": " in text:
        candidate, remainder = text.split(": ", 1)
        if candidate and " " not in candidate:
            path, message = candidate, remainder
    else:
        for separator in (" must ", " cannot ", " conflicts ", " duplicates "):
            if separator in text:
                path = text.split(separator, 1)[0].strip() or path
                break

    return {"path": path or "bootstrap", "message": message}


def _normalize_error_detail(detail: Any, *, default_code: str) -> dict[str, Any]:
    if isinstance(detail, dict):
        normalized = dict(detail)
        normalized.setdefault("code", default_code)
        raw_errors = normalized.get("errors")
        if isinstance(raw_errors, list):
            normalized["errors"] = [
                item if isinstance(item, dict) and item.get("path") else validation_error_item(item)
                for item in raw_errors[:100]
            ]
            if len(raw_errors) > 100:
                normalized["errors_truncated"] = len(raw_errors) - 100
        return normalized
    if isinstance(detail, list):
        normalized = {
            "code": default_code,
            "message": "Bootstrap validation failed.",
            "errors": [validation_error_item(item) for item in detail[:100]],
        }
        if len(detail) > 100:
            normalized["errors_truncated"] = len(detail) - 100
        return normalized
    return {
        "code": default_code,
        "message": str(detail or "Bootstrap operation failed."),
        "errors": [],
    }


def record_bootstrap_error(
    manager: Any,
    session_id: str,
    *,
    operation: str,
    status_code: int,
    detail: Any,
    default_code: str,
) -> dict[str, Any]:
    entry = {
        "error_id": "bootstrap_error_" + uuid.uuid4().hex[:12],
        "operation": operation,
        "status_code": status_code,
        **_normalize_error_detail(detail, default_code=default_code),
        "created_at": now_iso(),
    }
    try:
        with manager.storage.session_transaction(session_id):
            session = manager.storage.read_json(session_id, "session.json")
            session["last_error"] = entry
            session["updated_at"] = now_iso()
            manager.storage.write_json(session_id, "session.json", session)
    except (OSError, ValueError):
        # Do not hide the original failure when the session itself is gone or
        # its id is invalid.
        pass
    return entry


def clear_bootstrap_error(manager: Any, session_id: str) -> None:
    with manager.storage.session_transaction(session_id):
        session = manager.storage.read_json(session_id, "session.json")
        if "last_error" not in session:
            return
        session.pop("last_error", None)
        session["updated_at"] = now_iso()
        manager.storage.write_json(session_id, "session.json", session)


def _clip(value: Any, *, text_limit: int = 500, item_limit: int = 100) -> Any:
    if isinstance(value, str):
        text = " ".join(value.split())
        return text if len(text) <= text_limit else text[: text_limit - 1].rstrip() + "…"
    if isinstance(value, list):
        return [_clip(item, text_limit=text_limit, item_limit=item_limit) for item in value[:item_limit]]
    if isinstance(value, dict):
        return {
            str(key): _clip(item, text_limit=text_limit, item_limit=item_limit)
            for key, item in list(value.items())[:item_limit]
        }
    return value


def bootstrap_debug_summary(manager: Any, session_id: str, session: dict[str, Any]) -> dict[str, Any]:
    session_dir = manager.storage.session_dir(session_id)
    pending = manager.storage.read_json(session_id, "pending_bootstrap.json", default={})
    pending = pending if isinstance(pending, dict) else {}
    pending_characters = pending.get("characters") if isinstance(pending.get("characters"), dict) else {}

    return {
        "flow": "single_preview",
        "pending_bootstrap_present": (session_dir / "pending_bootstrap.json").exists(),
        "pending_character_ids": sorted(str(item) for item in pending_characters),
        "pending_preview_present": (session_dir / "pending_setup_preview.md").exists(),
        "ready_to_confirm": session.get("status") == "bootstrap_review_pending",
        "committed": session.get("status") == "active",
        "last_error": _clip(session.get("last_error") or {}),
    }
