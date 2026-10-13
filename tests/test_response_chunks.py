"""Regression tests for lossless, stable, 16k-character GPT Actions transport."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.response_chunks import CHUNK_CHARS, present, read_chunk
from test_prepare_turn import KEY, ready


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def reconstruct(client, first):
    """Follow ONLY unread indices as a ChatGPT Action client should."""
    assert first["chunked"] is True
    assert first["chunk_index"] == 0
    assert first["chunk_count"] > 1
    assert not first["all_chunks_read"]
    parts = {0: first["content"]}
    count = first["chunk_count"]
    current = first["next_chunk_index"]
    seen = []
    while current is not None:
        r = client.get(f"/chunks/{first['read_id']}/{current}", headers=KEY)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["chunk_index"] == current
        assert doc["read_id"] == first["read_id"]
        assert len(doc["content"]) <= CHUNK_CHARS
        parts[current] = doc["content"]
        seen.append(current)
        current = doc["next_chunk_index"]
        if current is not None:
            assert not doc["all_chunks_read"]
        else:
            assert doc["all_chunks_read"]
    assert seen == list(range(1, count))
    full = "".join(parts[i] for i in range(count))
    assert len(full) == first["total_chars"]
    assert hashlib.sha256(full.encode("utf-8")).hexdigest() == first["sha256"]
    return json.loads(full)


def test_unchanged_small_response_shape(store):
    original = {"session_id": "demo", "scene": "Привет"}
    result = present(original, "test")
    assert result == original
    assert not list((store / ".response_chunks").glob("*.bin")) if (store / ".response_chunks").exists() else True


def test_large_unicode_and_utf8_snapshot_survives_restart(store, monkeypatch):
    original = {"pov": "Юкира", "карточки": [{"имя": "Рэй", "описание": "🌷здравствуй" * 2500}], "сцены": ["ёж" * 9000]}
    envelope = present(original, "unit")
    assert envelope["chunk_count"] >= 3
    assert len(envelope["content"]) <= CHUNK_CHARS
    # Simulate a later request/process: the immutable file is the data source.
    client = TestClient(app)
    monkeypatch.setenv("API_KEY", "test-only-key")
    assert reconstruct(client, envelope) == original
    # Repeating the same chunk is safe; complete read remains complete.
    twice = client.get(f"/chunks/{envelope['read_id']}/1", headers=KEY).json()
    assert twice["all_chunks_read"]
    assert twice["next_chunk_index"] is None


def test_runtime_is_chunked_when_rules_are_large(store, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-only-key")
    client = TestClient(app)
    result = client.get("/runtime", headers=KEY)
    assert result.status_code == 200
    first = result.json()
    assert first.get("chunked")
    reconstructed = reconstruct(client, first)
    assert reconstructed["rules"].startswith("# Rules")
    assert reconstructed["skin_builder"].startswith("# Skin Builder")
    # The unchanged-version read remains tiny, not another chunked read.
    cached = client.get("/runtime", headers=KEY, params={"known_sha256": reconstructed["sha256"]})
    assert cached.status_code == 200 and cached.json()["changed"] is False


def test_raw_immutable_even_if_original_source_changes(store, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-only-key")
    client = TestClient(app)
    sid = client.post("/sessions", headers=KEY, json={"initial_text": "один" * 14000}).json()["session_id"]
    base = f"/sessions/{sid}"
    first = client.get(base + "/raw", headers=KEY).json()
    assert first["chunked"]
    client.post(base + "/raw", headers=KEY, json={"event_id": "new", "text": "два" * 4000})
    old = reconstruct(client, first)["raw"]
    now = reconstruct(client, client.get(base + "/raw", headers=KEY).json())["raw"]
    assert "два" * 4000 not in old
    assert "два" * 4000 in now


def test_prepare_turn_full_character_data_remains_lossless(ready):
    client, url, folder = ready
    path = folder / "память" / "pov.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    marker = "Любимая старая песня" * 3000
    data["знания"]["03.09.2026"].append(marker)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    p = client.post(url + "/prepare-turn", headers=KEY, json={"user_input": "(Смотреть в окно)"})
    assert p.status_code == 200
    first = p.json()
    assert first["chunked"] is True
    packet = reconstruct(client, first)
    assert marker in packet["персонажи_подробно"]["pov"]["память"]["знания"]["03.09.2026"]
    assert packet["ввод_игрока"] == "(Смотреть в окно)"
    assert len(packet["контекст_sha256"]) == 64


@pytest.mark.parametrize("invalid,status", [("invalid",422),("0"*32,404)])
def test_invalid_chunk_id_rejected(store, monkeypatch,invalid,status):
    monkeypatch.setenv("API_KEY", "test-only-key")
    client = TestClient(app)
    r = client.get(f"/chunks/{invalid}/0", headers=KEY)
    assert r.status_code == status


def test_chunk_endpoint_requires_auth_and_detects_corruption(store, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-only-key")
    first = present({"x": "🪷" * 20000}, "unit")
    client = TestClient(app)
    url = f"/chunks/{first['read_id']}/1"
    assert client.get(url).status_code == 401
    binfile = store / ".response_chunks" / (first["read_id"] + ".bin")
    info = json.loads((store / ".response_chunks" / (first["read_id"] + ".json")).read_text(encoding="utf-8"))
    with binfile.open("r+b") as handle:
        handle.seek(info["offsets"][1][0])
        handle.write(b"corrupt")
    assert client.get(url, headers=KEY).status_code == 409


def test_expired_chunk_rejected(store, monkeypatch):
    import time
    monkeypatch.setenv("API_KEY", "test-only-key")
    first = present({"x": "long" * 5000}, "unit")
    path = store / ".response_chunks" / (first["read_id"] + ".json")
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata["created"] = time.time() - 90000
    path.write_text(json.dumps(metadata))
    client = TestClient(app)
    assert client.get(f"/chunks/{first['read_id']}/1", headers=KEY).status_code == 410
