import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-only-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return TestClient(app)


def req(api, method, path, **kwargs):
    return api.request(method, path, headers={"X-API-Key": "test-only-key"}, **kwargs)


def init(api):
    r = req(api, "POST", "/sessions", json={"request_id": "test-unique", "initial_text": "Первая строка\n Вторая строка "})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def test_health_and_auth(api):
    assert api.get("/health").json() == {"ok": True}
    assert api.post("/sessions", json={}).status_code == 401
    assert req(api, "GET", "/sessions/00000000-0000-0000-0000-000000000000").status_code == 404


def test_raw_preserved_retries_and_two_confirmations(api):
    sid = init(api)
    assert init(api) == sid
    path = f"/sessions/{sid}"
    part = {"event_id": "qa1", "question": "Что известно?", "text": "Ответ\n  с двумя пробелами\n", "file_name": "notes.txt"}
    assert req(api, "POST", path + "/advance", json={"command": "подтверждаю"}).status_code == 200
    assert req(api, "POST", path + "/raw", json=part).status_code == 200
    assert req(api, "POST", path + "/raw", json=part).json()["источников"] == 2
    assert req(api, "POST", path + "/raw", json={**part, "text": "other"}).status_code == 409
    raw = req(api, "GET", path + "/raw").json()["raw"]
    assert "Первая строка\n Вторая строка " in raw
    assert "Ответ\n  с двумя пробелами\n" in raw
    assert raw.count("===== RAW qa1 ") == 1
    assert req(api, "POST", path + "/advance", json={"command": "подтверждаю"}).status_code == 409
    assert req(api, "POST", path + "/advance", json={"command": "вопросов_больше_нет"}).json()["этап"] == "готово_к_записи"
    assert req(api, "POST", path + "/advance", json={"command": "подтверждаю"}).json()["этап"] == "запись_и_сверка"
    assert req(api, "POST", path + "/raw", json={"event_id": "late", "text": "forgot"}).status_code == 409


def make_docs():
    return {
        "анкета.json": {"название": "Пример"},
        "персонажи.json": {"персонажи": [{"id": "char_pov"}, {"id": "char_aiden"}]},
        "state.json": {"pov_id": "char_pov", "физически": [{"id": "char_pov"}], "удалённо": []},
        "хронология.json": {"дни": {}},
        "скрытый_лор_и_крючки.json": {"скрытый_лор": [], "крючки": []},
        "отношения.json": {"pov_id": "char_pov", "персонажи": {"char_aiden": {"к_POV": {"параметры": {"доверие": 0}}}}},
        "локации.json": {"локации": []},
        "карточки/char_pov.json": {"id": "char_pov"},
        "карточки/char_aiden.json": {"id": "char_aiden"},
        "память/char_pov.json": {"персонаж_id": "char_pov", "знания": {}, "личные_события": {}},
        "память/char_aiden.json": {"персонаж_id": "char_aiden", "знания": {}, "личные_события": {}},
    }


def start_review(api):
    sid = init(api)
    path = f"/sessions/{sid}"
    for command in ("подтверждаю", "вопросов_больше_нет", "подтверждаю"):
        assert req(api, "POST", path + "/advance", json={"command": command}).status_code == 200
    return path


def test_full_review_and_validation(api):
    path = start_review(api)
    for file_name, document in make_docs().items():
        r = req(api, "PUT", path + "/data", json={"path": file_name, "document": document})
        assert r.status_code == 200, (file_name, r.text)
    assert req(api, "GET", path + "/data", params={"path": "память/char_aiden.json"}).json()["document"]["персонаж_id"] == "char_aiden"
    assert req(api, "POST", path + "/verify", json={"audited_against_raw": False}).status_code == 409
    done = req(api, "POST", path + "/verify", json={"audited_against_raw": True, "unresolved_issues": []})
    assert done.status_code == 200, done.text
    assert done.json()["этап"] == "готово_к_игре"
    assert req(api, "PUT", path + "/data", json={"path": "анкета.json", "document": {}}).status_code == 409


def test_missing_memory_and_pov_leaks_rejected(api):
    path = start_review(api)
    docs = make_docs()
    docs.pop("память/char_pov.json")
    docs["отношения.json"]["персонажи"]["char_pov"] = {}
    docs["отношения.json"]["персонажи"]["char_aiden"]["к_POV"]["параметры"]["доверие"] = 101
    for name, doc in docs.items():
        assert req(api, "PUT", path + "/data", json={"path": name, "document": doc}).status_code == 200
    issues = req(api, "POST", path + "/verify", json={"audited_against_raw": True}).json()["detail"]["issues"]
    assert any("память/char_pov" in x for x in issues)
    assert any("отношения от имени POV" in x for x in issues)
    assert any("шкала отношений" in x for x in issues)
    assert req(api, "PUT", path + "/data", json={"path": "../../evil", "document": {}}).status_code == 400

def test_resume_after_raw_metadata_interruption(api, tmp_path):
    sid = init(api)
    folder = tmp_path / "sessions" / sid
    session_file = folder / "сессия.json"
    meta = json.loads(session_file.read_text(encoding="utf-8"))
    meta["_raw_receipts"].pop("initial")
    session_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    sid_retry = init(api)
    assert sid_retry == sid
    assert req(api, "GET", f"/sessions/{sid}/raw").json()["raw"].count("===== RAW initial ") == 1
    assert req(api, "GET", f"/sessions/{sid}").json()["источников"] == 1
