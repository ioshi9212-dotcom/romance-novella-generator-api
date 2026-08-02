import json
from copy import deepcopy

from fastapi.testclient import TestClient

from app.bootstrap_preview_transport import (
    BOOTSTRAP_PREVIEW_CHUNK_SIZE,
    BOOTSTRAP_PREVIEW_INLINE_LIMIT,
    PREVIEW_TRANSPORT_FILE,
    split_bootstrap_preview,
)
from app.main import app
from app.session_manager import SessionManager
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
    assert "preview" not in body
    assert "user_visible_preview" not in body
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


def test_eight_character_preview_stays_within_action_response_budget_and_is_recoverable():
    client = TestClient(app)
    session_id = _create_pending_session(client)
    bootstrap = _valid_bootstrap()
    template = bootstrap["characters"]["coworker_01"]
    specs = (
        ("ryan_01", "Ryan Harper", "Райан", "older brother", "защитная резкость"),
        ("chloe_01", "Chloe Bennett", "Хлоя", "best friend", "навязчивая честность"),
        ("ethan_01", "Ethan Cole", "Итан", "coworker", "спокойное соперничество"),
        ("grace_01", "Grace Holloway", "Грейс", "coffee shop owner", "деловой контроль"),
        ("kai_01", "Kai Mercer", "Кай", "regular guest", "насмешливая дистанция"),
        ("nicole_01", "Nicole Hayes", "Николь", "neighbor", "тревожная настойчивость"),
    )
    for character_id, name, display_name, role, marker in specs:
        card = deepcopy(template)
        card.update(
            {
                "id": character_id,
                "name": name,
                "display_name": display_name,
                "role": role,
                "cast_status": "known_support",
                "goal": f"решить собственную задачу через {marker}, не становясь приложением к героине",
                "past_short": f"У {display_name} есть отдельная история и незакрытое последствие: {marker}.",
                "connections": [{"character_id": "pc_01", "relation": role}],
            }
        )
        card["behavior"] = {
            **card.get("behavior", {}),
            "care_style": f"проявляет заботу через {marker}",
            "conflict_style": f"спорит через {marker}",
            "stress_response": f"под стрессом усиливает {marker}",
        }
        card["speech_profile"] = {
            **card.get("speech_profile", {}),
            "baseline": f"узнаваемая речь: {marker}",
        }
        bootstrap["characters"][character_id] = card

    response = client.post(
        f"/api/v1/sessions/{session_id}/bootstrap-preview",
        json={"bootstrap_json": bootstrap},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["has_more_preview_chunks"] is True
    assert body["preview_chars"] > BOOTSTRAP_PREVIEW_INLINE_LIMIT
    assert len(json.dumps(body, ensure_ascii=False)) < 12_000
    assert len(body["message_to_user"]) <= BOOTSTRAP_PREVIEW_CHUNK_SIZE
    assert "preview" not in body
    assert "user_visible_preview" not in body

    chunks = [body["message_to_user"]]
    for chunk_index in range(1, body["preview_chunk_count"]):
        chunk_response = client.get(
            f"/api/v1/sessions/{session_id}/bootstrap-preview-chunk",
            params={"chunk_index": chunk_index, "preview_id": body["preview_id"]},
        )
        assert chunk_response.status_code == 200, chunk_response.text
        chunks.append(chunk_response.json()["preview_chunk"])

    complete_preview = "".join(chunks)
    assert len(complete_preview) == body["preview_chars"]
    for _, _, display_name, _, _ in specs:
        assert display_name in complete_preview

    # Simulate the real failure: createBootstrapPreview was saved, but its whole
    # Action response was lost. Debug must provide enough compact metadata to
    # recover from chunk 0 without rebuilding the bootstrap.
    SessionManager().storage.write_json(
        session_id,
        PREVIEW_TRANSPORT_FILE,
        {
            "version": "novella.bootstrap_preview_transport.v1",
            "preview_id": body["preview_id"],
            "preview_chars": body["preview_chars"],
            "chunk_size": 20_000,
            "chunk_count": 1,
        },
    )
    debug = client.get(f"/api/v1/sessions/{session_id}/debug-dump")
    assert debug.status_code == 200, debug.text
    recovery = debug.json()["diagnostics"]["bootstrap"]["preview_transport"]
    assert recovery["preview_id"] == body["preview_id"]
    assert recovery["chunk_count"] == body["preview_chunk_count"]
    assert recovery["recovery_start_chunk_index"] == 0
    recovered_chunks = []
    for chunk_index in range(recovery["chunk_count"]):
        chunk_response = client.get(
            f"/api/v1/sessions/{session_id}/bootstrap-preview-chunk",
            params={"chunk_index": chunk_index, "preview_id": recovery["preview_id"]},
        )
        assert chunk_response.status_code == 200, chunk_response.text
        recovered_chunks.append(chunk_response.json()["preview_chunk"])
    assert "".join(recovered_chunks) == complete_preview

    openapi = client.get("/openapi-actions.json").json()
    chunk_action = openapi["paths"]["/api/v1/sessions/{session_id}/bootstrap-preview-chunk"]["get"]
    assert chunk_action["operationId"] == "getBootstrapPreviewChunk"
    chunk_index_parameter = next(item for item in chunk_action["parameters"] if item["name"] == "chunk_index")
    assert chunk_index_parameter["schema"]["minimum"] == 0


def test_preview_chunk_rejects_stale_id_and_out_of_range_index():
    client = TestClient(app)
    session_id = _create_pending_session(client)
    bootstrap = _valid_bootstrap()
    # Keep this transport test larger than the inline limit even when the
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
    assert "preview" not in body
    assert "user_visible_preview" not in body

    openapi = client.get("/openapi-actions.json").json()
    chunk_path = openapi["paths"]["/api/v1/sessions/{session_id}/bootstrap-preview-chunk"]["get"]
    assert chunk_path["operationId"] == "getBootstrapPreviewChunk"
    assert chunk_path["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BootstrapPreviewChunkResponse"
    }

    preview_schema = openapi["components"]["schemas"]["BootstrapPreviewResponse"]
    assert "preview" not in preview_schema["properties"]
    assert "user_visible_preview" not in preview_schema["properties"]
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
