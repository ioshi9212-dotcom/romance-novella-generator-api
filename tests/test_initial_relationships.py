"""Initial relationships must retain any number of canon-supported facets.

No predefined emotional axes: numeric names are deliberately arbitrary. These
tests assert mechanical capability, not LLM semantic interpretation of RAW.
"""
from test_creation import api, make_docs, start_review


def _verified_story(api, facets):
    url = start_review(api)
    docs = make_docs()
    docs["отношения.json"]["персонажи"]["char_aiden"]["к_POV"]["параметры"] = facets
    for path, payload in docs.items():
        response = api.put(url + "/data", json={"path": path, "document": payload})
        assert response.status_code == 200, (path, response.text)
    verified = api.post(url + "/verify", json={"audited_against_raw": True})
    assert verified.status_code == 200, verified.text
    return url


def test_five_existing_independent_facets_remain_intact_at_game_start(api):
    # Initial values are NOT subject to gameplay's +/-3 transition limit.
    facets = {
        "грань_а": 92, "грань_б": 78, "грань_в": 64,
        "грань_г": 51, "грань_д": 37,
    }
    url = _verified_story(api, facets)
    saved = api.get(url + "/data", params={"path": "отношения.json"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["document"]["персонажи"]["char_aiden"]["к_POV"]["параметры"] == facets

    # The very first turn must receive the same five values, unchanged.
    response = api.post(url + "/prepare-turn", json={"user_input": "(Начать сцену)"})
    assert response.status_code == 200, response.text
    from test_scenario_simulation import consume
    packet, _ = consume(api, response.json())
    assert packet["режиссёр"]["отношения"]["персонажи"]["char_aiden"]["к_POV"]["параметры"] == facets


def test_unacquainted_npc_can_start_without_made_up_relationships(api):
    url = _verified_story(api, {})
    saved = api.get(url + "/data", params={"path": "отношения.json"})
    assert saved.json()["document"]["персонажи"]["char_aiden"]["к_POV"]["параметры"] == {}


def test_implicit_label_templates_are_not_required_by_foundation(api):
    # No forced one-dimensional metric or fixed dictionary is permitted.
    url = _verified_story(api, {"своя_ось_отношения": 88})
    saved = api.get(url + "/data", params={"path": "отношения.json"})
    assert saved.json()["document"]["персонажи"]["char_aiden"]["к_POV"]["параметры"] == {
        "своя_ось_отношения": 88
    }
