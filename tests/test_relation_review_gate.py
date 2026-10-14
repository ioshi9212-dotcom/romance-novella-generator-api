"""Server-side rejection of incomplete initial relationship facet transfers.

The server cannot know which feelings an LLM omitted from unrestricted prose,
but it CAN require an independent, exact RAW quote for each declared facet,
and ensure no declared facets silently disappear from numeric metrics.
"""
from test_creation import api, make_docs


RAW = (
    "Эдриан давно влюблён в Ренату.\n"
    "Эдриан эмоционально устал от отношений с Ренатой.\n"
    "Эдриан переживает за безопасность Ренаты.\n"
)
FACETS = {
    "чувство_a": "Эдриан давно влюблён в Ренату.",
    "чувство_b": "Эдриан эмоционально устал от отношений с Ренатой.",
    "чувство_c": "Эдриан переживает за безопасность Ренаты.",
}


def setup(api, review, metrics, *, more_npc=False):
    response = api.post("/sessions", json={"initial_text": RAW})
    assert response.status_code == 200, response.text
    url = "/sessions/" + response.json()["session_id"]
    for cmd in ("подтверждаю", "вопросов_больше_нет", "подтверждаю"):
        result = api.post(url + "/advance", json={"command": cmd})
        assert result.status_code == 200, result.text

    docs = make_docs()
    docs["персонажи.json"]["персонажи"][0]["имя"] = "Рената"
    docs["персонажи.json"]["персонажи"][1]["имя"] = "Эдриан"
    docs["отношения.json"]["персонажи"]["char_aiden"]["к_POV"]["параметры"] = metrics
    if review is None:
        docs["отношения.json"].pop("стартовая_сверка", None)
    else:
        docs["отношения.json"]["стартовая_сверка"] = review
    if more_npc:
        docs["персонажи.json"]["персонажи"].append({"id": "third", "имя": "Незнакомка"})
        docs["карточки/third.json"] = {"id": "third"}
        docs["память/third.json"] = {"персонаж_id": "third", "знания": {}, "личные_события": {}}
    for path, document in docs.items():
        r = api.put(url + "/data", json={"path": path, "document": document})
        assert r.status_code == 200, (path, r.text)
    return url


def report(*chosen):
    return {
        "char_aiden": {
            "статус": "есть_история",
            "аспекты": [
                {"показатель": key, "цитата_из_RAW": FACETS[key]}
                for key in chosen
            ],
        }
    }


def verify(api, url):
    return api.post(url + "/verify", json={"audited_against_raw": True})


def test_no_review_is_blocked(api):
    url = setup(api, None, {"чувство_a": 88})
    result = verify(api, url)
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "RELATIONSHIP_REVIEW_REQUIRED"
    assert "стартовая_сверка" in result.text
    assert api.get(url).json()["этап"] == "запись_и_сверка"


def test_multiple_documented_facets_cannot_be_reduced_to_one_metric(api):
    url = setup(api, report(*FACETS), {"чувство_c": 63})
    result = verify(api, url)
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "RELATIONSHIP_REVIEW_REQUIRED"
    issues = " ".join(result.json()["detail"]["issues"])
    assert "чувство_a" in issues and "чувство_b" in issues
    assert api.get(url).json()["этап"] == "запись_и_сверка"


def test_every_source_backed_facet_is_preserved(api):
    values = {"чувство_a": 93, "чувство_b": 78, "чувство_c": 64}
    url = setup(api, report(*FACETS), values)
    result = verify(api, url)
    assert result.status_code == 200, result.text
    assert result.json()["этап"] == "готово_к_игре"
    stored = api.get(url + "/data", params={"path": "отношения.json"}).json()["document"]
    assert stored["персонажи"]["char_aiden"]["к_POV"]["параметры"] == values


def test_fake_raw_evidence_rejected(api):
    fake = report("чувство_a")
    fake["char_aiden"]["аспекты"][0]["цитата_из_RAW"] = "Эдриан считает её инопланетянкой."
    url = setup(api, fake, {"чувство_a": 95})
    result = verify(api, url)
    assert result.status_code == 409
    assert "цитата не найдена" in result.text


def test_same_quote_cannot_justify_two_different_facets(api):
    fake = report("чувство_a", "чувство_b")
    fake["char_aiden"]["аспекты"][1]["цитата_из_RAW"] = FACETS["чувство_a"]
    url = setup(api, fake, {"чувство_a": 95, "чувство_b": 66})
    assert "одна и та же цитата" in verify(api, url).text


def test_all_npc_must_be_explicitly_checked_without_inventing_for_strangers(api):
    url = setup(api, report(*FACETS), {key: 60 for key in FACETS}, more_npc=True)
    failed = verify(api, url)
    assert failed.status_code == 409
    assert "third" in failed.text
    stored = api.get(url + "/data", params={"path": "отношения.json"}).json()["document"]
    stored["стартовая_сверка"]["third"] = {"статус": "не_знакомы", "аспекты": []}
    fixed = api.put(url + "/data", json={"path": "отношения.json", "document": stored})
    assert fixed.status_code == 200
    assert verify(api, url).status_code == 200


def test_stranger_cannot_be_given_backstory_metrics(api):
    review = report(*FACETS)
    review["char_aiden"] = {"статус": "не_знакомы", "аспекты": []}
    url = setup(api, review, {"чувство_a": 20})
    rejected = verify(api, url)
    assert rejected.status_code == 409
    assert "не_знакомы" not in rejected.text or "незнакомых" in rejected.text


def test_verified_initial_relationships_can_be_repaired_before_first_turn(api):
    url = setup(api, report("чувство_c"), {"чувство_c": 64})
    assert verify(api, url).status_code == 200
    previous = api.get(url + "/data", params={"path": "отношения.json"}).json()["document"]
    original_id = api.get(url).json()["session_id"]
    previous["стартовая_сверка"] = report(*FACETS)
    previous["персонажи"]["char_aiden"]["к_POV"]["параметры"] = {
        "чувство_a": 91, "чувство_b": 72, "чувство_c": 64
    }
    update = api.put(url + "/data", json={"path": "отношения.json", "document": previous})
    assert update.status_code == 200, update.text
    stored = api.get(url + "/data", params={"path": "отношения.json"}).json()["document"]
    assert len(stored["персонажи"]["char_aiden"]["к_POV"]["параметры"]) == 3
    assert api.get(url).json()["session_id"] == original_id
    assert api.get(url).json()["последний_ход"] == 0
    assert api.put(url + "/data", json={"path": "анкета.json", "document": {}}).status_code == 409


def test_bad_verified_relationship_correction_preserves_existing_document(api):
    url = setup(api, report("чувство_c"), {"чувство_c": 64})
    assert verify(api, url).status_code == 200
    from copy import deepcopy
    before = api.get(url + "/data", params={"path": "отношения.json"}).json()["document"]
    changed = deepcopy(before)
    changed["стартовая_сверка"] = report(*FACETS)
    changed["стартовая_сверка"]["char_aiden"]["аспекты"][0]["цитата_из_RAW"] = "Эдриан живёт на Луне и управляет кораблём."
    changed["персонажи"]["char_aiden"]["к_POV"]["параметры"] = {key: 50 for key in FACETS}
    rejected = api.put(url + "/data", json={"path": "отношения.json", "document": changed})
    assert rejected.status_code == 409
    unchanged = api.get(url + "/data", params={"path": "отношения.json"}).json()["document"]
    assert unchanged == before
