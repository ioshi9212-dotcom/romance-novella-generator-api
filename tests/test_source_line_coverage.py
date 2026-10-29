"""Literal RAW coverage is an honest diagnostic, not a semantic oracle."""
from app.source_line_coverage import source_line_coverage


def test_original_rough_wording_is_not_counted_when_only_softened():
    author = "Дантэ охуенно ревнивый, но никогда не признается."
    second = "Сайлас должен помнить точное условие наказания."
    report = source_line_coverage(
        [{"block_id": "original", "raw_text": author + "\n" + second}],
        {"characters": [
            {"character": author, "generated_details": {
                "description": second,  # Invented/AI-controlled fields never count as canon evidence.
            }},
        ]},
    )
    assert report["available"] is True
    assert report["eligible_source_lines"] == 2
    assert report["literal_lines_found"] == 1
    assert report["literal_lines_not_found"] == 1
    assert report["unmatched_line_locations"][0]["line"] == 2
    assert len(report["unmatched_line_locations"][0]["sha256"]) == 64
    assert "NOT proof" in report["interpretation"]
    assert second not in str(report["unmatched_line_locations"])


def test_old_prefix_does_not_double_count_complete_new_original():
    raw = "Первое дословное правило романа.\nВторое важное правило персонажа."
    report = source_line_coverage(
        [{"block_id": "short_old", "raw_text": raw[:32]},
         {"block_id": "full_original", "raw_text": raw}],
        {"novel": {"story_rules": raw}},
    )
    assert report["raw_blocks_considered"] == 1
    assert report["eligible_source_lines"] == 2
    assert report["literal_lines_found"] == 2


def test_no_saved_original_is_reported_as_unavailable():
    report = source_line_coverage([], {"novel": {"character": "foo"}})
    assert report["available"] is False
    assert report["reason"] == "RAW_NOT_SAVED"


def test_generator_session_status_opt_in_only_exposes_safe_line_indices(ready):
    client, base, _ = ready
    baseline = client.get(base)
    assert baseline.status_code == 200
    assert "literal_raw_coverage" not in baseline.json()

    audit = client.get(base, params={"include_literal_coverage": "true"})
    assert audit.status_code == 200, audit.text
    report = audit.json()["literal_raw_coverage"]
    assert report["available"]
    assert report["eligible_source_lines"] >= 1
    assert isinstance(report["unmatched_line_locations"], list)
    assert "raw_text" not in audit.json()
