import hashlib
import json
from copy import deepcopy


def _template(session_payload):
    return {
        key: deepcopy(session_payload[key])
        for key in (
            "novel",
            "hidden_lore",
            "plot_state",
            "director_plan",
            "world_state",
            "scene_state",
            "characters",
            "locations",
            "objects",
        )
    }


def test_story_must_be_readback_verified_before_session(client, service, session_payload):
    template = _template(session_payload)
    template["characters"][0]["card"]["player_canon_blob"] = "КАНОН:" + ("я" * 6000)
    source = "Исходная анкета игрока целиком. Маркер: НЕ ТЕРЯТЬ."

    written = client.put(
        "/api/v1/stories/avern/draft",
        json={
            "title": "По ту сторону Аверна",
            "source_text": source,
            "template": template,
        },
    )
    assert written.status_code == 200, written.text
    revision = written.json()["revision"]

    blocked = client.post("/api/v1/stories/avern/sessions")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "STORY_NOT_VERIFIED"

    chunks = []
    first = client.get("/api/v1/stories/avern/readback?chunk_index=0")
    assert first.status_code == 200, first.text
    meta = first.json()
    assert meta["chunk_count"] > 1
    chunks.append(meta["content"])

    premature = client.post(
        "/api/v1/stories/avern/verify",
        json={
            "revision": revision,
            "content_sha256": meta["content_sha256"],
            "missing_items": [],
            "conflicts": [],
            "final_consistency_pass": True,
        },
    )
    assert premature.status_code == 409
    assert premature.json()["error"]["code"] == "STORY_READBACK_INCOMPLETE"

    out_of_order = client.get("/api/v1/stories/avern/readback?chunk_index=2")
    if meta["chunk_count"] > 2:
        assert out_of_order.status_code == 409
        assert out_of_order.json()["error"]["code"] == "STORY_READBACK_CHUNK_OUT_OF_ORDER"

    final_meta = meta
    for index in range(1, meta["chunk_count"]):
        response = client.get(f"/api/v1/stories/avern/readback?chunk_index={index}")
        assert response.status_code == 200, response.text
        final_meta = response.json()
        chunks.append(final_meta["content"])
    assert final_meta["all_chunks_delivered"] is True

    raw = "".join(chunks)
    assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == meta["content_sha256"]
    snapshot = json.loads(raw)
    assert snapshot["source_text"] == source
    assert snapshot["characters"][0]["card"]["player_canon_blob"] == "КАНОН:" + ("я" * 6000)
    registry = snapshot["novel"]["character_registry"]
    assert {item["character_id"] for item in registry} == {
        item["character_id"] for item in template["characters"]
    }

    rejected = client.post(
        "/api/v1/stories/avern/verify",
        json={
            "revision": revision,
            "content_sha256": meta["content_sha256"],
            "missing_items": ["проверочный пропуск"],
            "conflicts": [],
            "final_consistency_pass": True,
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "STORY_VERIFICATION_INCOMPLETE"

    verified = client.post(
        "/api/v1/stories/avern/verify",
        json={
            "revision": revision,
            "content_sha256": meta["content_sha256"],
            "missing_items": [],
            "conflicts": [],
            "final_consistency_pass": True,
        },
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["ready_for_sessions"] is True

    created = client.post("/api/v1/stories/avern/sessions")
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    stored = service.storage.read_json(session_id, "characters/char_emily/card.json")
    assert stored["player_canon_blob"] == "КАНОН:" + ("я" * 6000)
    assert service.storage.read_json(session_id, "story_source.json")["story_id"] == "avern"


def test_rewriting_story_invalidates_previous_verification(client, session_payload):
    template = _template(session_payload)
    first = client.put(
        "/api/v1/stories/rewrite-test/draft",
        json={"title": "История", "source_text": "Версия один", "template": template},
    )
    assert first.status_code == 200
    meta = client.get("/api/v1/stories/rewrite-test/readback?chunk_index=0").json()
    for index in range(1, meta["chunk_count"]):
        assert client.get(f"/api/v1/stories/rewrite-test/readback?chunk_index={index}").status_code == 200
    assert client.post(
        "/api/v1/stories/rewrite-test/verify",
        json={
            "revision": first.json()["revision"],
            "content_sha256": meta["content_sha256"],
            "missing_items": [],
            "conflicts": [],
            "final_consistency_pass": True,
        },
    ).status_code == 200

    second = client.put(
        "/api/v1/stories/rewrite-test/draft",
        json={"title": "История", "source_text": "Версия два", "template": template},
    )
    assert second.status_code == 200
    assert second.json()["revision"] == first.json()["revision"] + 1
    blocked = client.post("/api/v1/stories/rewrite-test/sessions")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "STORY_NOT_VERIFIED"


def test_list_stories_is_short_metadata_only(client, session_payload):
    template = _template(session_payload)
    assert client.put(
        "/api/v1/stories/list-test/draft",
        json={"title": "Список", "source_text": "source", "template": template},
    ).status_code == 200
    listing = client.get("/api/v1/stories")
    assert listing.status_code == 200
    row = next(item for item in listing.json()["stories"] if item["story_id"] == "list-test")
    assert row["title"] == "Список"
    assert "characters" not in row
    assert "source_text" not in row
