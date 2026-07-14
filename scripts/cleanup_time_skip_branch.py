from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def update(path: str, transform) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    updated = transform(text)
    if updated != text:
        file_path.write_text(updated, encoding="utf-8")


def clean_director(text: str) -> str:
    text = text.replace(
        'TIME_SKIP_UNITS = {"hours", "days", "weeks", "months"}\nTIME_SKIP_UNITS = {"hours", "days", "weeks", "months"}\n',
        'TIME_SKIP_UNITS = {"hours", "days", "weeks", "months"}\n',
    )
    block = '''def _normalise_time_flow(value: Any, story_plan: dict[str, Any]) -> dict[str, Any]:
    source = deepcopy(value) if isinstance(value, dict) else {}
    allowed_units = [unit for unit in _string_list(source.get("allowed_units"), 4) if unit in TIME_SKIP_UNITS]
    if not allowed_units:
        allowed_units = ["hours", "days", "weeks"]
    maxima = source.get("max_amounts") if isinstance(source.get("max_amounts"), dict) else {}
    return {
        **source,
        "current_period": _text(source.get("current_period") or story_plan.get("current_story_position"), "early_story"),
        "default_mode": _text(source.get("default_mode"), "nearest_event"),
        "allow_nearest_event": source.get("allow_nearest_event") is not False,
        "allowed_units": allowed_units,
        "max_amounts": {
            "hours": _integer(maxima.get("hours"), 24, 1, 365),
            "days": _integer(maxima.get("days"), 14, 1, 365),
            "weeks": _integer(maxima.get("weeks"), 4, 1, 52),
            "months": _integer(maxima.get("months"), 1, 1, 12),
        },
        "last_skip": source.get("last_skip") if isinstance(source.get("last_skip"), dict) else None,
    }
'''
    text = text.replace(block + "\n\n" + block, block)
    for unit, amount in (("hours", 1), ("days", 2), ("weeks", 1)):
        duplicated = (
            f'            "skip_unit": "{unit}",\n'
            f'            "skip_amount": {amount},\n'
            f'            "skip_unit": "{unit}",\n'
            f'            "skip_amount": {amount},\n'
        )
        single = f'            "skip_unit": "{unit}",\n            "skip_amount": {amount},\n'
        text = text.replace(duplicated, single)
    if text.count('TIME_SKIP_UNITS = {"hours", "days", "weeks", "months"}') != 1:
        raise RuntimeError("TIME_SKIP_UNITS cleanup failed")
    if text.count("def _normalise_time_flow(") != 1:
        raise RuntimeError("_normalise_time_flow cleanup failed")
    return text


def sync_scene_format(text: str) -> str:
    old = "- `proposed_updates` всегда содержит `scene_state_patch`, `continuity_patch`, `relationship_patches`, `knowledge_patches`, `npc_state_patches`, `director_bible_patches`, `new_or_updated_characters`;"
    new = old + " для `advanceTime` дополнительно обязателен `time_skip_result`;"
    if new not in text:
        if old not in text:
            raise RuntimeError("scene format anchor missing")
        text = text.replace(old, new, 1)
    return text


def sync_instruction(text: str) -> str:
    replacements = [
        (
            "health — сервер; getStartQuestionnaire — анкета; createSession — сессия; createBootstrapPreview — preview; confirmBootstrapPreview — подтверждение; processTurn — turn_id/первый chunk; getTurnPromptChunk — остальные chunks; applyTurnResult — сохранение; debugSessionDump — диагностика.",
            "health — сервер; getStartQuestionnaire — анкета; createSession — сессия; createBootstrapPreview — preview; confirmBootstrapPreview — подтверждение; processTurn — обычный ход; advanceTime — выбранный пропуск; getTurnPromptChunk — chunks; applyTurnResult — сохранение; debugSessionDump — диагностика.",
        ),
        (
            "Корень: protagonist, characters, relationships, knowledge, story_plan, current_state, npc_state, future_locks, continuity, scene_history=[], turns=[].",
            "Корень: protagonist, characters, relationships, knowledge, story_plan, director_bible, current_state, npc_state, future_locks, continuity, scene_history=[], turns=[].",
        ),
        (
            "6. Показать message_to_user, иначе rendered_text.\nОдинаковый processTurn может вернуть тот же pending turn_id. Другой ввод до сохранения не отправлять. ResponseTooLargeError решается chunks/компакцией.",
            "6. Показать message_to_user, иначе rendered_text.\nВыбран пропуск → advanceTime с точным player_input. nearest_event без unit/amount; duration с ними. Далее тот же chunks/applyTurnResult. time_skip_blocked → показать причину и продолжить обычным ходом.\nОдинаковый processTurn/advanceTime может вернуть тот же pending turn_id. Другой ввод до сохранения не отправлять. ResponseTooLargeError решается chunks/компакцией.",
        ),
        (
            "proposed_updates всегда: scene_state_patch{}, continuity_patch{}, relationship_patches[], knowledge_patches[], npc_state_patches[], new_or_updated_characters[].",
            "proposed_updates всегда: scene_state_patch{}, continuity_patch{}, relationship_patches[], knowledge_patches[], npc_state_patches[], new_or_updated_characters[]. Сохраняй scene_state_patch.time_skip_control; true только в естественной паузе. advanceTime также возвращает time_skip_result.",
        ),
    ]
    for old, new in replacements:
        if new in text:
            continue
        if old not in text:
            raise RuntimeError(f"instruction anchor missing: {old[:80]}")
        text = text.replace(old, new, 1)
    return text


update("app/director_bible.py", clean_director)
update("prompts/scene_format_rules.md", sync_scene_format)
update("gpt/custom_gpt_instructions.md", sync_instruction)
