import json

from app.config import _repack_active_pending_packets, get_settings


def _write_pending(path, *, status="active", chunks=None, last_delivered=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "packet_type": "turn",
        "packet_id": "turnpacket_test",
        "chunks": chunks or [],
        "last_delivered_chunk_index": last_delivered,
        "all_chunks_delivered": False,
        "content_sha256": "digest",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_repack_preserves_delivered_chunks_and_only_combines_unread_tail(tmp_path):
    path = tmp_path / "sessions" / "sess_test" / "pending_turn.json"
    old_chunks = ["a" * 12_000, "b" * 12_000, "c" * 12_000, "d" * 12_000]
    _write_pending(path, chunks=old_chunks, last_delivered=1)

    _repack_active_pending_packets(tmp_path, 28_000)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["chunks"][:2] == old_chunks[:2]
    assert stored["chunks"][2] == old_chunks[2] + old_chunks[3]
    assert stored["last_delivered_chunk_index"] == 1
    assert stored["all_chunks_delivered"] is False
    assert stored["runtime_repacked"] is True
    assert stored["runtime_repacked_from_chunk_count"] == 4
    assert "".join(stored["chunks"]) == "".join(old_chunks)


def test_repack_does_not_touch_completed_packets(tmp_path):
    path = tmp_path / "sessions" / "sess_test" / "pending_turn.json"
    old = _write_pending(
        path,
        status="committed",
        chunks=["a" * 12_000, "b" * 12_000],
        last_delivered=0,
    )

    _repack_active_pending_packets(tmp_path, 28_000)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == old


def test_get_settings_enforces_production_chunk_floor_and_repacks_existing_packet(
    tmp_path, monkeypatch
):
    path = tmp_path / "sessions" / "sess_test" / "pending_audit.json"
    old_chunks = ["a" * 12_000, "b" * 12_000, "c" * 12_000]
    _write_pending(path, chunks=old_chunks, last_delivered=0)

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PACKET_CHUNK_CHARS", "12000")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.packet_chunk_chars == 28_000
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["chunks"][0] == old_chunks[0]
        assert stored["chunks"][1] == old_chunks[1] + old_chunks[2]
        assert stored["last_delivered_chunk_index"] == 0
        assert "".join(stored["chunks"]) == "".join(old_chunks)
    finally:
        get_settings.cache_clear()
