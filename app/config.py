from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / ".data")).resolve()
SESSIONS_DIR = DATA_DIR / "sessions"
RULES_DIR = ROOT_DIR / "rules"

ACTION_TOKEN = os.getenv("ACTION_TOKEN", "").strip()
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()

MAX_BOOTSTRAP_PART_CHARS = int(os.getenv("MAX_BOOTSTRAP_PART_CHARS", "50000"))
MAX_CHARACTER_CHARS = int(os.getenv("MAX_CHARACTER_CHARS", "16000"))
MAX_CONTEXT_CHUNK_CHARS = int(os.getenv("MAX_CONTEXT_CHUNK_CHARS", "25000"))
MAX_CONTEXT_CHUNKS = int(os.getenv("MAX_CONTEXT_CHUNKS", "3"))
MAX_SCENE_CHARS = int(os.getenv("MAX_SCENE_CHARS", "20000"))
MAX_COMMIT_CHARS = int(os.getenv("MAX_COMMIT_CHARS", "50000"))
LOCK_TIMEOUT_SECONDS = float(os.getenv("LOCK_TIMEOUT_SECONDS", "5"))


def ensure_data_dirs() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
