from pathlib import Path
from typing import Any
import json
import os
import tempfile

MAX_BUNDLE_SCENE_HISTORY = 6
MAX_BUNDLE_TURNS = 8


def _clip_text(value: Any, limit: int = 500) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _compact_list(items: Any, limit_items: int = 6, text_limit: int = 180) -> list[Any]:
    if not isinstance(items, list):
        return []
    result: list[Any] = []
    for item in items[:limit_items]:
        if isinstance(item, str):
            result.append(_clip_text(item, text_limit))
        elif isinstance(item, dict):
            result.append({str(k): _clip_text(v, text_limit) if isinstance(v, str) else v for k, v in item.items()})
        else:
            result.append(item)
    return result


def _compact_scene_history_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    return {
        "turn": entry.get("turn"),
        "summary": _clip_text(entry.get("summary", ""), 450),
        "important_facts": _compact_list(entry.get("important_facts", []), 5, 180),
        "witnesses": _compact_list(entry.get("witnesses", []), 8, 80),
        "body_excerpt": _clip_text(entry.get("body_excerpt") or entry.get("visible_scene_excerpt") or entry.get("visible_scene_text") or "", 500),
        "created_at": entry.get("created_at"),
    }


def _compact_turn_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    scene_response = entry.get("scene_response") if isinstance(entry.get("scene_response"), dict) else {}
    return {
        "turn": entry.get("turn"),
        "player_input": _clip_text(entry.get("player_input") or scene_response.get("player_input") or "", 280),
        "summary": _clip_text(entry.get("summary") or scene_response.get("summary") or "", 360),
        "important_facts": _compact_list(entry.get("important_facts") or scene_response.get("important_facts") or [], 4, 160),
        "witnesses": _compact_list(entry.get("witnesses") or scene_response.get("witnesses") or [], 8, 80),
        "created_at": entry.get("created_at"),
    }


def _compact_memory_chunk(chunk: Any) -> dict[str, Any]:
    if not isinstance(chunk, dict):
        return {}
    return {
        "chunk_id": chunk.get("chunk_id"),
        "type": chunk.get("type"),
        "turn_start": chunk.get("turn_start"),
        "turn_end": chunk.get("turn_end"),
        "scene_summaries": _compact_list(chunk.get("scene_summaries", []), 6, 220),
        "turn_summaries": _compact_list(chunk.get("turn_summaries", []), 6, 180),
    }


def _compact_continuity_for_actions(continuity: Any) -> dict[str, Any]:
    if not isinstance(continuity, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("current_arc", "current_act", "last_continuity_check"):
        if key in continuity:
            result[key] = continuity[key]
    for key in ("open_threads", "notes", "warnings"):
        result[key] = _compact_list(continuity.get(key, []), 10, 240)
    result["memory_chunks"] = [
        _compact_memory_chunk(chunk)
        for chunk in (continuity.get("memory_chunks", []) or [])[-6:]
        if isinstance(chunk, dict)
    ]
    result["maintenance_events"] = _compact_list(continuity.get("maintenance_events", []), 6, 200)
    result["gpt_memory_compacts"] = _compact_list(continuity.get("gpt_memory_compacts", []), 4, 200)
    return result


def _safe_path_component(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{label} must be non-empty and must not contain surrounding whitespace")
    if len(value) > 128:
        raise ValueError(f"{label} is too long")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{label} must be a single safe path component")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} contains control characters")
    return value


def _safe_session_id(session_id: str) -> str:
    return _safe_path_component(session_id, "session_id")


def _safe_relative_path(filename: str) -> Path:
    if not isinstance(filename, str):
        raise ValueError("filename must be a string")
    if not filename or filename != filename.strip():
        raise ValueError("filename must be non-empty and must not contain surrounding whitespace")
    if "\\" in filename:
        raise ValueError("filename must use forward slashes")
    if any(ord(char) < 32 for char in filename):
        raise ValueError("filename contains control characters")
    relative = Path(filename)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("filename must be a safe relative path")
    return relative


class JsonStorage:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        safe_id = _safe_session_id(session_id)
        sessions_root = self.sessions_dir.resolve()
        path = (sessions_root / safe_id).resolve()
        try:
            path.relative_to(sessions_root)
        except ValueError as exc:
            raise ValueError("session_id resolves outside the sessions directory") from exc
        return path

    def _session_path(self, session_id: str, filename: str) -> Path:
        session_root = self.session_dir(session_id)
        relative = _safe_relative_path(filename)
        path = (session_root / relative).resolve()
        try:
            path.relative_to(session_root)
        except ValueError as exc:
            raise ValueError("filename resolves outside the session directory") from exc
        return path

    def ensure_session_dir(self, session_id: str) -> Path:
        path = self.session_dir(session_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_json(self, session_id: str, filename: str, data: Any) -> None:
        path = self._session_path(session_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = Path(temp_file.name)
            os.replace(temp_path, path)
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise

    def read_json(self, session_id: str, filename: str, default: Any | None = None) -> Any:
        path = self._session_path(session_id, filename)
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
        base = self._session_path(session_id, directory)
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
        character_id = _safe_path_component(character_id, "character_id")
        self.write_json(session_id, f"characters/{character_id}.json", card)
        index = self.read_json(session_id, "characters_index.json", default={"ids": []})
        ids = index.setdefault("ids", [])
        if character_id not in ids:
            ids.append(character_id)
        self.write_json(session_id, "characters_index.json", index)

    def write_character_knowledge(self, session_id: str, character_id: str, entry: dict[str, Any]) -> None:
        character_id = _safe_path_component(character_id, "character_id")
        entry = {**entry, "character_id": entry.get("character_id") or character_id}
        self.write_json(session_id, f"state/knowledge/{character_id}.json", entry)
        index = self.read_json(session_id, "state/knowledge_index.json", default={"ids": []})
        ids = index.setdefault("ids", [])
        if character_id not in ids:
            ids.append(character_id)
        self.write_json(session_id, "state/knowledge_index.json", index)

    def write_relationship_pair(self, session_id: str, pair_id: str, entry: dict[str, Any]) -> None:
        pair_id = _safe_path_component(pair_id, "pair_id")
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

        # Keep Action payload safe: never expose full old scene text or full scene_response
        # through runtime bundle. Full rendered text is returned only by applyTurnResult.
        bundle["scene_history"] = [
            _compact_scene_history_entry(item)
            for item in (bundle.get("scene_history") or [])[-MAX_BUNDLE_SCENE_HISTORY:]
            if isinstance(item, dict)
        ]
        bundle["turns"] = [
            _compact_turn_entry(item)
            for item in (bundle.get("turns") or [])[-MAX_BUNDLE_TURNS:]
            if isinstance(item, dict)
        ]
        bundle["continuity"] = _compact_continuity_for_actions(bundle.get("continuity", {}))

        # v8 runtime layout: one card / knowledge / relationship file per generated id.
        # Legacy fallback remains for older v5-v7 sessions.
        bundle["characters"] = self.read_characters(session_id)
        bundle["knowledge"] = self.read_knowledge(session_id)
        bundle["relationships"] = self.read_relationships(session_id)
        bundle["characters_index"] = self.read_json(session_id, "characters_index.json", default={"ids": list(bundle["characters"].keys())})
        bundle["knowledge_index"] = self.read_json(session_id, "state/knowledge_index.json", default={"ids": list(bundle["knowledge"].keys())})
        bundle["relationship_index"] = self.read_json(session_id, "state/relationship_index.json", default={"pair_ids": list(bundle["relationships"].keys())})
        return bundle
