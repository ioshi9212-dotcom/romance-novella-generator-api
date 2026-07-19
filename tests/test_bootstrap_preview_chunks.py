import json

from fastapi.testclient import TestClient

from app.bootstrap_preview_transport import BOOTSTRAP_PREVIEW_CHUNK_SIZE, split_bootstrap_preview
from app.main import app
from tests.test_smoke import _valid_bootstrap


def _create_pending_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={
            "genre": "romantic urban mysticism",
            "setting_request": "modern city and coffee shop",
            "protagonist_request": "adult heroine with a detailed everyday life",
            "romance_request": "slow relationships with several inconvenient characters",
            "mode": "gpt_actions",
        },
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def test_preview_split_preserves_exact_text_and_limits_every_chunk():
    text = ("Раздел с подробностями.\n\n" * 1200) + "ФИНАЛ"
    chunks = split_bootstrap_preview(text)

    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert all(0 < len(chunk) <= BOOTSTRAP_PREVIEW_CHUNK_SIZE for chunk in chunks)


def test_large_bootstrap_preview_is_returned_in_safe_ordered_chunks():
    client = TestClient(app)
    session_id = _create_pending_session(client)
    bootstrap = _valid_bootstrap()
    marker = "УНИКАЛЬНЫЙ_ФРАГМЕНТ_PREVIEW"
    bootstrap["characters"]["pc_01"]["past_short"] = marker + " " + (
        "Она помнит конкретный эпизод прошлого, который влияет на её решения сейчас. " * 900
    )

    response = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": bootstrap},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "bootstrap_review_pending"
    assert body["has_more_preview_chunks"] is True
    assert body["preview_chunk_count"] > 1
    assert body["preview_chunk_index"] == 0
    assert body["next_preview_chunk_index"] == 1
    assert body["must_show_to_user"] is False
    assert body["can_confirm"] is False
    assert body["message_to_user"] == body["preview"] == body["user_visible_preview"]
    assert len(body["message_to_user"]) <= BOOTSTRAP_PREVIEW_CHUNK_SIZE
    assert len(json.dumps(body, ensure_ascii=False)) < 30000

    chunks = [body["message_to_user"]]
    last_chunk = None
    for chunk_index in range(1, body["preview_chunk_count"]):
        chunk_response = client.get(
            f"/api/v1/sessions/{session_id}/bootstrap-preview-chunk",
            params={"chunk_index": chunk_index, "preview_id": body["preview_id"]},
        )
        assert chunk_response.status_code == 200
        last_chunk = chunk_response.json()
        assert last_chunk["chunk_index"] == chunk_index
        assert last_chunk["chunk_count"] == body["preview_chunk_count"]
        assert last_chunk["preview_id"] == body["preview_id"]
        assert len(last_chunk["preview_chunk"]) <= BOOTSTRAP_PREVIEW_CHUNK_SIZE
        assert last_chunk["must_show_to_user"] is False
        chunks.append(last_chunk["preview_chunk"])

    complete_preview = "".join(chunks)
    assert len(complete_preview) == body["preview_chars"]
    assert complete_preview.startswith("## Черновик новеллы")
    assert marker in complete_preview
    assert last_chunk is not None
    assert last_chunk["has_more"] is False
    assert last_chunk["ready_to_show_full_preview"] is True
    assert last_chunk["can_confirm"] is True


def test_preview_chunk_rejects_stale_id_and_out_of_range_index():
    client = TestClient(app)
    session_id = _create_pending_session(client)
    bootstrap = _valid_bootstrap()
    # Keep this transport test larger than the 20k inline limit even when the
    # human-facing preview becomes more concise.
    bootstrap["characters"]["pc_01"]["past_short"] = "Большое прошлое. " * 1800

    preview = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": bootstrap},
    ).json()
    assert preview["has_more_preview_chunks"] is True

    stale = client.get(
        f"/api/v1/sessions/{session_id}/bootstrap-preview-chunk",
        params={"chunk_index": 1, "preview_id": "stale-preview-id"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_bootstrap_preview_id"

    outside = client.get(
        f"/api/v1/sessions/{session_id}/bootstrap-preview-chunk",
        params={"chunk_index": preview["preview_chunk_count"], "preview_id": preview["preview_id"]},
    )
    assert outside.status_code == 416
    assert outside.json()["detail"]["code"] == "bootstrap_preview_chunk_out_of_range"


def test_small_preview_keeps_legacy_single_response_behavior():
    client = TestClient(app)
    session_id = _create_pending_session(client)

    response = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": _valid_bootstrap()},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["has_more_preview_chunks"] is False
    assert body["preview_chunk_count"] == 1
    assert body["next_preview_chunk_index"] is None
    assert body["must_show_to_user"] is True
    assert body["can_confirm"] is True
    assert body["message_to_user"] == body["preview"] == body["user_visible_preview"]

    openapi = client.get("/openapi-actions.json").json()
    chunk_path = openapi["paths"]["/api/v1/sessions/{session_id}/bootstrap-preview-chunk"]["get"]
    assert chunk_path["operationId"] == "getBootstrapPreviewChunk"
    assert chunk_path["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BootstrapPreviewChunkResponse"
    }

    preview_schema = openapi["components"]["schemas"]["BootstrapPreviewResponse"]
    for field in (
        "preview_id",
        "preview_chars",
        "preview_chunk_index",
        "preview_chunk_count",
        "has_more_preview_chunks",
        "next_preview_chunk_index",
    ):
        assert field in preview_schema["properties"]
        assert field in preview_schema["required"]
