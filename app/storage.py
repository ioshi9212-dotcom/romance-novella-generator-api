from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import fcntl
from fastapi import HTTPException

from app.config import LOCK_TIMEOUT_SECONDS, SESSIONS_DIR, ensure_data_dirs


SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")
SAFE_RELATIVE_PART_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,120}$")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def safe_id(value: str, label: str = "id") -> str:
    if not SAFE_ID_RE.fullmatch(value or ""):
        raise HTTPException(status_code=400, detail=f"Unsafe {label}")
    return value


def safe_part(value: str, label: str = "path part") -> str:
    if not SAFE_RELATIVE_PART_RE.fullmatch(value or ""):
        raise HTTPException(status_code=400, detail=f"Unsafe {label}")
    return value


def session_root(session_id: str) -> Path:
    ensure_data_dirs()
    return SESSIONS_DIR / safe_id(session_id, "session_id")


def require_session(session_id: str) -> Path:
    root = session_root(session_id)
    if not (root / "session.json").is_file():
        raise HTTPException(status_code=404, detail="Session not found")
    return root


def resolve_session_path(root: Path, relative_path: str) -> Path:
    rel = Path(relative_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise HTTPException(status_code=400, detail="Unsafe relative path")
    target = (root / rel).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise HTTPException(status_code=400, detail="Path escapes session root")
    return target


def read_text(path: Path, default: str | None = None) -> str:
    if not path.is_file():
        if default is not None:
            return default
        raise HTTPException(status_code=404, detail=f"File not found: {path.name}")
    return path.read_text(encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Corrupt JSON: {path.name}") from exc


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def compact_json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json_text(value))


@contextmanager
def session_lock(root: Path, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".session.lock"
    handle = lock_path.open("a+")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise HTTPException(status_code=409, detail="Session is busy")
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def deep_merge(base: Any, patch: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    output = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(output.get(key), dict):
            output[key] = deep_merge(output[key], value)
        else:
            output[key] = value
    return output


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return items


def jsonl_with_event(text: str, event: dict[str, Any], unique_key: str, unique_value: str) -> str:
    items = parse_jsonl(text)
    if any(str(item.get(unique_key)) == unique_value for item in items):
        return text
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    prefix = text if not text or text.endswith("\n") else text + "\n"
    return prefix + line + "\n"


def apply_writes(root: Path, writes: dict[str, str]) -> list[str]:
    ordered = sorted(writes, key=lambda path: (path == "session.json", path))
    for relative_path in ordered:
        atomic_write_text(resolve_session_path(root, relative_path), writes[relative_path])
    return ordered


def journal_event(root: Path, event: dict[str, Any]) -> None:
    path = root / "journal.jsonl"
    existing = read_text(path, default="")
    event_id = str(event["event_id"])
    updated = jsonl_with_event(existing, event, "event_id", event_id)
    if updated != existing:
        atomic_write_text(path, updated)


def execute_transaction(
    root: Path,
    transaction_id: str,
    writes: dict[str, str],
    receipt: dict[str, Any] | None = None,
) -> list[str]:
    transaction_id = safe_id(transaction_id, "transaction_id")
    txn_dir = root / "transactions" / "pending" / transaction_id
    txn_dir.mkdir(parents=True, exist_ok=True)
    plan_path = txn_dir / "commit_plan.json"
    plan = {
        "transaction_id": transaction_id,
        "status": "prepared",
        "prepared_at": utc_now(),
        "writes": writes,
        "receipt": receipt,
    }
    atomic_write_json(plan_path, plan)
    journal_event(
        root,
        {
            "event_id": f"{transaction_id}:prepared",
            "transaction_id": transaction_id,
            "status": "prepared",
            "at": plan["prepared_at"],
        },
    )
    changed = apply_writes(root, writes)
    if receipt is not None:
        receipt_path = root / "transactions" / "receipts" / f"{transaction_id}.json"
        atomic_write_json(receipt_path, receipt)
    plan["status"] = "committed"
    plan["committed_at"] = utc_now()
    atomic_write_json(plan_path, plan)
    journal_event(
        root,
        {
            "event_id": f"{transaction_id}:committed",
            "transaction_id": transaction_id,
            "status": "committed",
            "at": plan["committed_at"],
        },
    )
    return changed


def recover_transactions(root: Path) -> list[str]:
    recovered: list[str] = []
    pending_root = root / "transactions" / "pending"
    if not pending_root.is_dir():
        return recovered
    for txn_dir in sorted(pending_root.iterdir()):
        plan_path = txn_dir / "commit_plan.json"
        plan = read_json(plan_path, default={}) or {}
        if plan.get("status") != "prepared":
            continue
        writes = plan.get("writes")
        if not isinstance(writes, dict):
            continue
        apply_writes(root, {str(key): str(value) for key, value in writes.items()})
        receipt = plan.get("receipt")
        if isinstance(receipt, dict):
            atomic_write_json(
                root / "transactions" / "receipts" / f"{txn_dir.name}.json",
                receipt,
            )
        plan["status"] = "committed"
        plan["recovered_at"] = utc_now()
        atomic_write_json(plan_path, plan)
        journal_event(
            root,
            {
                "event_id": f"{txn_dir.name}:recovered",
                "transaction_id": txn_dir.name,
                "status": "recovered",
                "at": plan["recovered_at"],
            },
        )
        recovered.append(txn_dir.name)
    return recovered
