"""Centralized persistent storage resolution and fail-closed Amvera checks.

Amvera mounts its persistent Data volume at /data. Never default to ./data:
that resolves to /app/data on Amvera and disappears after a deployment.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException


DEFAULT_DATA_DIR = Path("/data")


def storage_root() -> Path:
    """Resolve a stable absolute root; reject unsafe or unmounted production paths."""
    configured = os.environ.get("DATA_DIR", str(DEFAULT_DATA_DIR)).strip()
    path = Path(configured)
    if not configured or not path.is_absolute():
        raise HTTPException(
            503,
            "STORAGE_MISCONFIGURED: DATA_DIR must be an absolute path. "
            "Use /data in Amvera, not ./data or /app/data.",
        )
    if path == Path("/app") or Path("/app") in path.parents:
        raise HTTPException(
            503,
            "STORAGE_MISCONFIGURED: /app is ephemeral on Amvera. "
            "Set DATA_DIR=/data and mount persistenceMount: /data.",
        )
    if path == DEFAULT_DATA_DIR:
        # Prevent acknowledging successful writes to a plain, ephemeral /data
        # directory when the actual Data volume did not mount.
        if not path.is_dir() or not os.path.ismount(path):
            raise HTTPException(
                503,
                "STORAGE_NOT_MOUNTED: Persistent Amvera /data volume is unavailable. "
                "Check run.persistenceMount: /data and the deployed container. "
                "No session data was written.",
            )
    return path


def storage_diagnostics() -> dict[str, str | bool]:
    """Safe public diagnostics without exposing session IDs, text or secrets."""
    root = storage_root()
    return {
        "data_root": str(root),
        "persistent_mount_detected": os.path.ismount(root),
        "writable": os.access(root, os.W_OK),
    }
