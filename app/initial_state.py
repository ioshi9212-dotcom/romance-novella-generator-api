"""Canonicalize explicitly stated initial State participants by permanent character ID.

Only used during creation verification. Runtime turn state stays strict, since
its participants are already stored in canonical form. No character is ever
added to a scene by inference: a physical POV mention must actually exist.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any


def _key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.casefold().split())


def canonicalize_initial_state(
    state: dict[str, Any], roster: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    result = deepcopy(state)
    issues: list[str] = []
    by_id: dict[str, dict[str, Any]] = {
        row["id"]: row for row in roster
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    aliases: dict[str, set[str]] = defaultdict(set)
    for cid, row in by_id.items():
        aliases[_key(cid)].add(cid)
        for field in ("имя", "полное_имя", "имя_и_фамилия", "name"):
            candidate = row.get(field)
            if isinstance(candidate, str) and candidate.strip():
                aliases[_key(candidate)].add(cid)
                # Short given name is safe only when unique among the roster.
                aliases[_key(candidate.split()[0])].add(cid)

    def resolve(value: Any, context: str) -> str | None:
        if isinstance(value, dict):
            for field in ("id", "персонаж_id", "character_id", "имя", "name"):
                if value.get(field):
                    value = value[field]
                    break
            else:
                issues.append(f"{context}: не указан ID или имя персонажа")
                return None
        if not isinstance(value, str) or not value.strip():
            issues.append(f"{context}: требуется ID или имя персонажа")
            return None
        if value in by_id:
            return value
        matches = aliases.get(_key(value), set())
        if len(matches) == 1:
            return next(iter(matches))
        if len(matches) > 1:
            issues.append(f"{context}: имя {value!r} неоднозначно; укажи постоянный ID")
        else:
            issues.append(f"{context}: {value!r} не найден в реестре персонажей")
        return None

    original_pov = result.get("pov_id")
    if not original_pov and result.get("POV"):
        original_pov = result["POV"]
    resolved_pov = resolve(original_pov, "state.json.pov_id")
    if resolved_pov:
        result["pov_id"] = resolved_pov

    for channel in ("физически", "удалённо"):
        members = result.get(channel, [])
        if isinstance(members, dict):
            # Some builders use {"Имя": {"одежда": ...}} instead of a list.
            entries: list[Any] = [
                {"имя": key, **(detail if isinstance(detail, dict) else {})}
                for key, detail in members.items()
            ]
        elif isinstance(members, list):
            entries = members
        else:
            issues.append(
                f"state.json.{channel}: нужен список участников с ID, а не "
                f"{type(members).__name__}"
            )
            continue
        fixed = []
        for index, member in enumerate(entries):
            context = f"state.json.{channel}[{index}]"
            if isinstance(member, str):
                item = {}
                identifier = member
            elif isinstance(member, dict):
                item = deepcopy(member)
                identifier = next(
                    (item[key] for key in ("id", "персонаж_id", "character_id", "имя", "name")
                     if item.get(key)), None
                )
                if identifier is None and isinstance(item.get("персонаж"), dict):
                    identifier = item["персонаж"]
            else:
                issues.append(f"{context}: участник должен быть объектом или именем")
                fixed.append(member)
                continue
            canonical = resolve(identifier, context)
            if canonical:
                # The saved roster ID takes precedence over spelling variations
                # in the scene. The rest of the participant detail is preserved.
                item["id"] = canonical
                fixed.append(item)
            else:
                fixed.append(member)
        result[channel] = fixed

    return result, issues
