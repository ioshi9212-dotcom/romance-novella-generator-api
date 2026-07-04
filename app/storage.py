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

    def _read_dir_json_map(self, session_id: str, directory: str, key_field: str, fallback_filename: str) -> dict[str, Any]:
        base = self.session_dir(session_id) / directory
        if base.exists():
            result: dict[str, Any] = {}
            for path in sorted(base.glob("*.json")):
                data = json.loads(path.read_text(encoding="utf-8"))
                key = data.get(key_field) if isinstance(data, dict) else None
                result[str(key or path.stem)] = data
            return result
        return self.read_json(session_id, fallback_filename, default={})

    def read_characters(self, session_id: str) -> dict[str, Any]:
        return self._read_dir_json_map(session_id, "characters", "id", "characters.json")

    def read_knowledge(self, session_id: str) -> dict[str, Any]:
        return self._read_dir_json_map(session_id, "state/knowledge", "character_id", "knowledge.json")

    def read_relationships(self, session_id: str) -> dict[str, Any]:
        return self._read_dir_json_map(session_id, "state/relationship_pairs", "pair_id", "relationships.json")

    def write_character(self, session_id: str, character_id: str, card: dict[str, Any]) -> None:
        self.write_json(session_id, f"characters/{character_id}.json", card)
        index = self.read_json(session_id, "characters_index.json", default={"ids": []})
        ids = index.setdefault("ids", [])
        if character_id not in ids:
            ids.append(character_id)
        self.write_json(session_id, "characters_index.json", index)

    def write_character_knowledge(self, session_id: str, character_id: str, entry: dict[str, Any]) -> None:
        entry = {**entry, "character_id": entry.get("character_id") or character_id}
        self.write_json(session_id, f"state/knowledge/{character_id}.json", entry)
        index = self.read_json(session_id, "state/knowledge_index.json", default={"ids": []})
        ids = index.setdefault("ids", [])
        if character_id not in ids:
            ids.append(character_id)
        self.write_json(session_id, "state/knowledge_index.json", index)

    def write_relationship_pair(self, session_id: str, pair_id: str, entry: dict[str, Any]) -> None:
        entry = {**entry, "pair_id": entry.get("pair_id") or pair_id}
        self.write_json(session_id, f"state/relationship_pairs/{pair_id}.json", entry)
        index = self.read_json(session_id, "state/relationship_index.json", default={"pair_ids": []})
        ids = index.setdefault("pair_ids", [])
        if pair_id not in ids:
            ids.append(pair_id)
        self.write_json(session_id, "state/relationship_index.json", index)

    def read_session_bundle(self, session_id: str) -> dict[str, Any]:
        scalar_files = [
            "session.json",
            "user_request.json",
            "protagonist.json",
            "story_plan.json",
            "current_state.json",
            "npc_state.json",
            "future_locks.json",
            "continuity.json",
            "scene_history.json",
            "turns.json",
        ]
        bundle: dict[str, Any] = {}
        for filename in scalar_files:
            default = [] if filename in {"scene_history.json", "turns.json"} else {}
            bundle[filename.removesuffix(".json")] = self.read_json(session_id, filename, default=default)

        # v8 runtime layout: one card / knowledge / relationship file per generated id.
        # Legacy fallback remains for older v5-v7 sessions.
        bundle["characters"] = self.read_characters(session_id)
        bundle["knowledge"] = self.read_knowledge(session_id)
        bundle["relationships"] = self.read_relationships(session_id)
        bundle["characters_index"] = self.read_json(session_id, "characters_index.json", default={"ids": list(bundle["characters"].keys())})
        bundle["knowledge_index"] = self.read_json(session_id, "state/knowledge_index.json", default={"ids": list(bundle["knowledge"].keys())})
        bundle["relationship_index"] = self.read_json(session_id, "state/relationship_index.json", default={"pair_ids": list(bundle["relationships"].keys())})
        return bundle
