"""Distinguish backend context preparation from GPT thinking or Actions overhead."""
from test_prepare_turn import ready


def test_prepare_reports_server_duration_not_total_gpt_response_time(ready):
    client, base, _folder = ready
    response = client.post(base + "/prepare-turn", json={"user_input": "Привет"})
    assert response.status_code == 200, response.text
    value = response.json()
    assert isinstance(value.get("server_prepare_ms"), (int, float))
    assert 0 <= value["server_prepare_ms"] < 10000
