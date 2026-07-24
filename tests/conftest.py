from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest


TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="novel-runtime-tests-"))
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
os.environ["DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["ACTION_TOKEN"] = "test-action-token"
os.environ["ENVIRONMENT"] = "testing"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as value:
        yield value


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-action-token"}


def create_session(client: TestClient, headers: dict[str, str], title: str = "Тест") -> str:
    response = client.post("/v1/sessions", headers=headers, json={"title": title})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def bootstrap_parts(label: str = "A") -> list[dict[str, Any]]:
    return [
        {
            "part_type": "profile",
            "content": {
                "title": f"Новелла {label}",
                "genre": ["романтика"],
                "tone": ["живой"],
                "pov_id": "pov",
                "boundaries": ["без насилия"],
                "start": {"situation": "Утро в кафе"},
            },
        },
        {
            "part_type": "lore",
            "content": {
                "summary": f"Уникальный мир {label}",
                "world_rules": ["Современный мир"],
                "locations": {"cafe": {"name": f"Кафе {label}"}},
                "facts": [],
            },
        },
        {
            "part_type": "hidden_canon",
            "content": {
                "core_truths": [f"Секрет {label}"],
                "facts": [],
                "false_versions": [],
            },
        },
        {
            "part_type": "plot",
            "content": {
                "lines": {
                    "main": {
                        "status": "active",
                        "participant_ids": ["pov", "npc"],
                        "stakes": f"Ставки {label}",
                    }
                },
                "clocks": {},
                "npc_plans": [],
            },
        },
        {
            "part_type": "current",
            "content": {
                "datetime": "2026-09-02T08:00:00+10:00",
                "location_id": "cafe",
                "pov_state": {"mood": "спокойна"},
                "present_character_ids": ["pov", "npc"],
                "nearby_character_ids": [],
                "scheduled_character_ids": [],
                "last_scene_end": "",
            },
        },
        {
            "part_type": "character",
            "part_id": "pov",
            "content": {
                "id": "pov",
                "name": f"Героиня {label}",
                "aliases": ["героиня"],
                "appearance": {"hair": "светлые"},
                "personality": {"core": "наблюдательная"},
                "goals": {"current": "закончить смену"},
                "voice": {"style": "мягкий"},
                "starting_knowledge": [],
                "initial_relationships": [
                    {"to_character_id": "npc", "metric": "trust", "value": 10}
                ],
            },
        },
        {
            "part_type": "character",
            "part_id": "npc",
            "content": {
                "id": "npc",
                "name": f"Посетитель {label}",
                "aliases": ["посетитель"],
                "appearance": {"hair": "тёмные"},
                "personality": {"core": "упрямый"},
                "goals": {"current": "поговорить"},
                "voice": {"style": "сдержанный"},
                "starting_knowledge": [],
                "initial_relationships": [],
            },
        },
        {
            "part_type": "review",
            "content": {
                "title": f"Новелла {label}",
                "premise": f"Безопасное описание {label}",
                "known_characters": [f"Посетитель {label}"],
            },
        },
    ]


def activate_session(
    client: TestClient,
    headers: dict[str, str],
    label: str = "A",
) -> str:
    session_id = create_session(client, headers, f"Новелла {label}")
    questionnaire = client.put(
        f"/v1/sessions/{session_id}/questionnaire",
        headers=headers,
        json={
            "phase": "initial",
            "raw_answers": "Романтика в современном городе",
            "normalized": {"genre": "романтика"},
        },
    )
    assert questionnaire.status_code == 200, questionnaire.text
    for part in bootstrap_parts(label):
        response = client.post(
            f"/v1/sessions/{session_id}/bootstrap/parts",
            headers=headers,
            json=part,
        )
        assert response.status_code == 200, response.text
    validation = client.post(
        f"/v1/sessions/{session_id}/bootstrap/validate",
        headers=headers,
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["ready"] is True
    confirmation = client.post(
        f"/v1/sessions/{session_id}/bootstrap/confirm",
        headers=headers,
    )
    assert confirmation.status_code == 200, confirmation.text
    assert confirmation.json()["status"] == "active"
    return session_id
