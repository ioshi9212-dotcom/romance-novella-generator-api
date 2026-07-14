from __future__ import annotations

import re
from pathlib import Path


path = Path("app/turn_processor.py")
text = path.read_text(encoding="utf-8")

import_line = "from app.scene_rules_compiler import compile_scene_rules, scene_rules_diagnostics\n"
anchor = "from app.scene_contract_builder import build_scene_contract\n"
if import_line not in text:
    if anchor not in text:
        raise RuntimeError("turn_processor import anchor not found")
    text = text.replace(anchor, anchor + import_line, 1)

constant_pattern = re.compile(
    r'COMPACT_SCENE_WRITER_PROMPT = """.*?"""\.strip\(\)\n\n',
    re.DOTALL,
)
constant_replacement = '''SCENE_WRITER_TOOL_FLOW = """
Ты внутри tool-flow. Это не финальный ответ пользователю.

Если processTurn вернул несколько чанков, сначала прочитай все через getTurnPromptChunk и склей их по порядку. RUNTIME_SCENE_RULES — канонический контракт; SCENE_CONTRACT_JSON — state текущего хода.

Создай строго scene_response JSON без комментариев и markdown-обёртки. Не показывай JSON пользователю. Сразу вызови applyTurnResult и после успеха покажи только response.message_to_user.
""".strip()

# Backward-compatible public name. The value is compiled from repository rule files,
# never maintained as a second handwritten prompt.
COMPACT_SCENE_WRITER_PROMPT = compile_scene_rules()

'''
text, count = constant_pattern.subn(constant_replacement, text, count=1)
if count != 1:
    raise RuntimeError(f"Expected one handwritten prompt block, replaced {count}")

old_build = '''def build_scene_prompt(scene_contract: dict[str, Any]) -> str:
    return f"{COMPACT_SCENE_WRITER_PROMPT}\\n\\nSCENE_CONTRACT_JSON:\\n{json.dumps(_compact_contract(scene_contract), ensure_ascii=False, separators=(',', ':'))}"
'''
new_build = '''def build_scene_prompt(scene_contract: dict[str, Any]) -> str:
    contract_json = json.dumps(_compact_contract(scene_contract), ensure_ascii=False, separators=(",", ":"))
    return (
        f"{SCENE_WRITER_TOOL_FLOW}\\n\\n"
        f"RUNTIME_SCENE_RULES:\\n{COMPACT_SCENE_WRITER_PROMPT}\\n\\n"
        f"SCENE_CONTRACT_JSON:\\n{contract_json}"
    )
'''
if old_build not in text:
    raise RuntimeError("build_scene_prompt anchor not found")
text = text.replace(old_build, new_build, 1)

old_process = '''def process_turn_gpt_actions(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    contract = build_scene_contract(bundle, player_input=player_input)
    prompt = build_scene_prompt(contract)
    return {
'''
new_process = '''def process_turn_gpt_actions(bundle: dict[str, Any], player_input: str) -> dict[str, Any]:
    contract = build_scene_contract(bundle, player_input=player_input)
    prompt = build_scene_prompt(contract)
    rules_diagnostics = scene_rules_diagnostics()
    return {
'''
if old_process not in text:
    raise RuntimeError("process_turn_gpt_actions anchor not found")
text = text.replace(old_process, new_process, 1)

old_diag = '''            "compact_prompt_chars": len(prompt),
            "next_required_action": "generate scene_response internally, call applyTurnResult, then show response.message_to_user",
'''
new_diag = '''            "compact_prompt_chars": len(prompt),
            "scene_rules": rules_diagnostics,
            "next_required_action": "generate scene_response internally, call applyTurnResult, then show response.message_to_user",
'''
if old_diag not in text:
    raise RuntimeError("prompt diagnostics anchor not found")
text = text.replace(old_diag, new_diag, 1)

path.write_text(text, encoding="utf-8")
