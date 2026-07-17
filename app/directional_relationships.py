from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.id_utils import pair_id
from app.relationship_state import apply_relationship_patch, normalize_relationship_pair


BOOTSTRAP_DIRECTION_RULES = """

НАПРАВЛЕННЫЕ ОТНОШЕНИЯ
Для каждой стартовой пары known_core/known_support заполни shared, a_to_b и b_to_a.
- shared: type, status, shared_history, unresolved_threads, recent_changes, last_major_event.
- Каждое направление: scores, current_view, current_need, current_expectation, access_boundary, interpretation_bias, unresolved_emotion, unresolved_grievances, wrong_beliefs, care_risk.
- a_to_b и b_to_a всегда объекты, не строки; русский текст помещай внутрь current_view и других полей.
- Стороны не обязаны чувствовать одинаково. Любовь не равна доверию; привязанность может сочетаться с обидой, ревностью, страхом и разными ожиданиями доступа.
- Для каждого known_core обязательны хотя бы одна претензия, одно ошибочное убеждение, одна несовпадающая граница близости и способ ухудшить ситуацию, пытаясь помочь.
""".strip()


def _visible_name(card: dict[str, Any], fallback: str) -> str:
    for key in ("display_name", "visible_name", "name_ru", "russian_name", "name"):
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def prepare_directional_relationships(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return data
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    protagonist = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    current_state = data.get("current_state") if isinstance(data.get("current_state"), dict) else {}
    protagonist_id = str(protagonist.get("id") or current_state.get("player_character_id") or "pc_01")
    relationships = data.get("relationships") if isinstance(data.get("relationships"), dict) else {}

    for character_id, card in characters.items():
        if character_id == protagonist_id or not isinstance(card, dict):
            continue
        if card.get("cast_status") not in {"known_core", "known_support"}:
            continue
        pid = pair_id(protagonist_id, str(character_id))
        if pid not in relationships:
            relationships[pid] = {
                "pair_id": pid,
                "character_a": protagonist_id,
                "character_b": str(character_id),
                "type": "starting_relationship",
                "status": "отношения существуют до начала истории",
                "shared_history": [],
                "recent_changes": [],
                "open_threads": [],
            }

    normalized: dict[str, Any] = {}
    for pid, relationship in relationships.items():
        if not isinstance(relationship, dict):
            continue
        pair = normalize_relationship_pair(relationship, characters, protagonist_id)
        pair["pair_id"] = str(pid)
        normalized[str(pid)] = pair
    data["relationships"] = normalized
    return data


def validate_directional_relationships(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    relationships = data.get("relationships") if isinstance(data.get("relationships"), dict) else {}
    protagonist = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    protagonist_id = str(protagonist.get("id") or (data.get("current_state") or {}).get("player_character_id") or "pc_01")

    for character_id, card in characters.items():
        if character_id == protagonist_id or not isinstance(card, dict):
            continue
        if card.get("cast_status") not in {"known_core", "known_support"}:
            continue
        pid = pair_id(protagonist_id, str(character_id))
        rel = relationships.get(pid)
        if not isinstance(rel, dict):
            errors.append(f"relationships must contain directional pair {pid}")
            continue
        for direction_key in ("a_to_b", "b_to_a"):
            direction = rel.get(direction_key)
            if not isinstance(direction, dict):
                errors.append(f"relationships.{pid}.{direction_key} must be an object")
                continue
            scores = direction.get("scores")
            if not isinstance(scores, dict):
                errors.append(f"relationships.{pid}.{direction_key}.scores must be an object")
            for field in (
                "current_view", "current_need", "current_expectation", "access_boundary",
                "interpretation_bias", "unresolved_emotion", "care_risk",
            ):
                if not isinstance(direction.get(field), str) or not direction[field].strip():
                    errors.append(f"relationships.{pid}.{direction_key}.{field} must be concrete")
            for field in ("unresolved_grievances", "wrong_beliefs"):
                values = direction.get(field)
                if not isinstance(values, list) or not values:
                    errors.append(f"relationships.{pid}.{direction_key}.{field} must contain at least one item")
        shared = rel.get("shared")
        if not isinstance(shared, dict):
            errors.append(f"relationships.{pid}.shared must be an object")

        a_scores = ((rel.get("a_to_b") or {}).get("scores") or {})
        b_scores = ((rel.get("b_to_a") or {}).get("scores") or {})
        same_scores = all(a_scores.get(key) == b_scores.get(key) for key in set(a_scores) | set(b_scores))
        same_view = (rel.get("a_to_b") or {}).get("current_view") == (rel.get("b_to_a") or {}).get("current_view")
        if card.get("cast_status") == "known_core" and same_scores and same_view:
            errors.append(f"relationships.{pid} must be asymmetric for known_core; both directions are identical")
    return errors


def append_directional_preview(preview: str, data: dict[str, Any]) -> str:
    prepare_directional_relationships(data)
    characters = data.get("characters") if isinstance(data.get("characters"), dict) else {}
    relationships = data.get("relationships") if isinstance(data.get("relationships"), dict) else {}
    protagonist = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    protagonist_id = str(protagonist.get("id") or (data.get("current_state") or {}).get("player_character_id") or "pc_01")

    lines = [preview.rstrip(), "", "### Направленные отношения на старте"]
    shown = 0
    for pid, rel in relationships.items():
        if not isinstance(rel, dict) or protagonist_id not in {rel.get("character_a"), rel.get("character_b")}:
            continue
        other_id = rel.get("character_b") if rel.get("character_a") == protagonist_id else rel.get("character_a")
        card = characters.get(other_id) if isinstance(characters.get(other_id), dict) else {}
        if card.get("cast_status") not in {"known_core", "known_support"}:
            continue

        if rel.get("character_a") == protagonist_id:
            player_to_other = rel.get("a_to_b") or {}
            other_to_player = rel.get("b_to_a") or {}
        else:
            player_to_other = rel.get("b_to_a") or {}
            other_to_player = rel.get("a_to_b") or {}
        other_name = _visible_name(card, str(other_id))
        player_name = _visible_name(characters.get(protagonist_id, {}), "Героиня")

        lines.extend([
            f"- **{other_name} → {player_name}:**",
            f"  - хочет: {other_to_player.get('current_need', '—')}",
            f"  - ожидает / считает допустимым: {other_to_player.get('current_expectation', '—')}; {other_to_player.get('access_boundary', '—')}",
            f"  - искажает через: {other_to_player.get('interpretation_bias', '—')}",
            f"  - незакрытая претензия: {(other_to_player.get('unresolved_grievances') or ['—'])[0]}",
            f"  - ошибочное убеждение: {(other_to_player.get('wrong_beliefs') or ['—'])[0]}",
            f"  - как может сделать хуже, помогая: {other_to_player.get('care_risk', '—')}",
            f"- **{player_name} → {other_name}:**",
            f"  - видит так: {player_to_other.get('current_view', '—')}",
            f"  - хочет: {player_to_other.get('current_need', '—')}",
            f"  - граница: {player_to_other.get('access_boundary', '—')}",
            f"  - незакрытая претензия: {(player_to_other.get('unresolved_grievances') or ['—'])[0]}",
        ])
        shown += 1
    if not shown:
        lines.append("- На старте нет уже знакомых значимых персонажей.")
    return "\n".join(lines).strip()


def apply_directional_relationship_patches(
    storage: Any,
    session_id: str,
    scene_response: dict[str, Any],
    bundle_before_scene: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    updates = scene_response.get("proposed_updates") if isinstance(scene_response.get("proposed_updates"), dict) else {}
    patches = updates.get("relationship_patches") if isinstance(updates.get("relationship_patches"), list) else []
    if not patches:
        return result

    characters = storage.read_characters(session_id)
    protagonist_id = str((bundle_before_scene.get("current_state") or {}).get("player_character_id") or "pc_01")
    relationships = storage.read_relationships(session_id)
    turn_number = int((storage.read_json(session_id, "current_state.json", default={}) or {}).get("turn_number") or 0)

    result.setdefault("applied", {}).setdefault("relationships", [])
    result.setdefault("rejected", [])
    changed_any = False

    for patch in patches:
        if not isinstance(patch, dict):
            continue
        uses_directional_fields = any(key in patch for key in ("direction_patch", "a_to_b", "b_to_a", "shared_patch", "from_character_id", "to_character_id"))
        if not uses_directional_fields:
            continue
        pid = str(patch.get("pair_id") or "")
        if not pid:
            result["rejected"].append({"target": "relationships", "reason": "missing pair_id", "severity": "error"})
            continue
        if not str(patch.get("reason") or "").strip() or not str(patch.get("source_in_scene") or "").strip():
            result["rejected"].append({
                "target": f"relationships.{pid}",
                "reason": "directional relationship patch requires reason and source_in_scene",
                "severity": "error",
            })
            continue
        base = relationships.get(pid)
        if not isinstance(base, dict):
            result["rejected"].append({"target": f"relationships.{pid}", "reason": "directional patch requires an existing pair", "severity": "error"})
            continue
        normalized = normalize_relationship_pair(base, characters, protagonist_id)
        updated, error = apply_relationship_patch(normalized, patch, turn_number=turn_number)
        if error:
            result["rejected"].append({"target": f"relationships.{pid}", "reason": error, "severity": "error"})
            continue
        storage.write_relationship_pair(session_id, pid, updated)
        relationships[pid] = updated
        result["applied"]["relationships"].append({"pair_id": pid, "operation": "patch_directional_pair"})
        changed_any = True

    if result.get("rejected"):
        result["status"] = "partially_applied"
        result.setdefault("next_builder_hints", {})["repair_required"] = True
    elif changed_any:
        result["status"] = result.get("status") or "applied"
    return result
