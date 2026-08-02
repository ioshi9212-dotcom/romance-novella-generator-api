import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

import app.session_manager as session_manager_module
from app.bootstrap_prompt_transport import BOOTSTRAP_PROMPT_CHUNK_SIZE, split_bootstrap_prompt
from app.main import app
from app.session_manager import SessionManager


def test_bootstrap_prompt_split_preserves_exact_text_and_limits_chunks():
    text = ("Правило и точный факт.\n\n" * 12000) + "ФИНАЛ"
    chunks = split_bootstrap_prompt(text)

    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert all(0 < len(chunk) <= BOOTSTRAP_PROMPT_CHUNK_SIZE for chunk in chunks)


def test_create_session_returns_only_chunk_zero_and_reconstructs_221844_bytes(monkeypatch):
    target_bytes = 221_844
    # SessionManager inserts two blank separators even when both rule blocks are empty.
    source_prompt = "A" * (target_bytes - 4)
    monkeypatch.setattr(session_manager_module, "build_bootstrap_prompt", lambda _: source_prompt)
    monkeypatch.setattr(session_manager_module, "BOOTSTRAP_DIRECTION_RULES", "")
    monkeypatch.setattr(session_manager_module, "BOOTSTRAP_PREVIEW_TRANSPORT_RULES", "")

    client = TestClient(app)
    sessions_before = set(SessionManager().list_sessions())
    response = client.post(
        "/api/v1/sessions",
        json={"raw_start_text": "Точная заполненная анкета", "mode": "gpt_actions"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    session_id = body["session_id"]

    assert body["status"] == "bootstrap_pending"
    assert body["bootstrap_prompt_bytes"] == target_bytes
    assert body["bootstrap_prompt_chunk_count"] == 50
    assert body["has_more_bootstrap_prompt_chunks"] is True
    assert len(body["bootstrap_prompt"]) <= BOOTSTRAP_PROMPT_CHUNK_SIZE
    assert len(response.content) < 5000

    prompt_path = SessionManager().storage.session_dir(session_id) / "pending_bootstrap_prompt.md"
    full_prompt = prompt_path.read_text(encoding="utf-8")
    assert len(full_prompt.encode("utf-8")) == target_bytes
    assert hashlib.sha256(full_prompt.encode("utf-8")).hexdigest() == body["bootstrap_prompt_sha256"]

    chunks = [body["bootstrap_prompt"]]
    for chunk_index in range(1, body["bootstrap_prompt_chunk_count"]):
        chunk_response = client.get(
            f"/api/v1/sessions/{session_id}/bootstrap-prompt-chunk",
            params={
                "chunk_index": chunk_index,
                "bootstrap_prompt_sha256": body["bootstrap_prompt_sha256"],
            },
        )
        assert chunk_response.status_code == 200, chunk_response.text
        chunk_body = chunk_response.json()
        assert chunk_body["chunk_index"] == chunk_index
        assert chunk_body["chunk_count"] == 50
        assert len(chunk_body["bootstrap_prompt_chunk"]) <= BOOTSTRAP_PROMPT_CHUNK_SIZE
        chunks.append(chunk_body["bootstrap_prompt_chunk"])

    assert "".join(chunks) == full_prompt
    sessions_after = set(SessionManager().list_sessions())
    assert sessions_after - sessions_before == {session_id}


def test_bootstrap_prompt_chunk_rejects_stale_hash_and_out_of_range(monkeypatch):
    monkeypatch.setattr(session_manager_module, "build_bootstrap_prompt", lambda _: "X" * 10_000)
    monkeypatch.setattr(session_manager_module, "BOOTSTRAP_DIRECTION_RULES", "")
    monkeypatch.setattr(session_manager_module, "BOOTSTRAP_PREVIEW_TRANSPORT_RULES", "")
    client = TestClient(app)
    created = client.post(
        "/api/v1/sessions",
        json={"raw_start_text": "анкета", "mode": "gpt_actions"},
    ).json()

    stale = client.get(
        f"/api/v1/sessions/{created['session_id']}/bootstrap-prompt-chunk",
        params={"chunk_index": 1, "bootstrap_prompt_sha256": "0" * 64},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_bootstrap_prompt_sha256"

    outside = client.get(
        f"/api/v1/sessions/{created['session_id']}/bootstrap-prompt-chunk",
        params={"chunk_index": 999, "bootstrap_prompt_sha256": created["bootstrap_prompt_sha256"]},
    )
    assert outside.status_code == 416
    assert outside.json()["detail"]["code"] == "bootstrap_prompt_chunk_out_of_range"


def test_openapi_exposes_bootstrap_prompt_chunk_contract():
    contract = app.openapi()
    operation = contract["paths"]["/api/v1/sessions/{session_id}/bootstrap-prompt-chunk"]["get"]
    assert operation["operationId"] == "getBootstrapPromptChunk"
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("/BootstrapPromptChunkResponse")

    instructions = Path("gpt/custom_gpt_instructions.md").read_text(encoding="utf-8")
    assert "createSession — ровно один раз" in instructions
    assert "getBootstrapPromptChunk" in instructions
    assert "bootstrap_prompt_sha256" in instructions
