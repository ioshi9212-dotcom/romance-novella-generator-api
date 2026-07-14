from pathlib import Path


path = Path("app/relationship_state.py")
text = path.read_text(encoding="utf-8")

old_signature = '''def _direction_block(
    raw: Any,
    legacy_view: Any,
    legacy_scores: dict[str, Any],
    defaults: dict[str, int],
    text_defaults: dict[str, str],
    source_id: str,
    target_id: str,
) -> dict[str, Any]:'''
new_signature = '''def _direction_block(
    raw: Any,
    legacy_view: Any,
    legacy_scores: dict[str, Any],
    defaults: dict[str, int],
    text_defaults: dict[str, str],
    source_id: str,
    target_id: str,
    allow_legacy_scores: bool,
) -> dict[str, Any]:'''

old_score_logic = '''        if value is None and key == "attraction":
            value = source_scores.get("romantic_interest", legacy_scores.get("romantic_interest"))
        if value is None and key in legacy_scores:
            value = legacy_scores.get(key)'''
new_score_logic = '''        if value is None and key == "attraction":
            value = source_scores.get("romantic_interest")
            if value is None and allow_legacy_scores:
                value = legacy_scores.get("romantic_interest")
        if value is None and allow_legacy_scores and key in legacy_scores:
            value = legacy_scores.get(key)'''

old_a_call = '''        character_a,
        character_b,
    )
    b_to_a = _direction_block('''
new_a_call = '''        character_a,
        character_b,
        character_a != protagonist_id,
    )
    b_to_a = _direction_block('''

old_b_call = '''        character_b,
        character_a,
    )

    compatibility_scores = {
        "trust": round((a_to_b["scores"]["trust"] + b_to_a["scores"]["trust"]) / 2),
        "tension": shared["scores"]["tension"],
        "attachment": round((a_to_b["scores"]["attachment"] + b_to_a["scores"]["attachment"]) / 2),
        "respect": round((a_to_b["scores"]["respect"] + b_to_a["scores"]["respect"]) / 2),
        "fear": round((a_to_b["scores"]["fear"] + b_to_a["scores"]["fear"]) / 2),
        "curiosity": round((a_to_b["scores"]["curiosity"] + b_to_a["scores"]["curiosity"]) / 2),
        "romantic_interest": round((a_to_b["scores"]["attraction"] + b_to_a["scores"]["attraction"]) / 2),
    }'''
new_b_call = '''        character_b,
        character_a,
        character_b != protagonist_id,
    )

    if character_a == protagonist_id:
        compatibility_direction = b_to_a
    elif character_b == protagonist_id:
        compatibility_direction = a_to_b
    else:
        compatibility_direction = None

    if compatibility_direction is not None:
        compatibility_scores = {
            "trust": compatibility_direction["scores"]["trust"],
            "tension": shared["scores"]["tension"],
            "attachment": compatibility_direction["scores"]["attachment"],
            "respect": compatibility_direction["scores"]["respect"],
            "fear": compatibility_direction["scores"]["fear"],
            "curiosity": compatibility_direction["scores"]["curiosity"],
            "romantic_interest": compatibility_direction["scores"]["attraction"],
        }
    else:
        compatibility_scores = {
            "trust": round((a_to_b["scores"]["trust"] + b_to_a["scores"]["trust"]) / 2),
            "tension": shared["scores"]["tension"],
            "attachment": round((a_to_b["scores"]["attachment"] + b_to_a["scores"]["attachment"]) / 2),
            "respect": round((a_to_b["scores"]["respect"] + b_to_a["scores"]["respect"]) / 2),
            "fear": round((a_to_b["scores"]["fear"] + b_to_a["scores"]["fear"]) / 2),
            "curiosity": round((a_to_b["scores"]["curiosity"] + b_to_a["scores"]["curiosity"]) / 2),
            "romantic_interest": round((a_to_b["scores"]["attraction"] + b_to_a["scores"]["attraction"]) / 2),
        }'''

for old, new, label in [
    (old_signature, new_signature, "signature"),
    (old_score_logic, new_score_logic, "legacy score logic"),
    (old_a_call, new_a_call, "a_to_b call"),
    (old_b_call, new_b_call, "b_to_a call and compatibility"),
]:
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise SystemExit(f"Expected {label} block not found")

path.write_text(text, encoding="utf-8")
