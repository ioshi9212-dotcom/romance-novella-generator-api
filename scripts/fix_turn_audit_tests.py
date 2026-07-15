from pathlib import Path

path = Path(__file__).resolve().parent.parent / "tests" / "test_turn_persistence_audit.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    'assert relationship["b_to_a"]["current_view"] == "Рен учитывает результат хода 15"',
    'assert relationship["a_to_b"]["current_view"] == "Рен учитывает результат хода 15"',
)
text = text.replace(
    'response["proposed_updates"]["new_or_updated_characters"] = [{"id": "coworker_01", "age": 99}]',
    'response["proposed_updates"]["new_or_updated_characters"] = [{"id": "coworker_01", "name": "Ren Ashford", "role": "coworker", "age": 99}]',
)
path.write_text(text, encoding="utf-8")
