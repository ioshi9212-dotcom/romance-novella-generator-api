from __future__ import annotations

import json

from app.config import MAX_CONTEXT_CHUNK_CHARS, MAX_CONTEXT_CHUNKS, SESSIONS_DIR
from tests.conftest import activate_session


def _prepare(client, headers, session_id, mode="play", user_input="Доброе утро."):
    response = client.post(
        f"/v1/sessions/{session_id}/turns",
        headers=headers,
        json={"mode": mode, "user_input": user_input},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _play_commit(label="I", turn_number=1, audit_updates=None):
    body = (
        "Утро в кафе держалось на тихом звоне чашек, ровном шуме кофемашины "
        "и неторопливом движении людей у стойки. Героиня продолжала привычную "
        "работу, а посетитель выбирал слова осторожнее, чем требовал обычный заказ. "
    ) * 8
    return {
        "scene_text": (
            f"🎭 Новелла {label} · начало осени\n"
            f"📅 2 сентября 2026 · 🕒 08:00 · 📍 кафе {label}\n"
            "🌦️ Погода: прохладное утро\n"
            "⚙️ Состояние сцены: посетитель начинает разговор\n\n"
            f"✦ Героиня {label} · спокойна\n"
            "🧥 Одежда: рабочая одежда\n"
            "◈ Инвентарь: без изменений\n\n"
            f"{body.strip()}\n\n"
            "Что я могу сделать\n"
            "- Продолжить готовить заказ.\n"
            "- Посмотреть на посетителя внимательнее.\n"
            "- Отойти к кофемашине.\n\n"
            "Что я могу сказать\n"
            "- Уточнить его заказ.\n"
            "- Ответить на приветствие.\n"
            "- Спросить, ждёт ли он кого-то.\n\n"
            "Что я могу подумать\n"
            "- Он явно пришёл не только за кофе.\n"
            "- Утро начинается слишком любопытно.\n"
            "- Возможно, я его уже видела.\n\n"
            "Состояние: спокойна\n"
            f"Отношения: Посетитель {label} — интерес 2/+2\n"
            f"Ход: {turn_number}"
        ),
        "scene_summary": "Посетитель заговорил с героиней у стойки.",
        "current_patch": {"last_pose": "у стойки"},
        "time_advance_minutes": 5,
        "character_patches": [],
        "new_characters": [],
        "knowledge_events": [
            {
                "character_id": "npc",
                "fact": "Героиня работает утром",
                "status": "fact",
                "source": "личное наблюдение в кафе",
            }
        ],
        "relationship_events": [
            {
                "from_character_id": "npc",
                "to_character_id": "pov",
                "metric": "interest",
                "delta": 2,
                "reason": "Ему понравилась её спокойная реакция",
            }
        ],
        "plotline_patches": [
            {"plotline_id": "main", "changes": {"current_stage": "first_contact"}}
        ],
        "chronology_event": {
            "start": "2026-09-02T08:00:00+10:00",
            "end": "2026-09-02T08:05:00+10:00",
            "location_id": "cafe",
            "events": ["Посетитель заговорил с героиней"],
        },
        "audit_updates": audit_updates or {},
    }


def _all_sections(client, headers, session_id, prepared):
    responses = [prepared]
    for chunk_index in range(1, prepared["total_chunks"]):
        response = client.get(
            f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/chunks/{chunk_index}",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        responses.append(response.json())
    return {
        section["name"]: section["data"]
        for response in responses
        for section in response["chunk"]["sections"]
    }


def test_prepare_is_frozen_and_repeatable(client, auth_headers):
    session_id = activate_session(client, auth_headers, "P")
    first = _prepare(client, auth_headers, session_id)
    second = _prepare(client, auth_headers, session_id)
    assert first["turn_id"] == second["turn_id"]
    assert first["input_hash"] == second["input_hash"]
    assert len(json.dumps(first, ensure_ascii=False)) < 30000

    if first["has_more"]:
        chunk = client.get(
            f"/v1/sessions/{session_id}/turns/{first['turn_id']}/chunks/{first['next_chunk_index']}",
            headers=auth_headers,
        )
        assert chunk.status_code == 200
        assert chunk.json()["turn_id"] == first["turn_id"]


def test_commit_is_idempotent_and_persists_scene(client, auth_headers):
    session_id = activate_session(client, auth_headers, "I")
    prepared = _prepare(client, auth_headers, session_id)
    url = f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit"
    first = client.post(url, headers=auth_headers, json=_play_commit())
    assert first.status_code == 200, first.text
    second = client.post(url, headers=auth_headers, json=_play_commit())
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    root = SESSIONS_DIR / session_id
    session = json.loads((root / "session.json").read_text())
    assert session["turn_number"] == 1
    assert session["state_version"] == 2
    assert (root / "scenes" / "000001.md").is_file()
    relationships = json.loads((root / "state" / "relationships.json").read_text())
    metric = relationships["pairs"]["npc__pov"]["directions"]["npc->pov"]["metrics"]["interest"]
    assert metric == 2
    transaction = root / "transactions" / "pending" / prepared["turn_id"]
    plan = json.loads((transaction / "commit_plan.json").read_text())
    assert plan["status"] == "committed"
    assert "writes" not in plan
    assert plan["payload_size_chars"] > 0
    assert not (transaction / "packet.json").exists()
    status = client.get(f"/v1/sessions/{session_id}", headers=auth_headers).json()
    assert status["pending_turn_id"] is None


def test_technical_commit_does_not_advance_turn(client, auth_headers):
    session_id = activate_session(client, auth_headers, "T")
    prepared = _prepare(
        client,
        auth_headers,
        session_id,
        mode="technical",
        user_input="Исправь цвет волос.",
    )
    response = client.post(
        f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit",
        headers=auth_headers,
        json={
            "scene_text": "",
            "scene_summary": "",
            "current_patch": {},
            "character_patches": [
                {"character_id": "npc", "changes": {"appearance": {"hair": "рыжие"}}}
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["turn_number"] == 0
    assert response.json()["new_state_version"] == 2
    card = json.loads(
        (SESSIONS_DIR / session_id / "state" / "characters" / "npc.json").read_text()
    )
    assert card["appearance"]["hair"] == "рыжие"


def test_stale_commit_is_rejected(client, auth_headers):
    session_id = activate_session(client, auth_headers, "S")
    prepared = _prepare(client, auth_headers, session_id)
    root = SESSIONS_DIR / session_id
    session_path = root / "session.json"
    session = json.loads(session_path.read_text())
    session["state_version"] += 1
    session_path.write_text(json.dumps(session), encoding="utf-8")
    response = client.post(
        f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit",
        headers=auth_headers,
        json=_play_commit(),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "state_version_conflict"


def test_new_character_can_be_patched_and_learn_in_same_commit(client, auth_headers):
    session_id = activate_session(client, auth_headers, "N")
    prepared = _prepare(
        client,
        auth_headers,
        session_id,
        mode="technical",
        user_input="Добавь нового персонажа.",
    )
    response = client.post(
        f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit",
        headers=auth_headers,
        json={
            "new_characters": [
                {
                    "character_id": "barista",
                    "card": {"name": "Бариста", "appearance": {"hair": "чёрные"}},
                    "starting_knowledge": [
                        {
                            "entry_id": "bootstrap:1",
                            "fact": "Кафе открывается в восемь",
                            "status": "fact",
                            "source": "рабочий график",
                        }
                    ],
                }
            ],
            "character_patches": [
                {
                    "character_id": "barista",
                    "changes": {"personality": {"core": "внимательный"}},
                }
            ],
            "knowledge_events": [
                {
                    "character_id": "barista",
                    "fact": "Героиня ждёт важного посетителя",
                    "status": "heard_fragment",
                    "source": "обрывок разговора у стойки",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text

    root = SESSIONS_DIR / session_id
    card = json.loads((root / "state" / "characters" / "barista.json").read_text())
    knowledge = json.loads((root / "state" / "knowledge" / "barista.json").read_text())
    assert card["name"] == "Бариста"
    assert card["appearance"]["hair"] == "чёрные"
    assert card["personality"]["core"] == "внимательный"
    assert [entry["fact"] for entry in knowledge["entries"]] == [
        "Кафе открывается в восемь",
        "Героиня ждёт важного посетителя",
    ]


def test_large_context_is_split_into_bounded_frozen_chunks(client, auth_headers):
    session_id = activate_session(client, auth_headers, "L")
    root = SESSIONS_DIR / session_id
    lore_path = root / "state" / "lore.json"
    lore = json.loads(lore_path.read_text())
    lore["summary"] = "Длинный фрагмент мира. " * 1800
    lore_path.write_text(json.dumps(lore, ensure_ascii=False), encoding="utf-8")

    prepared = _prepare(client, auth_headers, session_id, user_input="Осмотрись вокруг.")
    assert 1 < prepared["total_chunks"] <= MAX_CONTEXT_CHUNKS

    responses = [prepared]
    for chunk_index in range(1, prepared["total_chunks"]):
        response = client.get(
            f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/chunks/{chunk_index}",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        responses.append(response.json())

    for response in responses:
        sections = response["chunk"]["sections"]
        assert len(json.dumps(sections, ensure_ascii=False, separators=(",", ":"))) <= (
            MAX_CONTEXT_CHUNK_CHARS
        )
        assert len(json.dumps(response, ensure_ascii=False)) < 30000


def test_prepare_contains_chronology_full_hidden_canon_cards_and_knowledge(
    client,
    auth_headers,
):
    session_id = activate_session(client, auth_headers, "FULL")
    root = SESSIONS_DIR / session_id
    hidden_path = root / "state" / "hidden_canon.json"
    hidden = json.loads(hidden_path.read_text())
    hidden["false_versions"] = [{"claim": "Гость пришёл случайно"}]
    hidden["causal_chain"] = [{"cause": "старое обещание", "effect": "визит"}]
    hidden["constraints"] = ["Гость не раскрывает причину сразу"]
    hidden_path.write_text(json.dumps(hidden, ensure_ascii=False), encoding="utf-8")
    chronology_event = {
        "turn_id": "earlier",
        "scene_number": 0,
        "events": ["Героиня открыла кафе"],
    }
    (root / "state" / "chronology.jsonl").write_text(
        json.dumps(chronology_event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    prepared = _prepare(client, auth_headers, session_id)
    assert prepared["context_complete"] is True
    sections = _all_sections(client, auth_headers, session_id, prepared)
    assert sections["chronology"] == [chronology_event]
    assert sections["hidden_canon"]["false_versions"] == hidden["false_versions"]
    assert sections["hidden_canon"]["causal_chain"] == hidden["causal_chain"]
    assert sections["hidden_canon"]["constraints"] == hidden["constraints"]
    assert sections["character.pov"]["name"] == "Героиня FULL"
    assert sections["character.npc"]["name"] == "Посетитель FULL"
    assert sections["knowledge.pov"]["character_id"] == "pov"
    assert sections["knowledge.npc"]["character_id"] == "npc"


def test_prepare_rejects_overflow_instead_of_omitting_context(client, auth_headers):
    session_id = activate_session(client, auth_headers, "OVERFLOW")
    root = SESSIONS_DIR / session_id
    lore_path = root / "state" / "lore.json"
    lore = json.loads(lore_path.read_text())
    lore["summary"] = "л" * (MAX_CONTEXT_CHUNK_CHARS * MAX_CONTEXT_CHUNKS)
    lore_path.write_text(json.dumps(lore, ensure_ascii=False), encoding="utf-8")

    response = client.post(
        f"/v1/sessions/{session_id}/turns",
        headers=auth_headers,
        json={"mode": "play", "user_input": "Продолжить."},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "scene_context_too_large"
    status = client.get(f"/v1/sessions/{session_id}", headers=auth_headers).json()
    assert status["pending_turn_id"] is None


def test_prepare_rejects_missing_required_character_state(client, auth_headers):
    session_id = activate_session(client, auth_headers, "MISSING")
    root = SESSIONS_DIR / session_id
    (root / "state" / "characters" / "npc.json").unlink()

    response = client.post(
        f"/v1/sessions/{session_id}/turns",
        headers=auth_headers,
        json={"mode": "play", "user_input": "Посмотреть на посетителя."},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "scene_context_incomplete"


def test_character_rename_refreshes_index_aliases_and_lookup(client, auth_headers):
    session_id = activate_session(client, auth_headers, "RENAME")
    prepared = _prepare(
        client,
        auth_headers,
        session_id,
        mode="technical",
        user_input="Переименуй посетителя в Николь.",
    )
    committed = client.post(
        f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit",
        headers=auth_headers,
        json={
            "character_patches": [
                {"character_id": "npc", "changes": {"name": "Николь"}}
            ]
        },
    )
    assert committed.status_code == 200, committed.text

    root = SESSIONS_DIR / session_id
    index = json.loads((root / "state" / "characters" / "index.json").read_text())
    assert index["characters"]["npc"]["name"] == "Николь"
    assert "Посетитель RENAME" in index["characters"]["npc"]["aliases"]
    current_path = root / "state" / "current.json"
    current = json.loads(current_path.read_text())
    current["present_character_ids"] = ["pov"]
    current_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")

    next_turn = _prepare(
        client,
        auth_headers,
        session_id,
        user_input="Николь подошла к стойке.",
    )
    assert "npc" in next_turn["included_sections"] or any(
        name.startswith("character.npc") for name in next_turn["included_sections"]
    )


def test_technical_commit_cannot_change_story_time(client, auth_headers):
    session_id = activate_session(client, auth_headers, "TIME")
    prepared = _prepare(
        client,
        auth_headers,
        session_id,
        mode="technical",
        user_input="Исправь техническую деталь.",
    )
    url = f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit"
    advanced = client.post(url, headers=auth_headers, json={"time_advance_minutes": 60})
    assert advanced.status_code == 422
    assert "cannot advance story time" in advanced.text
    patched = client.post(
        url,
        headers=auth_headers,
        json={"current_patch": {"datetime": "2026-09-02T09:00:00+10:00"}},
    )
    assert patched.status_code == 422
    assert "cannot patch current.datetime" in patched.text


def test_invalid_scene_format_is_rejected_before_persistence(client, auth_headers):
    session_id = activate_session(client, auth_headers, "FORMAT")
    prepared = _prepare(client, auth_headers, session_id)
    payload = _play_commit(label="FORMAT")
    payload["scene_text"] = "Короткая сцена без шапки."
    response = client.post(
        f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit",
        headers=auth_headers,
        json=payload,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "scene_format_invalid"
    assert not (SESSIONS_DIR / session_id / "scenes" / "000001.md").exists()


def test_tenth_turn_requires_and_persists_real_continuity_audit(client, auth_headers):
    session_id = activate_session(client, auth_headers, "AUDIT")
    root = SESSIONS_DIR / session_id
    add_character = _prepare(
        client,
        auth_headers,
        session_id,
        mode="technical",
        user_input="Добавь сотрудника вне текущей сцены.",
    )
    added = client.post(
        f"/v1/sessions/{session_id}/turns/{add_character['turn_id']}/commit",
        headers=auth_headers,
        json={
            "new_characters": [
                {
                    "character_id": "offscreen",
                    "card": {"name": "Сотрудник", "aliases": []},
                    "starting_knowledge": [],
                }
            ]
        },
    )
    assert added.status_code == 200, added.text
    session_path = root / "session.json"
    session = json.loads(session_path.read_text())
    session["turn_number"] = 9
    session_path.write_text(json.dumps(session), encoding="utf-8")

    prepared = _prepare(client, auth_headers, session_id)
    assert prepared["audit_due"] is True
    assert any(
        name.startswith("character.offscreen")
        for name in prepared["included_sections"]
    )
    url = f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit"
    missing = client.post(
        url,
        headers=auth_headers,
        json=_play_commit(label="AUDIT", turn_number=10),
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "continuity_audit_required"

    audit_updates = {
        "continuity_checked": True,
        "chronology_checked": True,
        "checked_character_ids": ["pov", "npc", "offscreen"],
        "issues": [],
        "repairs": [],
    }
    committed = client.post(
        url,
        headers=auth_headers,
        json=_play_commit(
            label="AUDIT",
            turn_number=10,
            audit_updates=audit_updates,
        ),
    )
    assert committed.status_code == 200, committed.text
    plot = json.loads((root / "state" / "plot.json").read_text())
    assert plot["last_audit"]["updates"] == audit_updates


def test_thirty_turns_do_not_retain_heavy_transaction_copies(client, auth_headers):
    session_id = activate_session(client, auth_headers, "VOLUME")
    root = SESSIONS_DIR / session_id
    for turn_number in range(1, 31):
        prepared = _prepare(
            client,
            auth_headers,
            session_id,
            user_input=f"Продолжить сцену, ход {turn_number}.",
        )
        audit_updates = None
        if turn_number % 10 == 0:
            assert prepared["audit_due"] is True
            audit_updates = {
                "continuity_checked": True,
                "chronology_checked": True,
                "checked_character_ids": ["pov", "npc"],
                "issues": [],
                "repairs": [],
            }
        response = client.post(
            f"/v1/sessions/{session_id}/turns/{prepared['turn_id']}/commit",
            headers=auth_headers,
            json=_play_commit(
                label="VOLUME",
                turn_number=turn_number,
                audit_updates=audit_updates,
            ),
        )
        assert response.status_code == 200, response.text

    transaction_root = root / "transactions"
    assert not list(transaction_root.rglob("packet.json"))
    plans = list(transaction_root.rglob("commit_plan.json"))
    assert plans
    assert all("writes" not in json.loads(path.read_text()) for path in plans)
    transaction_bytes = sum(
        path.stat().st_size
        for path in transaction_root.rglob("*")
        if path.is_file()
    )
    total_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    assert transaction_bytes / total_bytes < 0.5
