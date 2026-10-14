"""Read the currently deployed Rules and Skin Builder, never an in-chat cache.

The active Skin Builder is included in *every* prepare-turn packet, and its
content hash becomes part of the turn's context SHA. Edits during scene writing
therefore invalidate stale commits instead of silently saving an outdated scene.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException


def runtime_directory() -> Path:
    return Path(__file__).resolve().parent.parent / "runtime"


def read_runtime() -> dict[str, Any]:
    base = runtime_directory()
    try:
        rules = (base / "rules.md").read_text(encoding="utf-8")
        skin = (base / "scene_builder.md").read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            503, "Runtime instructions are unavailable; cannot safely prepare a scene."
        ) from exc
    fingerprint = hashlib.sha256(json.dumps(
        [rules, skin], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return {
        "sha256": fingerprint,
        "rules_sha256": hashlib.sha256(rules.encode("utf-8")).hexdigest(),
        "skin_builder_sha256": hashlib.sha256(skin.encode("utf-8")).hexdigest(),
        "rules": rules,
        "skin_builder": skin,
    }
