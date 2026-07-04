from pathlib import Path
from typing import Any
import json


class JsonStorage:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / session_id

    def ensure_session_dir(self, session_id: str) -> Path:
        path = self.session_dir(session_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_json(self, session_id: str, filename: str, data: Any) -> None:
        path = self.ensure_session_dir(session_id) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_json(self, session_id: str, filename: str, default: Any | None = None) -> Any:
        path = self.session_dir(session_id) / filename
        if not path.exists():
            if default is not None:
                return default
            raise FileNotFoundError(f"Missing file for session {session_id}: {filename}")
        return json.loads(path.read_text(encoding="utf-8"))

    def append_json_list(self, session_id: str, filename: str, item: Any) -> None:
        data = self.read_json(session_id, filename, default=[])
        if not isinstance(data, list):
            raise ValueError(f"{filename} is not a list")
        data.append(item)
        self.write_json(session_id, filename, data)

    def list_sessions(self) -> list[str]:
        if not self.sessions_dir.exists():
            return []
        return sorted([p.name for p in self.sessions_dir.iterdir() if p.is_dir()], reverse=True)

    def read_session_bundle(self, session_id: str) -> dict[str, Any]:
        files = [
            "session.json",
            "user_request.json",
            "protagonist.json",
            "characters.json",
            "relationships.json",
            "knowledge.json",
            "story_plan.json",
            "current_state.json",
            "npc_state.json",
            "future_locks.json",
            "continuity.json",
            "scene_history.json",
            "turns.json",
        ]
        bundle: dict[str, Any] = {}
        for filename in files:
            bundle[filename.removesuffix(".json")] = self.read_json(session_id, filename, default={})
        return bundle
