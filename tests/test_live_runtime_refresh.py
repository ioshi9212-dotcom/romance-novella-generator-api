"""Real turn lifecycle with changed Skin Builder during the same GPT chat.

A test-only mutable runtime folder imitates a newly deployed GitHub edit.
No production Amvera files or real sessions are affected.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import app.runtime_docs as runtime_docs
from test_commit_turn import commit, packet
from test_prepare_turn import ready, KEY


@pytest.fixture
def editable_runtime(tmp_path, monkeypatch):
    directory = tmp_path / "deployed_runtime"
    directory.mkdir()
    (directory / "rules.md").write_text("# Rules\\nKeep all game data consistent.\\n", encoding="utf-8")
    (directory / "scene_builder.md").write_text("# Skin Builder\\nFORMAT VERSION A: one paragraph.\\n", encoding="utf-8")
    monkeypatch.setattr(runtime_docs, "runtime_directory", lambda: directory)
    return directory


def unfold(client, response):
    assert response.status_code == 200, response.text
    value = response.json()
    if not value.get("chunked"):
        return value
    fragments = {0: value["content"]}
    next_index = value["next_chunk_index"]
    while next_index is not None:
        continuation = client.get(f"/chunks/{value['read_id']}/{next_index}")
        assert continuation.status_code == 200, continuation.text
        part = continuation.json()
        assert part["chunk_index"] == next_index
        fragments[next_index] = part["content"]
        next_index = part["next_chunk_index"]
    assert len(fragments) == value["chunk_count"]
    original = "".join(fragments[i] for i in range(value["chunk_count"]))
    assert hashlib.sha256(original.encode("utf-8")).hexdigest() == value["sha256"]
    return json.loads(original)


def test_second_prepare_receives_edited_skin_without_calling_runtime(ready, editable_runtime):
    client, _, folder = ready
    before = packet(ready)
    first = before["актуальные_инструкции"]
    assert first["skin_builder"] == (editable_runtime / "scene_builder.md").read_text(encoding="utf-8")
    assert "FORMAT VERSION A" in first["skin_builder"]
    saved_files = {
        p.relative_to(folder): p.read_bytes()
        for p in folder.rglob("*.json")
    }

    # Edit in GitHub, deploy to Amvera, then simulate another game turn.
    (editable_runtime / "scene_builder.md").write_text(
        "# Skin Builder\\nFORMAT VERSION B: single line for dialogue.\\n",
        encoding="utf-8",
    )
    later = packet(ready)  # No getRuntimeInstructions call in between!
    assert "FORMAT VERSION B" in later["актуальные_инструкции"]["skin_builder"]
    assert "FORMAT VERSION A" not in later["актуальные_инструкции"]["skin_builder"]
    assert later["актуальные_инструкции"]["skin_builder_sha256"] != first["skin_builder_sha256"]
    assert later["контекст_sha256"] != before["контекст_sha256"]
    assert later["turn_id"] == before["turn_id"]
    assert {
        p.relative_to(folder): p.read_bytes()
        for p in folder.rglob("*.json")
    } == saved_files


def test_stale_scene_cannot_commit_after_skin_edit_but_new_prepare_can(ready, editable_runtime):
    client, url, root = ready
    old = packet(ready)
    (editable_runtime / "scene_builder.md").write_text(
        "# Skin Builder\\nUPDATED: no old format.\\n", encoding="utf-8"
    )
    rejected, _ = commit(ready, old, scene="Scene written by the older Skin Builder.")
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "STALE_TURN_CONTEXT"
    assert not (root / "ходы.jsonl").exists()

    fresh = packet(ready)
    assert "UPDATED" in fresh["актуальные_инструкции"]["skin_builder"]
    success, payload = commit(ready, fresh, scene="Scene based on the updated Skin Builder.")
    assert success.status_code == 200, success.text
    assert success.json()["status"] == "saved"
    assert len((root / "ходы.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    # Network retry stays idempotent even after another Skin Builder update.
    (editable_runtime / "scene_builder.md").write_text(
        "# Skin Builder\\nTHIRD FORMAT.\\n", encoding="utf-8"
    )
    same_retry = client.post(url + "/commit-turn", json=payload)
    assert same_retry.status_code == 200, same_retry.text
    assert same_retry.json()["status"] == "already_saved"
    assert len((root / "ходы.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_rules_hash_changes_and_runtime_endpoint_matches(ready, editable_runtime):
    client, _, root = ready
    before = packet(ready)
    before_rules = before["актуальные_инструкции"]["rules_sha256"]
    (editable_runtime / "rules.md").write_text(
        "# Rules\\nTechnical protocol just changed in deployed runtime.\\n",
        encoding="utf-8",
    )
    refreshed = packet(ready)
    assert refreshed["актуальные_инструкции"]["rules_sha256"] != before_rules
    assert refreshed["контекст_sha256"] != before["контекст_sha256"]
    runtime = unfold(client, client.get("/runtime"))
    assert runtime["sha256"] == refreshed["актуальные_инструкции"]["runtime_sha256"]
    assert runtime["skin_builder"] == refreshed["актуальные_инструкции"]["skin_builder"]
    unchanged = client.get("/runtime", params={"known_sha256": runtime["sha256"]})
    assert unchanged.status_code == 200
    assert unchanged.json()["changed"] is False


def test_long_skin_builder_is_not_cut_and_chunk_snapshot_stays_consistent(ready, editable_runtime):
    client, url, _ = ready
    text = "# Skin Builder\\n" + ("Правило 12345, строка. " * 2400)
    assert len(text) > 16000
    (editable_runtime / "scene_builder.md").write_text(text, encoding="utf-8")

    first = client.post(url + "/prepare-turn", json={"user_input": "Продолжаю разговор"})
    assert first.status_code == 200, first.text
    assert first.json()["chunked"] is True
    # The saved snapshot must not mutate even if the deployed file changes
    # after chunk 0 and before reading the rest.
    (editable_runtime / "scene_builder.md").write_text(
        "# Skin Builder\\nNEW AFTER FIRST CHUNK.\\n", encoding="utf-8"
    )
    original = unfold(client, first)
    assert original["актуальные_инструкции"]["skin_builder"] == text
    assert original["контекст_sha256"]
    stale, _ = commit(ready, original)
    assert stale.status_code == 409
    latest = packet(ready)
    assert "NEW AFTER FIRST CHUNK" in latest["актуальные_инструкции"]["skin_builder"]


def test_unavailable_runtime_rejects_prepare_instead_of_reusing_old_skin(ready, editable_runtime):
    client, url, folder = ready
    original = packet(ready)
    (editable_runtime / "scene_builder.md").unlink()
    result = client.post(url + "/prepare-turn", json={"user_input": original["ввод_игрока"]})
    assert result.status_code == 503
    assert not (folder / "ходы.jsonl").exists()
