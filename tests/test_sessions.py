from __future__ import annotations

from tests.conftest import create_session


def test_auth_is_required(client):
    response = client.post("/v1/sessions", json={"title": "Закрытая"})
    assert response.status_code == 401


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
