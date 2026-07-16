from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one marker in {path}, found {count}: {old[:160]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/bootstrap_preview_transport.py",
    '''BOOTSTRAP_STAGING_TRANSPORT_RULES = """
ТРАНСПОРТ BOOTSTRAP ЧЕРЕЗ ACTIONS — ОБЯЗАТЕЛЬНО
- Не отправляй полный мир одним большим createBootstrapPreview: даже корректный JSON может превысить лимит Action-запроса.
- Сохраняй bootstrap через saveBootstrapPart небольшими вызовами.
- protagonist, story_plan, director_bible, current_state, future_locks и continuity сохраняй отдельными секциями.
- characters, relationships, knowledge и npc_state сохраняй по одному item_id за вызов.
- После сохранения всех обязательных частей вызови finalizeBootstrapPreview.
- Если finalizeBootstrapPreview сообщает has_more_preview_chunks=true, не показывай первый кусок отдельно. Получи остальные части через getBootstrapPreviewChunk по порядку, склей без изменений и только затем покажи пользователю полный preview.
- Не подтверждай preview и не запускай сцену, пока пользователь не увидел весь склеенный текст и явно его не подтвердил.
""".strip()
''',
    '''BOOTSTRAP_STAGING_TRANSPORT_RULES = """
ТРАНСПОРТ BOOTSTRAP ЧЕРЕЗ ACTIONS — ОБЯЗАТЕЛЬНО
- Основной путь: saveBootstrapPart небольшими вызовами, затем finalizeBootstrapPreview.
- В saveBootstrapPart передавай ровно section, value и item_id только для одной записи map-раздела.
- protagonist, story_plan, director_bible, current_state, future_locks и continuity сохраняй как section+value без item_id.
- characters, relationships, knowledge и npc_state сохраняй по одной записи: section+item_id+value; пустой раздел — section+value={}.
- Не передавай protagonist, characters, relationships, knowledge, story_plan, director_bible, current_state, npc_state, future_locks или continuity как отдельные kwargs любого Action.
- scene_history и turns не отправляй: staged backend сам создаёт оба пустых списка.
- В finalizeBootstrapPreview передавай только session_id, без body и без дополнительных kwargs.
- createBootstrapPreview — только запасная совместимость: единственное поле body — bootstrap_json, а все root fields находятся внутри него.
- Если preview разбит на части, дочитай getBootstrapPreviewChunk по порядку, склей без изменений и только затем покажи пользователю.
- Не подтверждай preview и не запускай сцену, пока пользователь не увидел полный склеенный текст и явно его не подтвердил.
""".strip()
''',
)

replace_once(
    "gpt/custom_gpt_instructions.md",
    "health; getStartQuestionnaire; createSession; saveBootstrapPart; finalizeBootstrapPreview; createBootstrapPreview; confirmBootstrapPreview; processTurn; advanceTime; getTurnPromptChunk; applyTurnResult; debugSessionDump.",
    "health; getStartQuestionnaire; createSession; saveBootstrapPart; finalizeBootstrapPreview; createBootstrapPreview; getBootstrapPreviewChunk; confirmBootstrapPreview; processTurn; advanceTime; getTurnPromptChunk; applyTurnResult; debugSessionDump.",
)

replace_once(
    "gpt/custom_gpt_instructions.md",
    '''4. saveBootstrapPart небольшими вызовами:
- protagonist/story_plan/director_bible/current_state/future_locks/continuity — раздел целиком без item_id;
- characters/relationships/knowledge/npc_state — по записи с item_id; пустой раздел: value={}.
5. После всех частей finalizeBootstrapPreview только с session_id.
6. Показать message_to_user, иначе preview; ждать подтверждения.
createBootstrapPreview с полным bootstrap_json — только совместимость.
''',
    '''4. saveBootstrapPart: только section, value и item_id для одной записи; Корневые разделы не передавай как kwargs.
- protagonist/story_plan/director_bible/current_state/future_locks/continuity — section+value без item_id;
- characters/relationships/knowledge/npc_state — section+item_id+value; пустой раздел: section+value={}.
- scene_history и turns не отправляй: сервер создаёт пустые списки.
5. finalizeBootstrapPreview: только session_id, без knowledge/npc_state/continuity и других kwargs.
6. Если has_more_preview_chunks=true, дочитай getBootstrapPreviewChunk, склей все части, затем покажи preview и жди подтверждения.
createBootstrapPreview: только bootstrap_json; все корневые поля строго внутри него. Это запасная совместимость, не основной путь.
''',
)

replace_once(
    "app/novella_openapi_actions.py",
    '''BOOTSTRAP_PREVIEW_SCHEMA = _schema_obj(
    {
        "bootstrap_json": {
            "$ref": "#/components/schemas/BootstrapPayload",
            "description": "Canonical request field. It must contain the entire bootstrap object and all root fields.",
        },
        "protagonist": _bootstrap_compat(_loose_obj()),
        "characters": _bootstrap_compat(_loose_obj()),
        "relationships": _bootstrap_compat(_loose_obj()),
        "knowledge": _bootstrap_compat(_loose_obj()),
        "story_plan": _bootstrap_compat(_loose_obj()),
        "director_bible": _bootstrap_compat(_loose_obj()),
        "current_state": _bootstrap_compat(_loose_obj()),
        "npc_state": _bootstrap_compat(_loose_obj()),
        "future_locks": _bootstrap_compat(_loose_obj()),
        "continuity": _bootstrap_compat(_loose_obj()),
        "scene_history": _bootstrap_compat({"type": "array", "items": _loose_obj()}),
        "turns": _bootstrap_compat({"type": "array", "items": _loose_obj()}),
    },
    required=["bootstrap_json"],
)
''',
    '''BOOTSTRAP_PREVIEW_SCHEMA = _schema_obj(
    {
        "bootstrap_json": {
            "$ref": "#/components/schemas/BootstrapPayload",
            "description": (
                "Compatibility-only complete bootstrap request. The JSON body must contain exactly one field: "
                "bootstrap_json. Keep every bootstrap root field inside bootstrap_json; never pass root fields "
                "such as knowledge, npc_state, continuity, scene_history or turns as Action kwargs."
            ),
        },
    },
    required=["bootstrap_json"],
)
''',
)

replace_once(
    "app/novella_openapi_actions.py",
    '''                    "summary": (
                        "Validate and save pending bootstrap JSON as a visible "
                        "preview. Do not start the scene."
                    ),
''',
    '''                    "summary": (
                        "Compatibility-only full preview call. Send exactly one body field named bootstrap_json; "
                        "never pass bootstrap root fields as separate Action kwargs. Prefer saveBootstrapPart."
                    ),
''',
)

for temporary_path in [
    ROOT / "scripts" / "apply_bootstrap_action_kwargs_fix.py",
    ROOT / ".github" / "workflows" / "apply-bootstrap-action-kwargs-fix.yml",
]:
    if temporary_path.exists():
        temporary_path.unlink()
