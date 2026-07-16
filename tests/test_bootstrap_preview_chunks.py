from fastapi.testclient import TestClient

from app.bootstrap_preview_transport import BOOTSTRAP_PREVIEW_CHUNK_SIZE
from app.main import app
from tests.test_smoke import _valid_bootstrap


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={
            "genre": "romance with mysticism",
            "setting_request": "modern city coffee shop",
            "protagonist_request": "adult barista heroine with a detailed starting cast",
            "mode": "gpt_actions",
        },
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def test_long_bootstrap_preview_is_delivered_in_chunks_and_must_be_fully_loaded(monkeypatch):
    client = TestClient(app)
    session_id = _create_session(client)

    paragraphs = [
        f"## Раздел {index}\n" + (f"Подробная строка черновика {index}. " * 180) + "\n"
        for index in range(1, 13)
    ]
    full_preview = "\n".join(paragraphs)
    assert len(full_preview) > BOOTSTRAP_PREVIEW_CHUNK_SIZE * 2

    monkeypatch.setattr("app.session_manager.build_setup_preview", lambda _: full_preview)
    monkeypatch.setattr("app.session_manager.append_directional_preview", lambda preview, _: preview)

    response = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": _valid_bootstrap()},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "bootstrap_review_pending"
    assert body["preview_id"].startswith("preview_")
    assert body["preview_chunk_index"] == 0
    assert body["preview_chunk_count"] >= 3
    assert body["has_more_preview_chunks"] is True
    assert body["next_preview_chunk_index"] == 1
    assert body["message_to_user"] == body["preview_chunk"]
    assert body["preview"] == body["preview_chunk"]
    assert body["user_visible_preview"] == body["preview_chunk"]
    assert len(body["preview_chunk"]) <= BOOTSTRAP_PREVIEW_CHUNK_SIZE
    assert len(response.text) < 70_000

    premature = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-confirm",
        json={"confirmation_text": "подтверждаю"},
    )
    assert premature.status_code == 409
    assert premature.json()["detail"]["code"] == "bootstrap_preview_chunks_not_loaded"

    collected = [body["preview_chunk"]]
    for chunk_index in range(1, body["preview_chunk_count"]):
        chunk_response = client.get(
            f"/api/v1/sessions/{session_id}/bootstrap-preview-chunk",
            params={
                "preview_id": body["preview_id"],
                "chunk_index": chunk_index,
            },
        )
        assert chunk_response.status_code == 200
        chunk = chunk_response.json()
        assert chunk["chunk_index"] == chunk_index
        assert chunk["chunk_count"] == body["preview_chunk_count"]
        assert len(chunk["preview_chunk"]) <= BOOTSTRAP_PREVIEW_CHUNK_SIZE
        collected.append(chunk["preview_chunk"])

    assert "".join(collected) == full_preview

    confirmed = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-confirm",
        json={"confirmation_text": "подтверждаю"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "active"


def test_openapi_exposes_bootstrap_preview_chunk_endpoint():
    client = TestClient(app)
    response = client.get("/openapi-actions.json")
    assert response.status_code == 200
    assert "/api/v1/sessions/{session_id}/bootstrap-preview-chunk" in response.json()["paths"]
