"""Realistic GPT initial-State variations, without inventing POV presence."""
import json
from copy import deepcopy

import pytest

from test_creation import api, make_docs, start_review


def setup_and_verify(api, state_overrides, *, names=None):
    path = start_review(api)
    docs = make_docs()
    docs["персонажи.json"]["персонажи"][0]["имя"] = "Кайра Астер"
    docs["персонажи.json"]["персонажи"][1]["имя"] = "Лиам Торн"
    if names:
        docs["персонажи.json"]["персонажи"].extend(names)
        for person in names:
            docs["отношения.json"]["стартовая_сверка"][person["id"]] = {"статус": "не_знакомы", "аспекты": []}
        for item in names:
            cid = item["id"]
            docs[f"карточки/{cid}.json"] = {"id": cid}
            docs[f"память/{cid}.json"] = {"персонаж_id": cid, "знания": {}, "личные_события": {}}
    docs["state.json"].update(deepcopy(state_overrides))
    for name, document in docs.items():
        saved = api.put(path + "/data", json={"path": name, "document": document})
        assert saved.status_code == 200, (name, saved.text)
    verified = api.post(path + "/verify", json={"audited_against_raw": True})
    after = api.get(path + "/data", params={"path": "state.json"}).json()["document"]
    return verified, after


@pytest.mark.parametrize("raw_state", [
    {"pov_id": "Кайра", "физически": ["Кайра"]},
    {"pov_id": "Кайра Астер", "физически": [{"имя": "Кайра", "одежда": "куртка"}]},
    {"pov_id": {"имя": "Кайра"}, "физически": [{"персонаж_id": "char_pov", "при_себе": ["ключи"]}]},
    {"pov_id": "char_pov", "физически": {"Кайра": {"одежда": "домашняя"}}},
    {"pov_id": "char_pov", "физически": [{"id": "char_pov", "одежда": "куртка"}]},
])
def test_initial_state_accepts_unambiguous_gpt_shapes(api, raw_state):
    response, doc = setup_and_verify(api, raw_state)
    assert response.status_code == 200, response.text
    assert doc["pov_id"] == "char_pov"
    assert isinstance(doc["физически"], list)
    assert len(doc["физически"]) == 1
    assert doc["физически"][0]["id"] == "char_pov"
    assert doc["физически"][0].get("одежда", "") == (
        raw_state["физически"].get("Кайра", {}).get("одежда", "")
        if isinstance(raw_state["физически"], dict)
        else next((v.get("одежда", "") for v in raw_state["физически"] if isinstance(v, dict)), "")
    )


def test_missing_physical_pov_is_not_invented(api):
    state = {"pov_id": "Кайра", "физически": [{"id": "char_aiden"}]}
    response, doc = setup_and_verify(api, state)
    assert response.status_code == 409
    issues = response.json()["detail"]["issues"]
    assert any("POV должен быть физически присутствующим" in x for x in issues)
    assert any("char_pov" in x for x in issues)
    # A failed review never rewrites the user's original State.
    assert doc["pov_id"] == "Кайра"
    assert doc["физически"] == state["физически"]


def test_ambiguous_name_requires_explicit_id(api):
    other = [{"id": "char_second_kaira", "имя": "Кайра Эш"}]
    response, doc = setup_and_verify(
        api, {"pov_id": "Кайра", "физически": ["Кайра"]}, names=other,
    )
    assert response.status_code == 409
    assert any("неоднозначно" in x for x in response.json()["detail"]["issues"])
    assert doc["pov_id"] == "Кайра"


def test_unknown_physical_character_is_not_autocreated(api):
    response, doc = setup_and_verify(
        api, {"pov_id": "char_pov", "физически": [{"имя": "Новый неизвестный"}]}
    )
    assert response.status_code == 409
    assert any("не найден в реестре" in x for x in response.json()["detail"]["issues"])
    assert doc["физически"] == [{"имя": "Новый неизвестный"}]


def test_remote_presence_does_not_substitute_for_physical_pov(api):
    response, doc = setup_and_verify(
        api, {
            "pov_id": "char_pov",
            "физически": [],
            "удалённо": ["Кайра"],
        },
    )
    assert response.status_code == 409
    assert any("POV должен быть физически присутствующим" in x for x in response.json()["detail"]["issues"])
    assert doc["физически"] == []


def test_nonaligned_pov_and_relationships_still_rejected(api):
    response, doc = setup_and_verify(
        api,
        {"pov_id": "Лиам", "физически": ["Лиам"]},
    )
    assert response.status_code == 409
    assert any("pov_id различается" in x for x in response.json()["detail"]["issues"])
    assert doc["pov_id"] == "Лиам"


def test_missing_required_state_retains_foundation_validation_error(api):
    path = start_review(api)
    docs = make_docs()
    docs.pop("state.json")
    for name, document in docs.items():
        written = api.put(path + "/data", json={"path": name, "document": document})
        assert written.status_code == 200, written.text
    verification = api.post(path + "/verify", json={"audited_against_raw": True})
    assert verification.status_code == 409, verification.text
    assert verification.json()["detail"]["code"] == "FOUNDATION_INCOMPLETE"
    assert any("state.json" in issue for issue in verification.json()["detail"]["issues"])
