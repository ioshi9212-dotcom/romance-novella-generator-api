from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest


def _base_bundle() -> dict:
    return {
        "current_state": {
            "player_character_id": "pc_01",
            "active_character_ids": ["pc_01"],
            "status": {
                "hunger": "норма",
                "fatigue": "низкая",
                "injuries": [],
                "emotional_state": "ровно",
                "skills": [],
                "custom": [
                    {"id": "story_slot_1", "label": "Давление", "value": "низкое"},
                    {"id": "story_slot_2", "label": "Отклик", "value": "низкий"},
                ],
            },
        },
        "story_plan": {"status_slots": []},
        "characters": {},
        "relationships": {},
    }


def _long_body() -> str:
    return " ".join(["Свет у двери дрожит, и героиня задерживает дыхание." for _ in range(40)])


def test_v9_prompt_headings_match_visible_renderer():
    from app.turn_processor import COMPACT_SCENE_WRITER_PROMPT

    assert "✦ Что можно сделать" in COMPACT_SCENE_WRITER_PROMPT
    assert "✦ Что можно сказать" in COMPACT_SCENE_WRITER_PROMPT
    assert "✦ Мысли" in COMPACT_SCENE_WRITER_PROMPT
    assert "✦ Что <имя героини> могла бы сказать" not in COMPACT_SCENE_WRITER_PROMPT
    assert "✦ Мысли <имя героини>" not in COMPACT_SCENE_WRITER_PROMPT


def test_v9_normalizer_fallback_options_do_not_use_banned_placeholders():
    from app.scene_response_normalizer import normalize_scene_response

    data = {
        "scene": {
            "header": {"player_name": "Мира"},
            "body": _long_body(),
            "player_options": {},
        },
        "proposed_updates": {"scene_state_patch": {}},
    }

    rendered = normalize_scene_response(data, _base_bundle())["scene"]["rendered_text"]
    banned = [
        "Проверить важную деталь",
        "Сделать следующий физический шаг",
        "Удержать безопасную дистанцию",
        "Сказать коротко и прямо",
        "Задать один конкретный вопрос",
        "Отметить, что изменилось",
        "Сдержать первую реакцию",
    ]
    for phrase in banned:
        assert phrase not in rendered


def test_v9_status_patch_is_visible_in_same_turn_footer():
    from app.scene_response_normalizer import normalize_scene_response

    data = {
        "scene": {
            "header": {"player_name": "Мира"},
            "body": _long_body(),
            "player_options": {
                "actions": ["Отойти к стойке.", "Посмотреть на дверь.", "Убрать телефон."],
                "dialogue": ["Что происходит?", "Говорите яснее.", "Я слушаю."],
                "thoughts": ["Это нехорошо.", "Надо не паниковать.", "Кто-то врёт."],
            },
        },
        "proposed_updates": {
            "scene_state_patch": {
                "status": {"fatigue": "высокая усталость"}
            }
        },
    }

    rendered = normalize_scene_response(data, _base_bundle())["scene"]["rendered_text"]
    assert "Усталость: 75/100 — высокая усталость" in rendered


def test_storage_rejects_session_id_path_traversal(tmp_path: Path):
    from app.storage import JsonStorage

    storage = JsonStorage(tmp_path)
    for unsafe_id in ("../outside", "nested/session", r"nested\session", ".", "..", ""):
        with pytest.raises(ValueError):
            storage.ensure_session_dir(unsafe_id)

    assert not (tmp_path.parent / "outside").exists()


def test_storage_rejects_unsafe_relative_filenames(tmp_path: Path):
    from app.storage import JsonStorage

    storage = JsonStorage(tmp_path)
    session_id = "session_safe"
    storage.ensure_session_dir(session_id)

    for unsafe_filename in (
        "../escape.json",
        "state/../../escape.json",
        "/tmp/escape.json",
        r"state\..\escape.json",
    ):
        with pytest.raises(ValueError):
            storage.write_json(session_id, unsafe_filename, {"unsafe": True})

    assert not (tmp_path / "escape.json").exists()


def test_storage_write_json_uses_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app import storage as storage_module

    real_replace = storage_module.os.replace
    replace_calls: list[tuple[Path, Path]] = []

    def recording_replace(source, target):
        replace_calls.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(storage_module.os, "replace", recording_replace)

    storage = storage_module.JsonStorage(tmp_path)
    session_id = "session_safe"
    storage.write_json(session_id, "current_state.json", {"turn_number": 7})

    assert storage.read_json(session_id, "current_state.json") == {"turn_number": 7}
    assert len(replace_calls) == 1

    temporary_path, final_path = replace_calls[0]
    assert final_path == storage.session_dir(session_id) / "current_state.json"
    assert temporary_path.parent == final_path.parent
    assert temporary_path != final_path
    assert not temporary_path.exists()


def test_session_transaction_serializes_same_session(tmp_path: Path):
    from app.storage import JsonStorage

    first_storage = JsonStorage(tmp_path)
    second_storage = JsonStorage(tmp_path)
    session_id = "session_safe"
    first_storage.ensure_session_dir(session_id)

    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def hold_first_transaction():
        with first_storage.session_transaction(session_id):
            first_entered.set()
            assert release_first.wait(timeout=2)

    def enter_second_transaction():
        assert first_entered.wait(timeout=2)
        with second_storage.session_transaction(session_id):
            second_entered.set()

    first_thread = threading.Thread(target=hold_first_transaction)
    second_thread = threading.Thread(target=enter_second_transaction)
    first_thread.start()
    second_thread.start()

    assert first_entered.wait(timeout=2)
    assert not second_entered.wait(timeout=0.1)
    release_first.set()

    first_thread.join(timeout=2)
    second_thread.join(timeout=2)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert second_entered.is_set()


def test_session_transaction_discards_all_staged_writes_on_body_error(tmp_path: Path):
    from app.storage import JsonStorage

    storage = JsonStorage(tmp_path)
    session_id = "session_safe"
    storage.write_json(session_id, "a.json", {"value": "old-a"})
    storage.write_json(session_id, "b.json", {"value": "old-b"})

    with pytest.raises(RuntimeError, match="stop before commit"):
        with storage.session_transaction(session_id):
            storage.write_json(session_id, "a.json", {"value": "new-a"})
            storage.write_json(session_id, "b.json", {"value": "new-b"})
            assert storage.read_json(session_id, "a.json") == {"value": "new-a"}
            assert storage.read_json(session_id, "b.json") == {"value": "new-b"}
            raise RuntimeError("stop before commit")

    assert storage.read_json(session_id, "a.json") == {"value": "old-a"}
    assert storage.read_json(session_id, "b.json") == {"value": "old-b"}


def test_session_transaction_rolls_back_partial_disk_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app import storage as storage_module

    storage = storage_module.JsonStorage(tmp_path)
    session_id = "session_safe"
    storage.write_json(session_id, "a.json", {"value": "old-a"})
    storage.write_json(session_id, "b.json", {"value": "old-b"})

    real_replace = storage_module.os.replace
    failed = False

    def fail_second_target_once(source, target):
        nonlocal failed
        source_path = Path(source)
        target_path = Path(target)
        if not failed and source_path.parent.name == "staged" and target_path.name == "b.json":
            failed = True
            raise OSError("simulated disk failure")
        real_replace(source, target)

    monkeypatch.setattr(storage_module.os, "replace", fail_second_target_once)

    with pytest.raises(OSError, match="simulated disk failure"):
        with storage.session_transaction(session_id):
            storage.write_json(session_id, "a.json", {"value": "new-a"})
            storage.write_json(session_id, "b.json", {"value": "new-b"})

    assert failed is True
    assert storage.read_json(session_id, "a.json") == {"value": "old-a"}
    assert storage.read_json(session_id, "b.json") == {"value": "old-b"}
    transactions_root = storage.session_dir(session_id) / ".transactions"
    assert not transactions_root.exists() or not any(transactions_root.iterdir())


def test_session_transaction_recovers_prepared_journal_after_restart(tmp_path: Path):
    from app.storage import JsonStorage

    storage = JsonStorage(tmp_path)
    session_id = "session_safe"
    storage.write_json(session_id, "current_state.json", {"turn_number": 4})
    session_root = storage.session_dir(session_id)

    transaction_dir = session_root / ".transactions" / "interrupted"
    backup_dir = transaction_dir / "backup"
    staged_dir = transaction_dir / "staged"
    backup_dir.mkdir(parents=True)
    staged_dir.mkdir(parents=True)
    (backup_dir / "0000.json").write_text(
        json.dumps({"turn_number": 4}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (session_root / "current_state.json").write_text(
        json.dumps({"turn_number": 5}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (transaction_dir / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "state": "prepared",
                "entries": [
                    {
                        "target": "current_state.json",
                        "staged": "staged/0000.json",
                        "backup": "backup/0000.json",
                        "backup_exists": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    restarted_storage = JsonStorage(tmp_path)
    with restarted_storage.session_transaction(session_id):
        pass

    assert restarted_storage.read_json(session_id, "current_state.json") == {"turn_number": 4}
    assert not transaction_dir.exists()


def test_process_turn_retry_reuses_pending_turn_and_blocks_different_input():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    created = client.post(
        "/api/v1/sessions",
        json={
            "genre": "urban mysticism",
            "setting_request": "night office",
            "protagonist_request": "guarded adult heroine",
            "mode": "debug_stub",
        },
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    first_input = "(посмотреть на дверь)"
    first = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": first_input, "mode": "gpt_actions"},
    )
    assert first.status_code == 200, first.text

    retry = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": first_input, "mode": "gpt_actions"},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["turn_id"] == first.json()["turn_id"]
    assert retry.json()["scene_prompt"] == first.json()["scene_prompt"]

    different = client.post(
        f"/api/v1/sessions/{session_id}/turn",
        json={"player_input": "(взять телефон)", "mode": "gpt_actions"},
    )
    assert different.status_code == 409
    assert "still pending" in different.json()["detail"]
