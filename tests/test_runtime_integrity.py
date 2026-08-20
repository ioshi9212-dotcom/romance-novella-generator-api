from copy import deepcopy

from app.runtime_integrity import audit_runtime
from tests.conftest import create_current_session


def _complete_current_payload(session_payload):
    payload = deepcopy(session_payload)
    payload["director_plan"]["active_threads"] = [
        {
            "thread_id": "thread_main",
            "current_question": "Что нарушило обычное утро?",
            "current_pressure": "Начальная загадка требует реакции",
            "status": "active",
        }
    ]
    payload["director_plan"]["character_agendas"] = [
        {
            "character_id": "char_chloe",
            "current_goal": "Поговорить с Эмили",
            "next_plausible_action": "Задать прямой вопрос",
            "conditions": [],
        }
    ]
    return payload


def test_runtime_audit_accepts_verified_setup_source(
    client, service, session_payload
):
    created = create_current_session(
        client, _complete_current_payload(session_payload)
    )

    report = audit_runtime(service)

    row = next(
        item for item in report["sessions"] if item["session_id"] == created["session_id"]
    )
    assert row["errors"] == []


def test_runtime_audit_detects_changed_exact_setup_source(
    client, service, session_payload
):
    created = create_current_session(
        client, _complete_current_payload(session_payload)
    )
    session_id = created["session_id"]
    source = service.storage.read_json(session_id, "state/setup_source.json")
    source["messages"][0] = "Подменённая формулировка"
    service.storage.write_json_batch(
        session_id, {"state/setup_source.json": source}
    )

    report = audit_runtime(service)

    row = next(item for item in report["sessions"] if item["session_id"] == session_id)
    assert "setup_source digest disagrees with manifest" in row["errors"]
