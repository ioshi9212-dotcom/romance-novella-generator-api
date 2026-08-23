from __future__ import annotations

import json
import re
import secrets
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.service import BASE_STATE_PATHS, ServiceError, _new_id, _stamp_document, now_iso
from app.storage import safe_component

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class StoryLibrary:
    """Persistent master-story templates, separate from mutable play sessions."""

    def __init__(self, novella_service: Any):
        self.service = novella_service
        self.storage = novella_service.storage
        self.root = Path(novella_service.settings.data_dir) / "stories"
        self.root.mkdir(parents=True, exist_ok=True)

    def _story_dir(self, story_id: str) -> Path:
        if not SAFE_ID_RE.fullmatch(story_id):
            raise ServiceError(422, "INVALID_STORY_ID", "story_id must be a stable ASCII SafeId")
        safe_id = safe_component(story_id, "story_id")
        root = self.root.resolve()
        path = (root / safe_id).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ServiceError(400, "INVALID_STORY_ID", "Unsafe story_id") from exc
        return path

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)

    @staticmethod
    def _read_json(path: Path, default: Any = None) -> Any:
        if not path.exists():
            return deepcopy(default)
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _digest(value: Any) -> str:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_safe_id(value: Any, label: str) -> str:
        text = str(value or "")
        if not SAFE_ID_RE.fullmatch(text):
            raise ServiceError(422, f"{label.upper()}_INVALID", f"{label} must be an ASCII SafeId")
        return text

    def _validate_template(self, template: Any) -> dict[str, Any]:
        if not isinstance(template, dict):
            raise ServiceError(422, "STORY_TEMPLATE_INVALID", "template must be an object")
        required = [
            "novel",
            "hidden_lore",
            "plot_state",
            "director_plan",
            "world_state",
            "scene_state",
            "characters",
        ]
        missing = [key for key in required if key not in template]
        if missing:
            raise ServiceError(
                422,
                "STORY_TEMPLATE_INCOMPLETE",
                "Missing template sections: " + ", ".join(missing),
            )
        characters = template.get("characters")
        if not isinstance(characters, list) or not characters:
            raise ServiceError(422, "STORY_CHARACTERS_REQUIRED", "At least one character is required")

        seen: set[str] = set()
        registry: list[dict[str, str]] = []
        for index, bundle in enumerate(characters, start=1):
            if not isinstance(bundle, dict):
                raise ServiceError(422, "STORY_CHARACTER_INVALID", f"Character #{index} must be an object")
            character_id = self._validate_safe_id(bundle.get("character_id"), "character_id")
            if character_id in seen:
                raise ServiceError(422, "STORY_CHARACTER_ID_DUPLICATE", character_id)
            seen.add(character_id)
            card = bundle.get("card") if isinstance(bundle.get("card"), dict) else {}
            card_id = card.get("character_id")
            if card_id not in (None, character_id):
                raise ServiceError(422, "STORY_CHARACTER_ID_MISMATCH", character_id)
            identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
            name = str(identity.get("name", "")).strip()
            if not name:
                raise ServiceError(422, "STORY_CHARACTER_NAME_REQUIRED", character_id)
            role = str(identity.get("role") or card.get("card_hint") or "персонаж истории").strip()
            registry.append({"character_id": character_id, "name": name, "short_role": role})

        for location in template.get("locations", []) or []:
            self._validate_safe_id(location.get("location_id"), "location_id")
        for item in template.get("objects", []) or []:
            self._validate_safe_id(item.get("object_id"), "object_id")

        prepared = deepcopy(template)
        novel = deepcopy(prepared.get("novel", {}))
        novel["character_registry"] = registry
        novel["character_registry_instruction"] = (
            "Complete short roster of all registered characters. character_id links to the full card. "
            "Ordinary turn packets include full dossiers only for POV and characters physically present in the scene."
        )
        prepared["novel"] = novel
        prepared.setdefault("locations", [])
        prepared.setdefault("objects", [])
        return prepared

    def list_stories(self) -> dict[str, Any]:
        stories: list[dict[str, Any]] = []
        for path in sorted(self.root.iterdir() if self.root.exists() else []):
            if not path.is_dir():
                continue
            meta = self._read_json(path / "story.json", {})
            if not isinstance(meta, dict) or not meta.get("story_id"):
                continue
            stories.append(
                {
                    "story_id": meta.get("story_id"),
                    "title": meta.get("title"),
                    "status": meta.get("status", "draft"),
                    "revision": meta.get("revision", 0),
                    "character_count": meta.get("character_count", 0),
                    "pov_character_id": meta.get("pov_character_id"),
                }
            )
        return {"stories": stories, "count": len(stories)}

    def put_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        story_id = str(payload.get("story_id", "")).strip()
        title = str(payload.get("title", "")).strip()
        source_text = payload.get("source_text")
        if not title or not isinstance(source_text, str) or not source_text.strip():
            raise ServiceError(422, "STORY_DRAFT_INCOMPLETE", "title and exact source_text are required")
        path = self._story_dir(story_id)
        template = self._validate_template(payload.get("template"))
        path.mkdir(parents=True, exist_ok=True)
        previous = self._read_json(path / "story.json", {})
        revision = int(previous.get("revision", 0) or 0) + 1
        meta = {
            "story_id": story_id,
            "title": title,
            "status": "draft",
            "revision": revision,
            "character_count": len(template["characters"]),
            "pov_character_id": template.get("novel", {}).get("pov_character_id"),
            "template_sha256": self._digest(template),
            "source_sha256": sha256(source_text.encode("utf-8")).hexdigest(),
            "updated_at": now_iso(),
        }
        self._write_json(path / "story.json", meta)
        (path / "source.txt").write_text(source_text, encoding="utf-8")
        self._write_template_files(path, template)
        self._write_json(
            path / "verification.json",
            {
                "status": "pending_readback",
                "revision": revision,
                "last_read_chunk_index": -1,
                "all_chunks_delivered": False,
                "content_sha256": None,
                "missing_items": [],
                "conflicts": [],
                "final_consistency_pass": False,
                "updated_at": now_iso(),
            },
        )
        return {
            **meta,
            "next_required_action": (
                "Read every story readback chunk strictly in order. If anything is missing, distorted or contradictory, "
                "rewrite the draft, restart readback from chunk 0, and repeat until verification has zero issues."
            ),
        }

    def _write_template_files(self, path: Path, template: dict[str, Any]) -> None:
        for key in BASE_STATE_PATHS:
            self._write_json(path / "state" / f"{key}.json", template.get(key, {}))
        manifest = {
            "schema_version": 2,
            "character_ids": [item["character_id"] for item in template.get("characters", [])],
            "location_ids": [item["location_id"] for item in template.get("locations", [])],
            "object_ids": [item["object_id"] for item in template.get("objects", [])],
        }
        self._write_json(path / "manifest.json", manifest)
        for character in template.get("characters", []):
            cid = character["character_id"]
            prefix = path / "characters" / cid
            self._write_json(prefix / "card.json", character.get("card", {}))
            self._write_json(prefix / "current_state.json", character.get("current_state", {}))
            self._write_json(prefix / "relationships.json", character.get("relationships", {}))
            self._write_json(prefix / "knowledge.json", character.get("knowledge", {}))
        for location in template.get("locations", []):
            self._write_json(path / "locations" / f"{location['location_id']}.json", location.get("state", {}))
        for item in template.get("objects", []):
            self._write_json(path / "objects" / f"{item['object_id']}.json", item.get("state", {}))

    def _snapshot(self, story_id: str) -> dict[str, Any]:
        path = self._story_dir(story_id)
        meta = self._read_json(path / "story.json", None)
        if not isinstance(meta, dict):
            raise ServiceError(404, "STORY_NOT_FOUND", story_id)
        manifest = self._read_json(path / "manifest.json", {})
        state = {
            key: self._read_json(path / "state" / f"{key}.json", {})
            for key in BASE_STATE_PATHS
        }
        characters = []
        for cid in manifest.get("character_ids", []):
            prefix = path / "characters" / cid
            characters.append(
                {
                    "character_id": cid,
                    "card": self._read_json(prefix / "card.json", {}),
                    "current_state": self._read_json(prefix / "current_state.json", {}),
                    "relationships": self._read_json(prefix / "relationships.json", {}),
                    "knowledge": self._read_json(prefix / "knowledge.json", {}),
                }
            )
        locations = [
            {"location_id": lid, "state": self._read_json(path / "locations" / f"{lid}.json", {})}
            for lid in manifest.get("location_ids", [])
        ]
        objects = [
            {"object_id": oid, "state": self._read_json(path / "objects" / f"{oid}.json", {})}
            for oid in manifest.get("object_ids", [])
        ]
        return {
            "story": meta,
            "source_text": (path / "source.txt").read_text(encoding="utf-8"),
            **state,
            "characters": characters,
            "locations": locations,
            "objects": objects,
        }

    def _serialized_snapshot(self, story_id: str) -> tuple[dict[str, Any], list[str], str]:
        snapshot = self._snapshot(story_id)
        text = json.dumps(snapshot, ensure_ascii=False, indent=2)
        size = self.service.settings.packet_chunk_chars
        chunks = [text[i : i + size] for i in range(0, len(text), size)] or [""]
        digest = sha256(text.encode("utf-8")).hexdigest()
        return snapshot, chunks, digest

    def readback(self, story_id: str, chunk_index: int) -> dict[str, Any]:
        snapshot, chunks, digest = self._serialized_snapshot(story_id)
        if chunk_index < 0 or chunk_index >= len(chunks):
            raise ServiceError(404, "STORY_CHUNK_NOT_FOUND", str(chunk_index))
        path = self._story_dir(story_id)
        verification = self._read_json(path / "verification.json", {})
        revision = int(snapshot["story"].get("revision", 0))
        if int(verification.get("revision", -1)) != revision:
            verification = {
                "status": "pending_readback",
                "revision": revision,
                "last_read_chunk_index": -1,
                "all_chunks_delivered": False,
            }
        last_read = int(verification.get("last_read_chunk_index", -1))
        if chunk_index > last_read + 1:
            raise ServiceError(
                409,
                "STORY_READBACK_CHUNK_OUT_OF_ORDER",
                f"Read chunk {last_read + 1} before requesting chunk {chunk_index}",
            )
        if chunk_index == last_read + 1:
            verification["last_read_chunk_index"] = chunk_index
        verification["content_sha256"] = digest
        verification["all_chunks_delivered"] = (
            int(verification.get("last_read_chunk_index", -1)) == len(chunks) - 1
        )
        verification["updated_at"] = now_iso()
        self._write_json(path / "verification.json", verification)
        return {
            "story_id": story_id,
            "revision": revision,
            "chunk_index": chunk_index,
            "chunk_count": len(chunks),
            "content": chunks[chunk_index],
            "content_sha256": digest,
            "has_more": chunk_index < len(chunks) - 1,
            "next_chunk_index": chunk_index + 1 if chunk_index < len(chunks) - 1 else None,
            "delivered_chunk_count": int(verification.get("last_read_chunk_index", -1)) + 1,
            "all_chunks_delivered": bool(verification.get("all_chunks_delivered")),
        }

    def verify(self, story_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot, chunks, digest = self._serialized_snapshot(story_id)
        meta = snapshot["story"]
        path = self._story_dir(story_id)
        verification = self._read_json(path / "verification.json", {})
        revision = int(meta.get("revision", 0))
        if int(payload.get("revision", -1)) != revision:
            raise ServiceError(409, "STORY_REVISION_CHANGED", "Draft changed after readback; read it again")
        if not verification.get("all_chunks_delivered") or int(verification.get("last_read_chunk_index", -1)) != len(chunks) - 1:
            next_index = int(verification.get("last_read_chunk_index", -1)) + 1
            raise ServiceError(409, "STORY_READBACK_INCOMPLETE", f"Read every current story chunk first; next chunk is {next_index}")
        if verification.get("content_sha256") != digest or payload.get("content_sha256") != digest:
            raise ServiceError(409, "STORY_READBACK_MISMATCH", "Story changed after readback; restart readback")
        if payload.get("missing_items") or payload.get("conflicts") or payload.get("final_consistency_pass") is not True:
            raise ServiceError(
                409,
                "STORY_VERIFICATION_INCOMPLETE",
                "Rewrite the draft and repeat full readback until missing_items and conflicts are empty and final_consistency_pass is true",
            )
        meta["status"] = "verified"
        meta["verified_at"] = now_iso()
        self._write_json(path / "story.json", meta)
        self._write_json(
            path / "verification.json",
            {
                "status": "verified",
                "revision": revision,
                "last_read_chunk_index": len(chunks) - 1,
                "all_chunks_delivered": True,
                "content_sha256": digest,
                "source_sha256": meta["source_sha256"],
                "missing_items": [],
                "conflicts": [],
                "final_consistency_pass": True,
                "verified_at": meta["verified_at"],
            },
        )
        return {
            "story_id": story_id,
            "title": meta["title"],
            "status": "verified",
            "revision": revision,
            "ready_for_sessions": True,
        }

    def create_session_from_story(self, story_id: str) -> dict[str, Any]:
        snapshot = self._snapshot(story_id)
        meta = snapshot["story"]
        if meta.get("status") != "verified":
            raise ServiceError(
                409,
                "STORY_NOT_VERIFIED",
                "Story must complete full readback verification before a session can start",
            )
        for _ in range(10):
            session_id = _new_id("sess", 32)
            try:
                self.storage.create_session_dir(session_id)
                break
            except FileExistsError:
                continue
        else:
            raise ServiceError(500, "SESSION_ID_FAILURE", "Could not allocate a unique session_id")

        created_at = now_iso()
        character_ids = [item["character_id"] for item in snapshot["characters"]]
        location_ids = [item["location_id"] for item in snapshot["locations"]]
        object_ids = [item["object_id"] for item in snapshot["objects"]]
        session = {
            "session_id": session_id,
            "status": "active",
            "created_at": created_at,
            "updated_at": created_at,
            "state_revision": 1,
            "last_completed_turn": 0,
            "last_audited_turn": 0,
            "turns_since_audit": 0,
            "next_turn_number": 1,
            "audit_required": False,
            "runtime_contract_version": "2.0",
            "source_story_id": story_id,
            "source_story_revision": meta.get("revision"),
        }
        manifest = {
            "session_id": session_id,
            "schema_version": 2,
            "state_revision": 1,
            "character_ids": character_ids,
            "location_ids": location_ids,
            "object_ids": object_ids,
            "audit_ids": [],
            "updated_at": created_at,
        }
        writes: dict[str, Any] = {
            "session.json": session,
            "manifest.json": manifest,
            "story_source.json": {
                "story_id": story_id,
                "title": meta.get("title"),
                "revision": meta.get("revision"),
                "template_sha256": meta.get("template_sha256"),
            },
            "chronology/manifest.json": {
                "session_id": session_id,
                "revision": 1,
                "active_part": "chronology_0001",
                "next_event_number": 1,
                "parts": [
                    {
                        "part_id": "chronology_0001",
                        "turn_from": None,
                        "turn_to": None,
                        "date_from": None,
                        "date_to": None,
                        "sealed": False,
                    }
                ],
            },
            "chronology/chronology_0001.json": {
                "session_id": session_id,
                "part_id": "chronology_0001",
                "events": [],
            },
        }
        for key, target in BASE_STATE_PATHS.items():
            writes[target] = _stamp_document(
                snapshot[key], session_id=session_id, state_revision=1, updated_turn=0
            )
        for character in snapshot["characters"]:
            cid = character["character_id"]
            prefix = f"characters/{cid}"
            writes[f"{prefix}/card.json"] = _stamp_document(
                character["card"],
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"character_id": cid},
            )
            writes[f"{prefix}/current_state.json"] = _stamp_document(
                character["current_state"],
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"character_id": cid},
            )
            writes[f"{prefix}/relationships.json"] = _stamp_document(
                character["relationships"],
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"owner_character_id": cid},
            )
            writes[f"{prefix}/knowledge.json"] = _stamp_document(
                character["knowledge"],
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"character_id": cid},
            )
        for location in snapshot["locations"]:
            lid = location["location_id"]
            writes[f"locations/{lid}.json"] = _stamp_document(
                location["state"],
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"location_id": lid},
            )
        for item in snapshot["objects"]:
            oid = item["object_id"]
            writes[f"objects/{oid}.json"] = _stamp_document(
                item["state"],
                session_id=session_id,
                state_revision=1,
                updated_turn=0,
                identity={"object_id": oid},
            )
        self.storage.write_json_batch(session_id, writes)
        return {
            "session_id": session_id,
            "story_id": story_id,
            "title": meta.get("title"),
            "status": "active",
            "state_revision": 1,
            "next_turn_number": 1,
            "cycle_position": 1,
            "next_required_action": (
                "Call getTurnPacket with player_input='Начать стартовую сцену по сохранённой истории' "
                "and read every chunk before writing."
            ),
        }
