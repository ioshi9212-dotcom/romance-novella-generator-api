"""Protect exact author wording at save time, not just a GPT style guideline."""
import json

from fastapi.testclient import TestClient
from app.main import app


def _session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    client = TestClient(app)
    source = "Дантэ охуенно ревнивый, но никогда в этом не признаётся.\nЕго речь резкая.  Без украшений."
    r = client.post("/sessions", json={"initial_text": source, "request_id": "verbatim-card-case"})
    assert r.status_code == 200, r.text
    base = "/sessions/" + r.json()["session_id"]
    for command in ("подтверждаю", "вопросов_больше_нет", "подтверждаю"):
        response = client.post(base + "/advance", json={"command": command})
        assert response.status_code == 200, response.text
    return client, base, source


def test_author_quotes_exact_in_character_json_and_updates_locked(tmp_path, monkeypatch):
    client, base, original = _session(tmp_path, monkeypatch)
    phrase = original.split("\n")[0]
    card = {"id": "dante", "характер": phrase, "сгенерированные_дополнения": {"привычка": "Сжимает кружку."}}
    path = "карточки/dante.json"
    good = client.put(base + "/data", json={
        "path": path, "document": card, "source_quotes": {"/характер": phrase},
    })
    assert good.status_code == 200, good.text
    assert good.json()["verbatim_locked"] == 1
    saved = client.get(base + "/data", params={"path": path})
    assert saved.status_code == 200
    assert saved.json()["document"]["характер"] == phrase

    softened = {"id": "dante", "характер": "Дантэ склонен к ревности, но скрывает её."}
    rejected = client.put(base + "/data", json={"path": path, "document": softened})
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "CANON_LOCK_CHANGED"
    assert client.get(base + "/data", params={"path": path}).json()["document"] == card


def test_raw_quote_proof_rejects_paraphrase_and_invented_quote(tmp_path, monkeypatch):
    client, base, original = _session(tmp_path, monkeypatch)
    phrase = original.split("\n")[0]
    altered = phrase.replace("охуенно", "очень")
    for body, code in [
        ({"path": "анкета.json", "document": {"суть": altered}, "source_quotes": {"/суть": phrase}}, "CANON_QUOTE_NOT_VERBATIM"),
        ({"path": "анкета.json", "document": {"суть": altered}, "source_quotes": {"/суть": altered}}, "CANON_QUOTE_MISSING_FROM_RAW"),
    ]:
        response = client.put(base + "/data", json=body)
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == code
    assert client.get(base + "/data", params={"path": "анкета.json"}).status_code == 404


def test_non_author_generated_field_is_separate_and_editable(tmp_path, monkeypatch):
    client, base, original = _session(tmp_path, monkeypatch)
    phrase = original.split("\n")[0]
    path = "карточки/dante.json"
    doc = {"id": "dante", "характер": phrase, "сгенерированные_дополнения": {"привычка": "Курит."}}
    assert client.put(base + "/data", json={"path": path, "document": doc, "source_quotes": {"/характер": phrase}}).status_code == 200
    doc["сгенерированные_дополнения"]["привычка"] = "Трёт серьгу."
    assert client.put(base + "/data", json={"path": path, "document": doc}).status_code == 200
