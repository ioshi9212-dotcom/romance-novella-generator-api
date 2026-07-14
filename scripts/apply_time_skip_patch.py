from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Pattern not found in {path}: {old[:160]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/bootstrap_normalizer.py",
    '''        "environment": current_state.get("environment") if isinstance(current_state.get("environment"), dict) else {"light": "не указано", "sound": "не указано", "air": "не указано", "details": []},
        "status": {''',
    '''        "environment": current_state.get("environment") if isinstance(current_state.get("environment"), dict) else {"light": "не указано", "sound": "не указано", "air": "не указано", "details": []},
        "time_skip_state": current_state.get("time_skip_state") if isinstance(current_state.get("time_skip_state"), dict) else {
            "allowed": False,
            "reason": "Пропуск времени ещё не открыт: нужна естественная пауза после завершённого смыслового бита.",
            "suggested_horizon": "до ближайшего значимого события",
            "blocked_by": [],
        },
        "status": {''',
)

replace_once(
    "app/scene_contract_builder.py",
    '''            "environment": current_state.get("environment", {}),
            "status": status,''',
    '''            "environment": current_state.get("environment", {}),
            "time_skip_state": current_state.get("time_skip_state", {}),
            "status": status,''',
)

replace_once(
    "app/state_updater.py",
    '''        for key in ["date", "time", "location", "weather", "scene_state", "outfit", "inventory", "nearby_items", "scene_goal", "active_character_ids", "nearby_character_ids", "environment"]:''',
    '''        for key in ["date", "time", "location", "weather", "scene_state", "outfit", "inventory", "nearby_items", "scene_goal", "active_character_ids", "nearby_character_ids", "environment", "time_skip_state"]:''',
)

replace_once(
    "app/scene_rules_compiler.py",
    '''    RuleSource(
        "SCENE_FORMAT",
        "prompts/scene_format_rules.md",
        ("rendered_text", "ровно 3", "relationships_panel", "proposed_updates"),
    ),''',
    '''    RuleSource(
        "TIME_SKIP",
        "rules/time_skip_rules.md",
        ("Пропустить время до ближайших событий", "естественной паузе", "time_skip_state", "немедленной опасности"),
    ),
    RuleSource(
        "SCENE_FORMAT",
        "prompts/scene_format_rules.md",
        ("rendered_text", "ровно 3", "relationships_panel", "proposed_updates"),
    ),''',
)

replace_once(
    "app/turn_processor.py",
    '''from app.scene_contract_builder import build_scene_contract
from app.scene_rules_compiler import compile_scene_rules, scene_rules_diagnostics
''',
    '''from app.scene_contract_builder import build_scene_contract
from app.scene_rules_compiler import compile_scene_rules, scene_rules_diagnostics
from app.time_skip import build_time_skip_contract
''',
)

replace_once(
    "app/turn_processor.py",
    '''SCENE_WRITER_TOOL_FLOW = """
Ты внутри tool-flow. Это не финальный ответ пользователю.

Если processTurn вернул несколько чанков, сначала прочитай все через getTurnPromptChunk и склей их по порядку. RUNTIME_SCENE_RULES — канонический контракт; SCENE_CONTRACT_JSON — state текущего хода.

Создай строго scene_response JSON без комментариев и markdown-обёртки. Не показывай JSON пользователю. Сразу вызови applyTurnResult и после успеха покажи только response.message_to_user.
""".strip()
''',
    '''SCENE_WRITER_TOOL_FLOW = """
Ты внутри tool-flow. Это не финальный ответ пользователю.

Если processTurn вернул несколько чанков, сначала прочитай все через getTurnPromptChunk и склей их по порядку. RUNTIME_SCENE_RULES — канонический контракт; SCENE_CONTRACT_JSON — state текущего хода.

Создай строго scene_response JSON без комментариев и markdown-обёртки. Не показывай JSON пользователю. Сразу вызови applyTurnResult и после успеха покажи только response.message_to_user.
""".strip()

TIME_SKIP_TOOL_FLOW = """
Ты внутри специального tool-flow пропуска времени. Это не финальный ответ пользователю.

Игрок явно выбрал «Пропустить время до ближайших событий». Прочитай все чанки, затем создай scene_response перехода: коротко суммируй реально прошедший интервал и открой новую сцену на пороге target_event. Не решай событие и не делай важный выбор за героиню.

Обязательно выполни TIME_SKIP_CONTRACT_JSON.time_skip.transition_rules и required_metadata. Сразу вызови applyTurnResult и после успеха покажи только response.message_to_user.
""".strip()
''',
)

replace_once(
    "app/turn_processor.py",
    '''        "director_guidance": _compact_dict(contract.get("director_guidance", {}) if isinstance(contract.get("director_guidance"), dict) else {}, 900),
        "npc_runtime": _compact_dict(contract.get("npc_runtime", {}) if isinstance(contract.get("npc_runtime"), dict) else {}, 420),''',
    '''        "director_guidance": _compact_dict(contract.get("director_guidance", {}) if isinstance(contract.get("director_guidance"), dict) else {}, 900),
        "time_skip": _compact_dict(contract.get("time_skip", {}) if isinstance(contract.get("time_skip"), dict) else {}, 900),
        "npc_runtime": _compact_dict(contract.get("npc_runtime", {}) if isinstance(contract.get("npc_runtime"), dict) else {}, 420),''',
)

replace_once(
    "app/turn_processor.py",
    '''def build_scene_prompt(scene_contract: dict[str, Any]) -> str:
    contract_json = json.dumps(_compact_contract(scene_contract), ensure_ascii=False, separators=(",", ":"))
    return (
        f"{SCENE_WRITER_TOOL_FLOW}\n\n"
        f"RUNTIME_SCENE_RULES:\n{COMPACT_SCENE_WRITER_PROMPT}\n\n"
        f"SCENE_CONTRACT_JSON:\n{contract_json}"
    )
''',
    '''def build_scene_prompt(scene_contract: dict[str, Any]) -> str:
    contract_json = json.dumps(_compact_contract(scene_contract), ensure_ascii=False, separators=(",", ":"))
    return (
        f"{SCENE_WRITER_TOOL_FLOW}\n\n"
        f"RUNTIME_SCENE_RULES:\n{COMPACT_SCENE_WRITER_PROMPT}\n\n"
        f"SCENE_CONTRACT_JSON:\n{contract_json}"
    )


def build_time_skip_prompt(time_skip_contract: dict[str, Any]) -> str:
    contract_json = json.dumps(_compact_contract(time_skip_contract), ensure_ascii=False, separators=(",", ":"))
    return (
        f"{TIME_SKIP_TOOL_FLOW}\n\n"
        f"RUNTIME_SCENE_RULES:\n{COMPACT_SCENE_WRITER_PROMPT}\n\n"
        f"TIME_SKIP_CONTRACT_JSON:\n{contract_json}"
    )
''',
)

replace_once(
    "app/turn_processor.py",
    '''def process_turn_debug_stub(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:''',
    '''def process_time_skip_gpt_actions(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    contract = build_time_skip_contract(bundle, player_input)
    prompt = build_time_skip_prompt(contract)
    target_event = (contract.get("time_skip") or {}).get("target_event") or {}
    rules_diagnostics = scene_rules_diagnostics()
    return {
        "status": "gpt_actions_time_skip_prompt_ready",
        "scene": None,
        "scene_prompt": prompt,
        "diagnostics": {
            "turn_mode": "time_skip",
            "target_event_id": target_event.get("id"),
            "target_event_title": target_event.get("title"),
            "compact_prompt_chars": len(prompt),
            "scene_rules": rules_diagnostics,
            "next_required_action": "generate transition scene_response internally, call applyTurnResult, then show response.message_to_user",
        },
    }


def process_turn_debug_stub(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:''',
)

replace_once(
    "app/main.py",
    '''from app.state_updater import StateUpdater
from app.turn_processor import process_turn_debug_stub, process_turn_gpt_actions
from app.validators import validate_bootstrap_result, validate_scene_response
''',
    '''from app.state_updater import StateUpdater
from app.time_skip import TimeSkipUnavailable, ensure_time_skip_state_patch, is_time_skip_command, time_skip_availability, validate_time_skip_scene_response
from app.turn_processor import process_time_skip_gpt_actions, process_turn_debug_stub, process_turn_gpt_actions
from app.validators import validate_bootstrap_result, validate_scene_response
''',
)

replace_once(
    "app/main.py",
    '''            "scene_prompt_sha256": pending.get("scene_prompt_sha256"),
        }''',
    '''            "scene_prompt_sha256": pending.get("scene_prompt_sha256"),
            "turn_mode": pending.get("turn_mode", "scene"),
            "target_event_id": pending.get("target_event_id"),
        }''',
)

replace_once(
    "app/main.py",
    '''def _save_pending_turn(manager: SessionManager, session_id: str, player_input: str, expected_turn_number: int) -> dict[str, Any]:
    pending = {
        "session_id": session_id,
        "turn_id": _new_turn_id(),
        "status": "pending",
        "player_input": player_input,
        "player_input_sha256": _hash_text(player_input),
        "expected_turn_number": expected_turn_number,
        "created_at": now_iso(),
    }''',
    '''def _save_pending_turn(
    manager: SessionManager,
    session_id: str,
    player_input: str,
    expected_turn_number: int,
    *,
    turn_mode: str = "scene",
    target_event_id: str | None = None,
) -> dict[str, Any]:
    pending = {
        "session_id": session_id,
        "turn_id": _new_turn_id(),
        "status": "pending",
        "turn_mode": turn_mode,
        "target_event_id": target_event_id,
        "player_input": player_input,
        "player_input_sha256": _hash_text(player_input),
        "expected_turn_number": expected_turn_number,
        "created_at": now_iso(),
    }''',
)

old_process = '''def _process_turn_locked(manager: SessionManager, session_id: str, request: TurnRequest, player_input: str, bundle: dict[str, Any]) -> dict:
    if request.mode == "debug_stub":
        result = process_turn_debug_stub(bundle, player_input)
        apply_result = StateUpdater(manager.storage).apply_scene_response(session_id, result["scene_response"])
        return {
            "session_id": session_id,
            "status": apply_result["status"],
            "scene": result["scene"],
            "scene_prompt": None,
            "turn_id": None,
            "expected_turn_number": apply_result.get("next_builder_hints", {}).get("maintenance", {}).get("last_saved_turn_number"),
            "diagnostics": result["diagnostics"] | {"apply_result": apply_result},
        }

    expected_turn_number = int(((bundle.get("current_state") or {}).get("turn_number", 0)) or 0) + 1
    existing_pending = _load_pending_turn(manager, session_id)
    if existing_pending.get("status") == "pending":
        same_input = existing_pending.get("player_input_sha256") == _hash_text(player_input)
        same_turn = int(existing_pending.get("expected_turn_number") or 0) == expected_turn_number
        if same_input and same_turn:
            has_prompt = isinstance(existing_pending.get("prompt_chunks"), list) and bool(existing_pending.get("prompt_chunks"))
            if has_prompt:
                return _pending_turn_response(existing_pending, session_id)
            # Recover a turn that was reserved before prompt generation completed.
            repaired_result = process_turn_gpt_actions(bundle, player_input)
            repaired_pending = _store_prompt_chunks(
                manager,
                session_id,
                existing_pending,
                repaired_result["scene_prompt"],
                turn_status=repaired_result["status"],
                turn_diagnostics=repaired_result["diagnostics"],
            )
            return _pending_turn_response(repaired_pending, session_id)
        raise HTTPException(
            status_code=409,
            detail="Another turn is still pending. Apply its result before sending a different player input.",
        )

    # Build the prompt before reserving the turn. A prompt-building exception must
    # not leave an empty pending_turn that blocks the session.
    result = process_turn_gpt_actions(bundle, player_input)
    pending = _save_pending_turn(manager, session_id, player_input, expected_turn_number)
    pending = _store_prompt_chunks(
        manager,
        session_id,
        pending,
        result["scene_prompt"],
        turn_status=result["status"],
        turn_diagnostics=result["diagnostics"],
    )
    return _pending_turn_response(pending, session_id)
'''

new_process = '''def _process_turn_locked(manager: SessionManager, session_id: str, request: TurnRequest, player_input: str, bundle: dict[str, Any]) -> dict:
    wants_time_skip = is_time_skip_command(player_input)
    if request.mode == "debug_stub":
        if wants_time_skip:
            raise HTTPException(status_code=409, detail="Time skip is available only in the normal gpt_actions flow.")
        result = process_turn_debug_stub(bundle, player_input)
        apply_result = StateUpdater(manager.storage).apply_scene_response(session_id, result["scene_response"])
        return {
            "session_id": session_id,
            "status": apply_result["status"],
            "scene": result["scene"],
            "scene_prompt": None,
            "turn_id": None,
            "expected_turn_number": apply_result.get("next_builder_hints", {}).get("maintenance", {}).get("last_saved_turn_number"),
            "diagnostics": result["diagnostics"] | {"apply_result": apply_result},
        }

    if wants_time_skip:
        availability = time_skip_availability(bundle)
        if not availability.get("allowed"):
            raise HTTPException(status_code=409, detail=availability.get("reason") or "Time skip is not available in the current frame.")
        processor = process_time_skip_gpt_actions
        turn_mode = "time_skip"
    else:
        processor = process_turn_gpt_actions
        turn_mode = "scene"

    expected_turn_number = int(((bundle.get("current_state") or {}).get("turn_number", 0)) or 0) + 1
    existing_pending = _load_pending_turn(manager, session_id)
    if existing_pending.get("status") == "pending":
        same_input = existing_pending.get("player_input_sha256") == _hash_text(player_input)
        same_turn = int(existing_pending.get("expected_turn_number") or 0) == expected_turn_number
        if same_input and same_turn:
            has_prompt = isinstance(existing_pending.get("prompt_chunks"), list) and bool(existing_pending.get("prompt_chunks"))
            if has_prompt:
                return _pending_turn_response(existing_pending, session_id)
            repair_processor = process_time_skip_gpt_actions if existing_pending.get("turn_mode") == "time_skip" else process_turn_gpt_actions
            repaired_result = repair_processor(bundle, player_input)
            repaired_pending = _store_prompt_chunks(
                manager,
                session_id,
                existing_pending,
                repaired_result["scene_prompt"],
                turn_status=repaired_result["status"],
                turn_diagnostics=repaired_result["diagnostics"],
            )
            return _pending_turn_response(repaired_pending, session_id)
        raise HTTPException(
            status_code=409,
            detail="Another turn is still pending. Apply its result before sending a different player input.",
        )

    # Build the prompt before reserving the turn. A prompt-building exception must
    # not leave an empty pending_turn that blocks the session.
    result = processor(bundle, player_input)
    target_event_id = (result.get("diagnostics") or {}).get("target_event_id")
    pending = _save_pending_turn(
        manager,
        session_id,
        player_input,
        expected_turn_number,
        turn_mode=turn_mode,
        target_event_id=target_event_id,
    )
    pending = _store_prompt_chunks(
        manager,
        session_id,
        pending,
        result["scene_prompt"],
        turn_status=result["status"],
        turn_diagnostics=result["diagnostics"],
    )
    return _pending_turn_response(pending, session_id)
'''
replace_once("app/main.py", old_process, new_process)

replace_once(
    "app/main.py",
    '''            pending = _require_pending_turn_match(manager, session_id, compatible_turn_id, normalized_scene_response, bundle)
            errors = validate_scene_response(normalized_scene_response)
            if errors:''',
    '''            pending = _require_pending_turn_match(manager, session_id, compatible_turn_id, normalized_scene_response, bundle)
            normalized_scene_response = ensure_time_skip_state_patch(normalized_scene_response, pending)
            errors = validate_scene_response(normalized_scene_response)
            errors.extend(validate_time_skip_scene_response(normalized_scene_response, pending, bundle))
            if errors:''',
)

replace_once(
    "app/main.py",
    '''    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/turn-prompt-chunk"''',
    '''    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except TimeSkipUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/v1/sessions/{session_id}/turn-prompt-chunk"''',
)
