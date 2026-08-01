from __future__ import annotations

import app.main as main_module

from tests.conftest import create_session


def test_auth_is_required(client):
    response = client.post("/v1/sessions", json={"title": "Закрытая"})
    assert response.status_code == 401


def test_legacy_x_api_key_authentication(client):
    response = client.post(
        "/v1/sessions",
        headers={"X-API-Key": "test-action-token"},
        json={"title": "Совместимость"},
    )
    assert response.status_code == 200, response.text


def test_start_questionnaire_supports_legacy_and_current_paths(client, auth_headers):
    legacy = client.get("/api/v1/start-questionnaire", headers=auth_headers)
    current = client.get("/v1/start-questionnaire", headers=auth_headers)

    assert legacy.status_code == 200, legacy.text
    assert current.status_code == 200, current.text
    assert legacy.json() == current.json()
    assert legacy.json()["version"] == "2.0"
    assert "Стартовая анкета" in legacy.json()["questionnaire"]
    assert "Рандом" in legacy.json()["questionnaire"]


def test_create_list_and_resume(client, auth_headers):
    session_id = create_session(client, auth_headers, "Моя история")
    listed = client.get("/v1/sessions", headers=auth_headers)
    assert listed.status_code == 200
    assert any(item["session_id"] == session_id for item in listed.json())
    resumed = client.get(f"/v1/sessions/{session_id}", headers=auth_headers)
    assert resumed.status_code == 200
    assert resumed.json()["title"] == "Моя история"
    assert resumed.json()["status"] == "questionnaire"


def test_unsafe_session_path_is_rejected(client, auth_headers):
    response = client.get("/v1/sessions/..", headers=auth_headers)
    assert response.status_code in {400, 404}


def test_keyless_mode_uses_private_resume_code_and_blocks_listing(client, monkeypatch):
    monkeypatch.setattr(main_module, "ACTION_TOKEN", "")
    created = client.post("/v1/sessions", json={"title": "Без ключа"})
    assert created.status_code == 200, created.text
    payload = created.json()
    assert len(payload["resume_code"]) == 12

    listed = client.get("/v1/sessions")
    assert listed.status_code == 403

    resumed = client.get(f"/v1/sessions/resume/{payload['resume_code']}")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["session_id"] == payload["session_id"]
