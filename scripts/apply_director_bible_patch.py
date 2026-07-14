from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Pattern not found in {path}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_after(path: str, anchor: str, addition: str) -> None:
    replace_once(path, anchor, anchor + addition)


# Fix one defensive normalisation edge before wiring the module.
replace_once(
    "app/director_bible.py",
    "    events_source = source.get(\"event_queue\")\n    if not isinstance(events_source, list) or len(events_source) < 3:\n        defaults = _default_events(data, hooks)\n        events_source = list(events_source or []) + defaults[len(events_source or []):]\n",
    "    events_source = source.get(\"event_queue\")\n    existing_events = list(events_source) if isinstance(events_source, list) else []\n    if len(existing_events) < 3:\n        defaults = _default_events(data, hooks)\n        existing_events += defaults[len(existing_events):]\n    events_source = existing_events\n",
)

# bootstrap_normalizer.py
insert_after(
    "app/bootstrap_normalizer.py",
    "import re\n",
    "\nfrom app.director_bible import prepare_director_bible\n",
)
replace_once(
    "app/bootstrap_normalizer.py",
    "    return {\n        \"protagonist\": protagonist,\n        \"characters\": characters,\n        \"relationships\": relationships,\n        \"knowledge\": knowledge,\n        \"story_plan\": story_plan,\n        \"current_state\": current_state,\n        \"npc_state\": data.get(\"npc_state\") if isinstance(data.get(\"npc_state\"), dict) else {},\n        \"future_locks\": data.get(\"future_locks\") if isinstance(data.get(\"future_locks\"), dict) else {\"hidden_character_seeds\": [], \"do_not_reveal_yet\": []},\n        \"continuity\": data.get(\"continuity\") if isinstance(data.get(\"continuity\"), dict) else {},\n        \"scene_history\": data.get(\"scene_history\") if isinstance(data.get(\"scene_history\"), list) else [],\n        \"turns\": data.get(\"turns\") if isinstance(data.get(\"turns\"), list) else [],\n    }\n",
    "    normalized = {\n        \"protagonist\": protagonist,\n        \"characters\": characters,\n        \"relationships\": relationships,\n        \"knowledge\": knowledge,\n        \"story_plan\": story_plan,\n        \"current_state\": current_state,\n        \"npc_state\": data.get(\"npc_state\") if isinstance(data.get(\"npc_state\"), dict) else {},\n        \"director_bible\": data.get(\"director_bible\") if isinstance(data.get(\"director_bible\"), dict) else {},\n        \"future_locks\": data.get(\"future_locks\") if isinstance(data.get(\"future_locks\"), dict) else {\"hidden_character_seeds\": [], \"do_not_reveal_yet\": []},\n        \"continuity\": data.get(\"continuity\") if isinstance(data.get(\"continuity\"), dict) else {},\n        \"scene_history\": data.get(\"scene_history\") if isinstance(data.get(\"scene_history\"), list) else [],\n        \"turns\": data.get(\"turns\") if isinstance(data.get(\"turns\"), list) else [],\n    }\n    prepare_director_bible(normalized)\n    return normalized\n",
)

# session_manager.py
insert_after(
    "app/session_manager.py",
    "from app.directional_relationships import BOOTSTRAP_DIRECTION_RULES, append_directional_preview, prepare_directional_relationships\n",
    "from app.director_bible import prepare_director_bible\n",
)
replace_once("app/session_manager.py", '    "story_plan.json",\n    "current_state.json",', '    "story_plan.json",\n    "director_bible.json",\n    "current_state.json",')
replace_once("app/session_manager.py", '            "story_plan.json": {},\n            "current_state.json": {},', '            "story_plan.json": {},\n            "director_bible.json": {},\n            "current_state.json": {},')
replace_once(
    "app/session_manager.py",
    "        prepare_npc_runtime_map(bootstrap_json)\n\n        session =",
    "        prepare_npc_runtime_map(bootstrap_json)\n        prepare_director_bible(bootstrap_json)\n\n        session =",
)
replace_once(
    "app/session_manager.py",
    '        self.storage.write_json(session_id, "story_plan.json", bootstrap_json["story_plan"])\n        self.storage.write_json(session_id, "current_state.json", bootstrap_json["current_state"])',
    '        self.storage.write_json(session_id, "story_plan.json", bootstrap_json["story_plan"])\n        self.storage.write_json(session_id, "director_bible.json", bootstrap_json.get("director_bible", {}))\n        self.storage.write_json(session_id, "current_state.json", bootstrap_json["current_state"])',
)
replace_once(
    "app/session_manager.py",
    "        prepare_npc_runtime_map(bootstrap_json)\n        session = self.storage.read_json(session_id, \"session.json\")",
    "        prepare_npc_runtime_map(bootstrap_json)\n        prepare_director_bible(bootstrap_json)\n        session = self.storage.read_json(session_id, \"session.json\")",
)
replace_once(
    "app/session_manager.py",
    '                "directional_relationships_enabled": True,\n',
    '                "directional_relationships_enabled": True,\n                "director_bible_enabled": True,\n                "event_queue_count": len((bootstrap_json.get("director_bible") or {}).get("event_queue", [])),\n',
)

# bootstrapper.py legacy/debug file list and stale prompt language.
replace_once("app/bootstrapper.py", '    "story_plan.json",\n    "current_state.json",', '    "story_plan.json",\n    "director_bible.json",\n    "current_state.json",')
replace_once(
    "app/bootstrapper.py",
    "- Не раскрывай будущих важных персонажей полностью, если персонаж игрока их ещё не знает.\n- Для неизвестных будущих фигур делай только seed в future_locks.hidden_character_seeds, без имени и без полной карточки.\n",
    "- Будущих важных hidden_core создай сразу полными карточками, но не показывай в preview и не ставь в active/nearby до раскрытия.\n- `future_locks` хранит только технические блокировки; скрытый лор, крючки и события хранятся в `director_bible`.\n",
)
insert_after(
    "app/bootstrapper.py",
    "- В npc_state для значимых NPC задай коротко: current_goal, current_route, current_pressure, next_self_action_if_ignored.\n",
    "- Создай director_bible: world_truth, hidden_lore, character_functions, story_hooks, planned_reveals, active_conflicts, event_queue, time_anchors, do_not_resolve_early, continuity_truths и pacing.\n",
)

# bootstrap_setup.py runtime bootstrap prompt.
replace_once(
    "app/bootstrap_setup.py",
    "Корень: protagonist, characters, relationships, knowledge, story_plan, current_state, npc_state, future_locks, continuity, scene_history=[], turns=[].",
    "Корень: protagonist, characters, relationships, knowledge, story_plan, director_bible, current_state, npc_state, future_locks, continuity, scene_history=[], turns=[].",
)
insert_after(
    "app/bootstrap_setup.py",
    "Не фиксируй единственный финал. NPC имеют собственные дела и маршруты. Первые сцены не должны превращаться в инструкцию, квест или процедуру.\n",
    "\nDIRECTOR BIBLE — СКРЫТО ОТ ПОЛЬЗОВАТЕЛЯ\nСоздай отдельный авторский файл, чтобы история не превращалась в кашу и не выдумывала тайны по ходу:\n- world_truth: core_truth, world_rules, hidden_cause;\n- hidden_lore: минимум одна конкретная причинная истина с reveal_policy и evidence_chain;\n- character_functions для каждого known_core/known_support/hidden_core: story_role, pressure_source, conflict_function, private_goal, do_not_flatten_into;\n- story_hooks: минимум два незакрытых крючка;\n- planned_reveals: что раскрывается, earliest_turn, prerequisites и forbidden_before;\n- active_conflicts и do_not_resolve_early;\n- event_queue: минимум три ближайших события с priority, earliest/latest turn, conditions, participants, purpose, scene_pressure, next_if_ignored и time_hint;\n- time_anchors, continuity_truths, future_consequences и pacing.\nСобытия не являются рельсами: они должны адаптироваться к действиям игрока. Не решай выбор героини заранее. Не выводи director_bible в preview. `future_locks` оставь только технической блокировкой раскрытия.\n",
)

# storage.py
replace_once("app/storage.py", '            "story_plan.json",\n            "current_state.json",', '            "story_plan.json",\n            "director_bible.json",\n            "current_state.json",')

# scene_contract_builder.py
insert_after(
    "app/scene_contract_builder.py",
    "from app.id_utils import pair_id\n",
    "from app.director_bible import build_director_guidance\n",
)
replace_once(
    "app/scene_contract_builder.py",
    '        "story_compass": {\n',
    '        "director_guidance": build_director_guidance(bundle),\n        "story_compass": {\n',
)

# turn_processor.py compact transport.
replace_once(
    "app/turn_processor.py",
    '        "story_compass": _compact_dict(contract.get("story_compass", {}) if isinstance(contract.get("story_compass"), dict) else {}, 900),\n',
    '        "story_compass": _compact_dict(contract.get("story_compass", {}) if isinstance(contract.get("story_compass"), dict) else {}, 900),\n        "director_guidance": _compact_dict(contract.get("director_guidance", {}) if isinstance(contract.get("director_guidance"), dict) else {}, 900),\n',
)

# main.py validation and patch application.
insert_after(
    "app/main.py",
    "from app.directional_relationships import apply_directional_relationship_patches, prepare_directional_relationships, validate_directional_relationships\n",
    "from app.director_bible import apply_director_bible_patches, prepare_director_bible, validate_director_bible\n",
)
replace_once(
    "app/main.py",
    "    prepare_directional_relationships(normalized_bootstrap)\n    errors.extend(validate_directional_relationships(normalized_bootstrap))\n",
    "    prepare_directional_relationships(normalized_bootstrap)\n    prepare_director_bible(normalized_bootstrap)\n    errors.extend(validate_directional_relationships(normalized_bootstrap))\n    errors.extend(validate_director_bible(normalized_bootstrap))\n",
)
replace_once(
    "app/main.py",
    "            result = apply_directional_relationship_patches(\n                manager.storage,\n                session_id,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            _mark_pending_turn_applied",
    "            result = apply_directional_relationship_patches(\n                manager.storage,\n                session_id,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            result = apply_director_bible_patches(\n                manager.storage,\n                session_id,\n                normalized_scene_response,\n                bundle,\n                result,\n            )\n            _mark_pending_turn_applied",
)

# scene rule compiler.
replace_once(
    "app/scene_rules_compiler.py",
    "    RuleSource(\n        \"HIDDEN_CONTENT\",\n        \"rules/hidden_character_rules.md\",\n        (\"hidden_core\", \"полная карточка\", \"не раскры\"),\n    ),\n",
    "    RuleSource(\n        \"HIDDEN_CONTENT\",\n        \"rules/hidden_character_rules.md\",\n        (\"hidden_core\", \"полная карточка\", \"не раскры\"),\n    ),\n    RuleSource(\n        \"DIRECTOR_BIBLE\",\n        \"rules/director_bible_rules.md\",\n        (\"director_guidance\", \"event_queue\", \"author_only\", \"director_bible_patches\"),\n    ),\n",
)

# scene format rules mention the new output patch.
replace_once(
    "prompts/scene_format_rules.md",
    "- `proposed_updates` всегда содержит `scene_state_patch`, `continuity_patch`, `relationship_patches`, `knowledge_patches`, `npc_state_patches`, `new_or_updated_characters`;",
    "- `proposed_updates` всегда содержит `scene_state_patch`, `continuity_patch`, `relationship_patches`, `knowledge_patches`, `npc_state_patches`, `director_bible_patches`, `new_or_updated_characters`;",
)

# bootstrap schema: keep current formatting and add one compact property block.
replace_once(
    "schemas/bootstrap_output.schema.json",
    '    "story_plan",\n    "current_state",',
    '    "story_plan",\n    "director_bible",\n    "current_state",',
)
director_schema = '''    "director_bible": {
      "type": "object",
      "additionalProperties": true,
      "required": ["world_truth", "hidden_lore", "character_functions", "story_hooks", "planned_reveals", "active_conflicts", "event_queue", "time_anchors", "do_not_resolve_early", "continuity_truths", "future_consequences", "pacing"],
      "properties": {
        "version": {"type": "integer", "const": 1},
        "world_truth": {"type": "object", "required": ["core_truth", "world_rules", "hidden_cause"], "properties": {"core_truth": {"type": "string", "minLength": 1}, "world_rules": {"type": "array", "items": {"type": "string"}}, "hidden_cause": {"type": "string", "minLength": 1}}},
        "hidden_lore": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["id", "truth", "status", "reveal_policy", "known_by", "related_character_ids", "evidence_chain"], "properties": {"id": {"type": "string"}, "truth": {"type": "string", "minLength": 1}, "status": {"type": "string"}, "reveal_policy": {"type": "string", "minLength": 1}, "known_by": {"type": "array", "items": {"type": "string"}}, "related_character_ids": {"type": "array", "items": {"type": "string"}}, "evidence_chain": {"type": "array", "items": {"type": "string"}}}}},
        "character_functions": {"type": "object", "additionalProperties": {"type": "object", "required": ["story_role", "pressure_source", "conflict_function", "private_goal", "do_not_flatten_into"]}},
        "story_hooks": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["id", "hook", "status", "pressure", "next_escalation", "earliest_turn"]}},
        "planned_reveals": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["id", "reveal", "status", "earliest_turn", "prerequisites", "forbidden_before"]}},
        "active_conflicts": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["id", "description", "status", "pressure", "next_escalation", "do_not_resolve_with"]}},
        "event_queue": {"type": "array", "minItems": 3, "items": {"type": "object", "required": ["id", "title", "status", "priority", "earliest_turn", "latest_turn", "conditions", "participants", "purpose", "scene_pressure", "next_if_ignored", "time_hint"], "properties": {"status": {"type": "string", "enum": ["planned", "ready", "triggered", "completed", "blocked", "deferred"]}, "priority": {"type": "integer", "minimum": 0, "maximum": 100}, "earliest_turn": {"type": "integer", "minimum": 0}, "latest_turn": {"type": "integer", "minimum": 0}}}},
        "time_anchors": {"type": "array"},
        "do_not_resolve_early": {"type": "array", "items": {"type": "string"}},
        "continuity_truths": {"type": "array", "items": {"type": "string"}},
        "future_consequences": {"type": "array", "items": {"type": "string"}},
        "pacing": {"type": "object", "required": ["current_phase", "quiet_scene_budget", "major_reveal_spacing", "notes"]}
      },
      "description": "Author-only story bible. Never include it in the user-visible bootstrap preview."
    },
'''
replace_once(
    "schemas/bootstrap_output.schema.json",
    '    "current_state": {\n',
    director_schema + '    "current_state": {\n',
)

# scene contract schema.
replace_once(
    "schemas/scene_contract.schema.json",
    '    "knowledge_boundaries",\n    "output_requirements"',
    '    "knowledge_boundaries",\n    "director_guidance",\n    "output_requirements"',
)
replace_once(
    "schemas/scene_contract.schema.json",
    '    "story_compass": {\n      "type": "object"\n    },\n',
    '    "story_compass": {\n      "type": "object"\n    },\n    "director_guidance": {\n      "type": "object"\n    },\n',
)

# Scene response schema is minified; mutate structurally and keep it minified.
scene_schema_path = ROOT / "schemas/scene_response.schema.json"
scene_schema = json.loads(scene_schema_path.read_text(encoding="utf-8"))
proposed = scene_schema["properties"]["proposed_updates"]["properties"]
proposed["director_bible_patches"] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "event_updates": {"type": "array", "items": {"$ref": "#/$defs/directorStatusPatch"}},
        "hook_updates": {"type": "array", "items": {"$ref": "#/$defs/directorStatusPatch"}},
        "reveal_updates": {"type": "array", "items": {"$ref": "#/$defs/directorStatusPatch"}},
        "conflict_updates": {"type": "array", "items": {"$ref": "#/$defs/directorStatusPatch"}},
        "add_future_consequences": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "pacing_patch": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "current_phase": {"type": "string", "minLength": 1},
                "quiet_scene_budget": {"type": "integer", "minimum": 0, "maximum": 5},
                "add_notes": {"type": "array", "items": {"type": "string", "minLength": 1}},
            },
        },
    },
}
scene_schema.setdefault("$defs", {})["directorStatusPatch"] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "reason", "source_in_scene"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "status": {"type": "string", "minLength": 1},
        "reason": {"type": "string", "minLength": 1},
        "source_in_scene": {"type": "string", "minLength": 1},
        "pressure": {"type": "string", "minLength": 1},
        "next_escalation": {"type": "string", "minLength": 1},
        "next_if_ignored": {"type": "string", "minLength": 1},
        "time_hint": {"type": "string", "minLength": 1},
        "earliest_turn": {"type": "integer", "minimum": 0},
        "priority": {"type": "integer", "minimum": 0, "maximum": 100},
    },
}
scene_schema_path.write_text(json.dumps(scene_schema, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
