"""Regression checks for scene-first GPT instructions and recoverable relationship commits."""
from __future__ import annotations

import json
from pathlib import Path

from test_commit_turn import commit, packet
from test_prepare_turn import ready


ROOT = Path(__file__).resolve().parents[1]


def test_custom_gpt_instructions_are_synced_and_stage_scene_before_json():
    canonical = (ROOT / "gpt/custom_gpt_instructions.md").read_text(encoding="utf-8")
    paste_version = (ROOT / "gpt/ВСТАВИТЬ_В_ПОЛЕ_INSTRUCTIONS.txt").read_text(encoding="utf-8")
    assert canonical == paste_version
    assert len(canonical) < 8_000

    stages = (
        "1. **Художественная сцена.**",
        "2. **Проверка готового текста.**",
        "3. **Техническая фиксация.**",
        "4. **Сохранение.**",
    )
    positions = [canonical.index(marker) for marker in stages]
    assert positions == sorted(positions)

    rules = (ROOT / "runtime/rules.md").read_text(encoding="utf-8")
    assert "RELATIONSHIP_CHANGE_TOO_LARGE" in canonical
    assert "RELATIONSHIP_CHANGE_TOO_LARGE" in rules
    assert "Не удаляй фактически заслуженный показатель" in rules


def test_rejected_first_impression_can_be_corrected_without_rewriting_scene(ready):
    client, url, root = ready
    state_file = root / "state.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["физически"].append({"id": "aiden"})
    state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    prepared = packet(ready)
    scene = "Эйден впервые увидел Елену и заинтересовался её ответом."
    inflated, _ = commit(
        ready, prepared, scene=scene,
        relationship_changes=[{
            "owner_id": "aiden", "parameter": "первое впечатление",
            "initial_value": 56,
        }],
    )
    assert inflated.status_code == 409, inflated.text
    assert inflated.json()["detail"]["code"] == "RELATIONSHIP_CHANGE_TOO_LARGE"
    assert not (root / "ходы.jsonl").exists()

    saved, payload = commit(
        ready, prepared, scene=scene,
        relationship_changes=[{
            "owner_id": "aiden", "parameter": "первое впечатление",
            "initial_value": 2,
        }],
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "saved"
    stored = json.loads((root / "отношения.json").read_text(encoding="utf-8"))
    assert stored["персонажи"]["aiden"]["к_POV"]["параметры"] == {
        "доверие": 42, "первое впечатление": 2,
    }
    archive = [
        json.loads(line)
        for line in (root / "ходы.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(archive) == 1
    assert archive[0]["сцена"] == payload["scene"] == scene
