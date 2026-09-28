import os
from pathlib import Path

import pytest

from app.storage import JsonStorage
from tests.conftest import commit_next_turn, create_session


def test_two_sessions_never_share_state(client, service, session_payload) -> None:
    first = create_session(client, session_payload)
    second = create_session(client, session_payload)
    commit_next_turn(client, first, player_input="Изменить только первую сессию")

    first_session = service.storage.read_json(first, "session.json")
    second_session = service.storage.read_json(second, "session.json")
    assert first_session["last_completed_turn"] == 1
    assert second_session["last_completed_turn"] == 0
    assert service.storage.session_dir(first) != service.storage.session_dir(second)

    packet = client.post(
        f"/api/v1/sessions/{second}/turn-packet",
        json={"player_input": "Ход второй сессии"},
    ).json()
    wrong_session_chunk = client.get(
        f"/api/v1/sessions/{first}/turn-packets/{packet['packet_id']}/chunks/0"
    )
    assert wrong_session_chunk.status_code == 404


def test_path_traversal_is_rejected(service) -> None:
    with pytest.raises(ValueError):
        service.storage.session_dir("../other-session")
    with pytest.raises(ValueError):
        service.storage._path("valid-session", "../secret.json")


def test_json_batch_rolls_back_all_targets_on_mid_commit_failure(
    tmp_path: Path, monkeypatch
) -> None:
    storage = JsonStorage(tmp_path / "data")
    session_id = "sess_atomic_test"
    storage.create_session_dir(session_id)
    storage.write_json_batch(
        session_id,
        {"state/a.json": {"value": "old-a"}, "state/b.json": {"value": "old-b"}},
    )

    original_replace = os.replace
    failure_raised = False

    def fail_once_on_b(source, target):
        nonlocal failure_raised
        if not failure_raised and str(target).endswith("state/b.json"):
            failure_raised = True
            raise OSError("simulated disk failure")
        return original_replace(source, target)

    monkeypatch.setattr("app.storage.os.replace", fail_once_on_b)
    with pytest.raises(OSError, match="simulated disk failure"):
        storage.write_json_batch(
            session_id,
            {"state/a.json": {"value": "new-a"}, "state/b.json": {"value": "new-b"}},
        )

    assert storage.read_json(session_id, "state/a.json") == {"value": "old-a"}
    assert storage.read_json(session_id, "state/b.json") == {"value": "old-b"}
