from pathlib import Path

path = Path(__file__).resolve().parent / "apply_time_skip_patch.py"
text = path.read_text(encoding="utf-8")
needle = "    '''def build_scene_prompt(scene_contract: dict[str, Any]) -> str:"
replacement = "    r'''def build_scene_prompt(scene_contract: dict[str, Any]) -> str:"
if text.count(needle) != 2:
    raise RuntimeError(f"Expected two build_scene_prompt template strings, got {text.count(needle)}")
text = text.replace(needle, replacement, 2)
path.write_text(text, encoding="utf-8")
