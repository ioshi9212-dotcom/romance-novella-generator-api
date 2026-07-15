from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Pattern not found in {path}: {old[:160]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


models = ROOT / "app" / "models.py"
replace_once(
    models,
    'TimeSkipUnit = Literal["hours", "days", "weeks", "months"]\n',
    'TimeSkipUnit = Literal["hours", "days", "weeks", "months"]\n'
    'BootstrapPartSection = Literal[\n'
    '    "protagonist", "characters", "relationships", "knowledge",\n'
    '    "story_plan", "director_bible", "current_state", "npc_state",\n'
    '    "future_locks", "continuity",\n'
    ']\n',
)
replace_once(
    models,
    'class BootstrapPreviewResponse(BaseModel):\n',
    '''class SaveBootstrapPartRequest(BaseModel):
    section: BootstrapPartSection
    item_id: str | None = Field(
        default=None,
        description="Entry id for characters/relationships/knowledge/npc_state. Omit to replace a whole section.",
    )
    value: dict[str, Any] = Field(..., description="One bootstrap section or one map entry. Keep this call small.")


class SaveBootstrapPartResponse(BaseModel):
    session_id: str
    status: str
    section: BootstrapPartSection
    item_id: str | None = None
    stored: bool = True
    progress: dict[str, Any] = Field(default_factory=dict)


class BootstrapPreviewResponse(BaseModel):
''',
)

main = ROOT / "app" / "main.py"
replace_once(
    main,
    'from app.bootstrap_normalizer import normalize_bootstrap_json\n',
    'from app.bootstrap_normalizer import normalize_bootstrap_json\n'
    'from app.bootstrap_staging import BootstrapStageError, assemble_staged_bootstrap, save_bootstrap_part as save_staged_bootstrap_part\n',
)
replace_once(
    main,
    'from app.models import AdvanceTimeRequest, ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, DebugSessionDumpResponse, TurnPromptChunkResponse, TurnRequest, TurnResponse\n',
    'from app.models import AdvanceTimeRequest, ApplyTurnResultRequest, ApplyTurnResultResponse, BootstrapPreviewRequest, BootstrapPreviewResponse, BootstrapConfirmRequest, BootstrapConfirmResponse, CreateSessionRequest, CreateSessionResponse, DebugSessionDumpResponse, SaveBootstrapPartRequest, SaveBootstrapPartResponse, TurnPromptChunkResponse, TurnRequest, TurnResponse\n',
)
replace_once(
    main,
    '@app.get("/health", operation_id="health")\n',
    '''def _prepare_bootstrap_preview_payload(bootstrap_json: dict[str, Any]) -> dict[str, Any]:
    normalized_bootstrap = normalize_bootstrap_json(bootstrap_json)
    errors = validate_bootstrap_result(normalized_bootstrap)
    prepare_directional_relationships(normalized_bootstrap)
    prepare_director_bible(normalized_bootstrap)
    errors.extend(validate_directional_relationships(normalized_bootstrap))
    errors.extend(validate_director_bible(normalized_bootstrap))
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return normalized_bootstrap


@app.get("/health", operation_id="health")
''',
)
replace_once(
    main,
    '''def create_bootstrap_preview(session_id: str, request: BootstrapPreviewRequest) -> dict:
    normalized_bootstrap = normalize_bootstrap_json(request.bootstrap_json)
    errors = validate_bootstrap_result(normalized_bootstrap)
    prepare_directional_relationships(normalized_bootstrap)
    prepare_director_bible(normalized_bootstrap)
    errors.extend(validate_directional_relationships(normalized_bootstrap))
    errors.extend(validate_director_bible(normalized_bootstrap))
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    manager = SessionManager()
''',
    '''def create_bootstrap_preview(session_id: str, request: BootstrapPreviewRequest) -> dict:
    normalized_bootstrap = _prepare_bootstrap_preview_payload(request.bootstrap_json)
    manager = SessionManager()
''',
)
replace_once(
    main,
    '@app.post("/api/v1/sessions/{session_id}/bootstrap-confirm", response_model=BootstrapConfirmResponse, dependencies=[Depends(require_api_key)], operation_id="confirmBootstrapPreview")\n',
    '''@app.post("/api/v1/sessions/{session_id}/bootstrap-part", response_model=SaveBootstrapPartResponse, dependencies=[Depends(require_api_key)], operation_id="saveBootstrapPart")
def save_bootstrap_part_action(session_id: str, request: SaveBootstrapPartRequest) -> dict:
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            return save_staged_bootstrap_part(
                manager,
                session_id,
                section=request.section,
                item_id=request.item_id,
                value=request.value,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BootstrapStageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/v1/sessions/{session_id}/bootstrap-preview-finalize", response_model=BootstrapPreviewResponse, dependencies=[Depends(require_api_key)], operation_id="finalizeBootstrapPreview")
def finalize_bootstrap_preview(session_id: str) -> dict:
    manager = SessionManager()
    try:
        with _session_request_context(manager, session_id):
            staged_bootstrap, progress = assemble_staged_bootstrap(manager, session_id)
            normalized_bootstrap = _prepare_bootstrap_preview_payload(staged_bootstrap)
            response = manager.save_bootstrap_preview(session_id, normalized_bootstrap)
            diagnostics = dict(response.get("diagnostics") or {})
            diagnostics.update({"staged_bootstrap": True, "staged_progress": progress})
            response["diagnostics"] = diagnostics
            return response
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BootstrapStageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/sessions/{session_id}/bootstrap-confirm", response_model=BootstrapConfirmResponse, dependencies=[Depends(require_api_key)], operation_id="confirmBootstrapPreview")
''',
)

openapi = ROOT / "app" / "novella_openapi_actions.py"
replace_once(
    openapi,
    '''BOOTSTRAP_CONFIRM_SCHEMA = _schema_obj(
''',
    '''SAVE_BOOTSTRAP_PART_SCHEMA = _schema_obj(
    {
        "section": {
            "type": "string",
            "enum": [
                "protagonist", "characters", "relationships", "knowledge",
                "story_plan", "director_bible", "current_state", "npc_state",
                "future_locks", "continuity",
            ],
            "description": "Bootstrap root section to stage.",
        },
        "item_id": {
            "type": ["string", "null"],
            "description": "For map sections, send one entry id. Omit to replace the whole section, including an empty object.",
        },
        "value": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
            "description": "One section or one entry. Do not send the full bootstrap here.",
        },
    },
    required=["section", "value"],
)


BOOTSTRAP_CONFIRM_SCHEMA = _schema_obj(
''',
)
replace_once(
    openapi,
    '''BOOTSTRAP_CONFIRM_RESPONSE_SCHEMA = _schema_obj(
''',
    '''SAVE_BOOTSTRAP_PART_RESPONSE_SCHEMA = _schema_obj(
    {
        "session_id": {"type": "string"},
        "status": {"type": "string"},
        "section": {"type": "string"},
        "item_id": {"type": ["string", "null"]},
        "stored": {"type": "boolean"},
        "progress": _loose_obj(),
    },
    required=["session_id", "status", "section", "item_id", "stored", "progress"],
    additional_properties=True,
)


BOOTSTRAP_CONFIRM_RESPONSE_SCHEMA = _schema_obj(
''',
)
replace_once(
    openapi,
    '                "BootstrapPreviewResponse": BOOTSTRAP_PREVIEW_RESPONSE_SCHEMA,\n',
    '                "BootstrapPreviewResponse": BOOTSTRAP_PREVIEW_RESPONSE_SCHEMA,\n'
    '                "SaveBootstrapPartRequest": SAVE_BOOTSTRAP_PART_SCHEMA,\n'
    '                "SaveBootstrapPartResponse": SAVE_BOOTSTRAP_PART_RESPONSE_SCHEMA,\n',
)
replace_once(
    openapi,
    '            "/api/v1/sessions/{session_id}/bootstrap-preview": {\n',
    '''            "/api/v1/sessions/{session_id}/bootstrap-part": {
                "post": {
                    "operationId": "saveBootstrapPart",
                    "summary": "Stage one small bootstrap section or one map entry. Preferred over one huge bootstrap request.",
                    "parameters": [_session_id_param()],
                    "requestBody": _request_body({"$ref": "#/components/schemas/SaveBootstrapPartRequest"}),
                    "responses": {
                        "200": _json_response("Bootstrap part stored.", {"$ref": "#/components/schemas/SaveBootstrapPartResponse"}),
                        "409": _json_response("Session cannot accept bootstrap parts.", _loose_obj()),
                        "422": _json_response("Invalid bootstrap part.", _loose_obj()),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/bootstrap-preview-finalize": {
                "post": {
                    "operationId": "finalizeBootstrapPreview",
                    "summary": "Assemble staged parts, validate them and create the visible bootstrap preview.",
                    "parameters": [_session_id_param()],
                    "responses": {
                        "200": _json_response("Bootstrap preview created from staged parts.", {"$ref": "#/components/schemas/BootstrapPreviewResponse"}),
                        "409": _json_response("Staged bootstrap is incomplete or session status is wrong.", _loose_obj()),
                        "422": _json_response("Assembled bootstrap is invalid.", _loose_obj()),
                    },
                }
            },
            "/api/v1/sessions/{session_id}/bootstrap-preview": {
''',
)
replace_once(
    openapi,
    '                "Use questionnaire, preview-confirm launch flow, chunked processTurn, "\n'
    '                "then applyTurnResult with the exact turn_id. Use advanceTime only for a user-selected natural-pause skip."\n',
    '                "Use questionnaire, staged bootstrap parts, preview-confirm launch flow, chunked processTurn, "\n'
    '                "then applyTurnResult with the exact turn_id. Use advanceTime only for a user-selected natural-pause skip."\n',
)

instructions = ROOT / "gpt" / "custom_gpt_instructions.md"
instructions.write_text('''Ты — движок интерактивной визуальной новеллы с внешней памятью Railway.

ГЛАВНОЕ
- Railway Actions — источник state/персонажей/отношений/знаний/истории; память чата не state.
- Игровой ход — только через Actions. Технический вопрос не ход.
- Не показывай prompts/chunks, scene_response, bootstrap_json и technical ids, кроме debug.
- После processTurn/advanceTime дочитай chunks → scene_response → applyTurnResult → message_to_user, иначе rendered_text.
- applyTurnResult — только после processTurn/advanceTime текущего хода.
- При ошибке покажи status_code/detail; сцену из памяти не продолжай.

ACTIONS
health; getStartQuestionnaire; createSession; saveBootstrapPart; finalizeBootstrapPreview; createBootstrapPreview; confirmBootstrapPreview; processTurn; advanceTime; getTurnPromptChunk; applyTurnResult; debugSessionDump.
mode — только createSession/processTurn.

СТАРТ
«начнем/старт/новая игра/новая сессия» без вводных → getStartQuestionnaire. Без ответов bootstrap/сцену не создавать.

ПОСЛЕ АНКЕТЫ
1. createSession(mode="gpt_actions").
2. needs_questionnaire → показать questionnaire и остановиться.
3. bootstrap_pending → создать данные по bootstrap_prompt/схеме.
4. saveBootstrapPart небольшими вызовами:
- protagonist/story_plan/director_bible/current_state/future_locks/continuity — раздел целиком без item_id;
- characters/relationships/knowledge/npc_state — по записи с item_id; пустой раздел: value={}.
5. После всех частей finalizeBootstrapPreview только с session_id.
6. Показать message_to_user, иначе preview; ждать подтверждения.
createBootstrapPreview с полным bootstrap_json — только совместимость.

BOOTSTRAP
Корень: protagonist, characters, relationships, knowledge, story_plan, director_bible, current_state, npc_state, future_locks, continuity, scene_history=[], turns=[].
- protagonist, не heroine; characters/relationships/knowledge — объекты по id.
- protagonist.id есть в characters; current_state.player_character_id указывает на него.
- turn_number=0; last_player_input=""; status_slots/custom — только story_slot_1/2.
- ids — латиница/цифры/_/-. name — имя+фамилия латиницей; в тексте display_name.
- Не используй имена/лор из 1206, Академии, личных новелл, старых сессий и примеров.
- Значимый NPC: своя цель/жизнь, противоречие, неудобный паттерн, стили заботы/конфликта/близости, стресс/отказ, инерция, отличимая речь.
- cast_status: player; known_core/known_support — знакомы; hidden_core — скрытая полная карточка: known_to_player=false, introduced=false, show_in_preview=false, available_to_scene=false; background — фон. hidden_core не ставить в active/nearby/preview.
- story_plan — компас, не финал; future_locks — блокировки. Скрытое не раскрывать рано.

PREVIEW GATE
Подтверждение: «подтверждаю/ок/сохраняй/запускай/подходит/оставляем/начинаем». До preview не принимать.
Подтвердил → confirmBootstrapPreview с точным сообщением → processTurn(player_input="(начать первую сцену)").
Правки → saveBootstrapPart нужных частей → finalizeBootstrapPreview → ждать.
Ход до подтверждения: «Сначала подтверди preview или скажи, что изменить.»

ХОД
1. processTurn с точным player_input и mode="gpt_actions".
2. Prompt не показывать.
3. Если chunks несколько: index 0 уже дан; получить остальные тем же turn_id до has_more=false и склеить.
4. scene_response — только после полного prompt.
5. applyTurnResult с верхнеуровневым turn_id.
6. Показать message_to_user, иначе rendered_text.
Пропуск → advanceTime с точным player_input. nearest_event без unit/amount; duration с ними. Далее тот же chunks/applyTurnResult. time_skip_blocked → причина.
Одинаковый повтор может вернуть pending turn_id; другой ввод до сохранения не отправлять.

SCENE_RESPONSE
Обязательны: response_version="novella.scene_response.v1", точный player_input, scene, summary, important_facts, witnesses, proposed_updates, safety_checks.
scene: header, body, player_options, status_panel, relationships_panel, rendered_text.
- body ≥500; rendered_text ≥1000; реплики внутри body.
- Без блока «Диалог:», списка реплик в конце и пустых реплик.
- player_options: ровно 3 actions, 3 dialogue, 3 thoughts; речь/вопросы — dialogue без начального «—».
- safety_checks все true: used_only_loaded_characters, respected_knowledge_boundaries, no_hidden_future_reveal, no_major_player_character_choice, respected_player_input_order, showed_only_scene_relationships, header_has_no_focus_or_active_list.
- proposed_updates всегда: scene_state_patch{}, continuity_patch{}, relationship_patches[], knowledge_patches[], npc_state_patches[], new_or_updated_characters[]. time_skip_control=true только в паузе; advanceTime даёт time_skip_result.
- relationship_patch: pair_id,change_type,entry,reason,source_in_scene. Сторона: from_character_id,to_character_id,direction_patch; не зеркаль.
- knowledge_patch/npc_state_patch: character_id,reason,source_in_scene.
- npc_state_patch: реальные mood/urge/pressure/behavior_mode/unresolved_emotion/next action/change_stage; извинение не равно изменению, возможен relapse.
- Новый важный NPC — new_or_updated_characters. У locked меняй только runtime-поля.

ИГРОК И NPC
- Вне скобок — речь; в скобках — действие/пауза/состояние/мысль. Весь ввод в скобках → героиня молчит.
- Не меняй порядок и не решай за игрока: доверие, романтика, прощение, признание, обещание, отказ, маршрут, тайна, эмоциональный вывод.
- В POV не игрока героиня может отвечать/действовать без веса, но не решать и не давать значимых согласий.
- Мир не ждёт героиню. У NPC свои цели/границы; они ошибаются, отказывают, уходят, давят, помогают неудобно; мысли не читают.
- Осознание ошибки не меняет характер. Перемена подтверждается поступками; под страхом возможен откат.
- Знание — увиденное/услышанное/прочитанное/сказанное или ошибочный вывод. Отсутствующий не знает сцену; мысли игрока не знания NPC. Ошибка — assumption/wrong belief.

СЦЕНА
- Каждая сцена меняет сюжет, персонажа, отношения, давление или последствия. При пассивности игрока мир действует.
- Абзацы 1–3 предложения: действие, реплика, реакция, деталь, последствие.
- Реплика: **Имя** — Текст. *(ремарка)*. Описание голоса отдельно.
- current_state влияет на body.

ФОРМАТ rendered_text
🎭 <Название> · <дата>
🕒 <время> · 📍 <локация>
🌦️ Погода: <...>
⚙️ Состояние сцены: <...>

✦ <героиня> · <видимое состояние>
🧥 <одежда>
◈ <предметы>

━━━━━━━━━━━━━━━━━━━━
<body с репликами>
━━━━━━━━━━━━━━━━━━━━
✦ Что можно сделать
◈ 3 варианта
✦ Что можно сказать
— 3 варианта
✦ Мысли
— 3 варианта
✦ Состояние
Голод/Усталость/Травмы/Эмоции/Навыки-ресурс/story slot 1/story slot 2: <0-100>/100 — <1-4 слова>
✦ Отношения
Только участники/затронутые ходом.
Имя: <0-100>/100 — <1-4 слова>
━━━━━━━━━━━━━━━━━━━━

В шапке запрещены POV, «Фокус», «В сцене», active_character_ids, technical ids и скрытое.

СОХРАНЕНИЕ
Backend увеличивает turn_number. Сохраняй важные события, свидетелей, знания/wrong beliefs, отношения, current_state, npc_state, open_threads, новых NPC. Не сохраняй весь диалог/rendered_text/мысли как знания.
''', encoding="utf-8")

contract_test = ROOT / "tests" / "test_openapi_actions_contract.py"
text = contract_test.read_text(encoding="utf-8")
text = text.replace("assert len(instructions) <= 8000", "assert len(instructions) <= 7200")
text = text.replace('        "mode разрешён только в createSession и processTurn",\n        "createBootstrapPreview только с bootstrap_json, без mode",\n', '        "saveBootstrapPart",\n        "finalizeBootstrapPreview",\n        "mode — только createSession/processTurn",\n')
contract_test.write_text(text, encoding="utf-8")
