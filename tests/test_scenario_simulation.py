"""Deterministic gameplay integration simulation, not an LLM literary-quality test.

Run: python -m pytest -q tests/test_scenario_simulation.py -s
All story text is synthetic; assertions concern persistence, boundaries and
complete lossless payloads. No real Amvera sessions are touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import defaultdict
from pathlib import Path

from test_prepare_turn import ready  # pytest fixture supplies temporary session


def consume(client, obj):
    """Model the GPT client reading every fragment, including the first."""
    if not obj.get("chunked"):
        return obj, 0
    pieces = {0: obj["content"]}
    index = obj["next_chunk_index"]
    calls = 0
    while index is not None:
        response = client.get(f"/chunks/{obj['read_id']}/{index}")
        assert response.status_code == 200, response.text
        item = response.json()
        assert item["chunk_index"] == index
        assert len(item["content"]) <= 16_000
        assert item["read_id"] == obj["read_id"]
        pieces[index] = item["content"]
        index = item["next_chunk_index"]
        calls += 1
    assert set(pieces) == set(range(obj["chunk_count"]))
    raw = "".join(pieces[n] for n in range(obj["chunk_count"]))
    assert len(raw) == obj["total_chars"]
    assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == obj["sha256"]
    return json.loads(raw), calls


def action(client, method, url, *, body=None, query=None):
    t0 = time.perf_counter()
    response = client.request(method, url, json=body, params=query)
    elapsed = time.perf_counter() - t0
    assert response.status_code == 200, f"{method} {url}: {response.status_code} {response.text[:500]}"
    value, extra = consume(client, response.json())
    return value, extra, elapsed


def make_scene(number):
    """About 2,250 visible characters; unique per-turn evidence token."""
    unique = f"МЕТКА_СЦЕНЫ_{number:03d}"
    paragraph = (
        f"{unique}. В кофейне гремела посуда. Елена передвинула чашку; "
        f"Эйден посмотрел на дверь. Дождь постепенно становился сильнее. "
        f"Слова изменили смысл разговора, но никто не узнал чужих мыслей. "
    )
    return paragraph * 13


def test_120_turn_story_full_lifecycle_with_checks_and_churn(ready, capsys):
    client, url, root = ready
    turn_count = int(os.environ.get('NOVELLA_SIM_TURNS', '120'))
    assert turn_count >= 120 and turn_count % 60 == 0, 'Use 120, 180, 240, ... turns'
    start = time.perf_counter()
    seen_ids, stats = set(), defaultdict(int)
    touch_aiden = {i for i in range(1, turn_count + 1) if i % 11 == 0}
    last_packet, total_bytes = None, 0

    for n in range(1, turn_count + 1):
        selected = ["aiden"] if n in touch_aiden and n != 22 else []
        # Aiden later joins the physical scene for two turns.
        request = {"user_input": f"(Мой ход {n})", "additional_character_ids": selected}
        packet, extra, duration = action(client, "POST", url + "/prepare-turn", body=request)
        stats["prepare_calls"] += 1
        stats["chunk_calls"] += extra
        stats["prepare_ms_total"] += round(duration * 1000)
        assert packet["номер_хода"] == n
        assert packet["turn_id"] not in seen_ids
        seen_ids.add(packet["turn_id"])
        assert packet["ввод_игрока"] == request["user_input"]
        assert packet["режиссёр"]["state"]["pov_id"] == "pov"
        assert "pov" in packet["персонажи_подробно"]

        updates = {}
        if n % 5 == 0:
            updates["память/pov.json"] = [{
                "op": "append", "path": "/личные_события/03.09.2026",
                "value": f"лично запомнила ход {n}"
            }]
        # Off-scene memories may change only when their cards were explicitly loaded.
        if n in touch_aiden:
            assert "aiden" in packet["персонажи_подробно"]
            updates["память/aiden.json"] = [{
                "op": "append", "path": "/знания/03.09.2026",
                "value": f"Эйден услышал ход {n}, а не чужие внутренние мысли"
            }]
        if n == 20:
            updates["state.json"] = [{
                "op": "append", "path": "/физически", "value": {"id": "aiden", "одежда": "пальто"}
            }]
        if n == 22:
            updates["state.json"] = [{
                "op": "set", "path": "/физически", "value": [{"id": "pov", "одежда": "футболка"}]
            }]
        if n == 35:
            # Genuine new NPC added with registry, individual card and personal
            # memory in the same atomic turn. There is no permission to create
            # knowledge in another character's diary.
            updates["персонажи.json"] = [{
                "op": "append", "path": "/персонажи",
                "value": {"id": "new_35", "имя": "Нао", "стартовый": False}
            }]
            updates["карточки/new_35.json"] = [{
                "op": "set", "path": "", "value": {"id": "new_35", "имя": "Нао"}
            }]
            updates["память/new_35.json"] = [{
                "op": "set", "path": "", "value": {
                    "персонаж_id": "new_35", "знания": {"03.09.2026": ["Только личное прошлое Нао"]},
                    "личные_события": {}
                }
            }]
        if n == 42:
            updates["отношения.json"] = [{
                "op": "set", "path": "/персонажи/aiden/к_POV/параметры/доверие",
                "value": 44
            }]
        if n == 55:
            updates["отношения.json"] = [{
                "op": "set", "path": "/персонажи/aiden/к_POV/параметры/доверие",
                "value": 42
            }]
        scene = make_scene(n)
        total_bytes += len(scene.encode("utf-8"))
        assert 1_800 <= len(scene.replace(" ", "")) <= 3_000
        save_request = {
            "turn_id": packet["turn_id"], "user_input": request["user_input"],
            "context_sha256": packet["контекст_sha256"], "scene": scene,
            "updates": updates, "additional_character_ids": selected
        }
        saved, _, _ = action(client, "POST", url + "/commit-turn", body=save_request)
        assert saved["status"] == "saved"
        assert saved["номер_хода"] == n
        stats["commits"] += 1
        last_packet = packet

        if n in (40, 95, 119, 215):
            resumed, chunks, _ = action(client, "GET", url + "/resume")
            stats["chunk_calls"] += chunks
            assert resumed["последний_ход"] == n
            assert resumed["следующий_ход"] == n + 1
            assert resumed["последние_сцены"][-1]["сцена"] == scene
            stats["resume_checks"] += 1
        if n in (36, 78, 117, 217):
            old, chunks, _ = action(client, "GET", url + "/turns", query={
                "from_turn": n - 14, "to_turn": n
            })
            stats["chunk_calls"] += chunks
            assert len(old["сцены"]) == 15
            assert old["сцены"][-1]["сцена"] == scene
            assert f"МЕТКА_СЦЕНЫ_{n-14:03d}" in old["сцены"][0]["сцена"]
            stats["archival_checks"] += 1

        if n % 15 == 0:
            # Network retries must remain idempotent, including checkpoints
            # that block *new* turns while an audit or compaction is due.
            repeated = client.post(url + "/commit-turn", json=save_request)
            assert repeated.status_code == 200, repeated.text
            assert repeated.json()["status"] == "already_saved"
            blocked = client.post(url + "/prepare-turn", json={"user_input": "не должно пройти"})
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["detail"]["code"] == "AUDIT_REQUIRED"
            report, chunks, _ = action(client, "POST", url + "/prepare-audit", body={"character_ids": []})
            stats["chunk_calls"] += chunks
            stats["audit_calls"] += 1
            assert report["through_turn"] == n
            assert report["период"] == [n - 14, n]
            assert len(report["архив"]) == 15
            assert report["архив"][-1]["сцена"] == scene
            result, _, _ = action(client, "POST", url + "/commit-audit", body={
                "through_turn": n, "audit_sha256": report["audit_sha256"],
                "reviewed_against_archive": True, "character_ids": [],
                "findings": [f"Синтетическая проверка ходов {n-14}..{n}: без поправок"],
                "evidence_turns": {}, "updates": {}
            })
            assert result["status"] == "audited"
            if n % 60 == 0:
                blocked = client.post(url + "/prepare-turn", json={"user_input": "ещё нельзя"})
                assert blocked.status_code == 409
                assert blocked.json()["detail"]["code"] == "COMPACTION_REQUIRED"
                compact, chunks, _ = action(client, "POST", url + "/prepare-compaction")
                stats["chunk_calls"] += chunks
                assert compact["through_turn"] == n
                assert len(compact["archive"]) == 60
                assert len(compact["recent_scenes"]) == 15
                assert len(compact["character_ids"]) == (4 if n >= 35 else 3)
                compressed, _, _ = action(client, "POST", url + "/commit-compaction", body={
                    "through_turn": n, "review_sha256": compact["review_sha256"],
                    "reviewed_against_archive": True,
                    "world_summary": f"Проверенная контрольная сводка истории по {n}-й ход; подробности в RAW",
                    "character_summaries": {
                        cid: f"Проверенная сводка {cid} по {n}-й ход; исходный дневник сохранён"
                        for cid in compact["character_ids"]
                    }
                })
                assert compressed["full_memory_preserved"] is True
                stats["compactions"] += 1

    assert len(seen_ids) == turn_count
    assert stats["audit_calls"] == turn_count // 15
    assert stats["compactions"] == turn_count // 60
    archive = (root / "ходы.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(archive) == turn_count
    assert [json.loads(line)["номер"] for line in archive] == list(range(1, turn_count + 1))
    memory = json.loads((root / "память/pov.json").read_text(encoding="utf-8"))
    aiden = json.loads((root / "память/aiden.json").read_text(encoding="utf-8"))
    nao = json.loads((root / "память/new_35.json").read_text(encoding="utf-8"))
    assert len(memory["личные_события"]["03.09.2026"]) == 1 + turn_count // 5
    assert len(aiden["знания"]["03.09.2026"]) == 1 + len(touch_aiden)
    assert all("Эйден услышал" not in x for x in memory["личные_события"]["03.09.2026"])
    assert nao["знания"]["03.09.2026"] == ["Только личное прошлое Нао"]
    assert json.loads((root / "отношения.json").read_text(encoding="utf-8"))["персонажи"]["aiden"]["к_POV"]["параметры"]["доверие"] == 42

    next_packet, chunks, _ = action(client, "POST", url + "/prepare-turn", body={
        "user_input": "(Следующий ход)", "full_memory_character_ids": ["pov"]
    })
    stats["chunk_calls"] += chunks
    assert next_packet["номер_хода"] == turn_count + 1
    assert next_packet["последнее_сжатие"] == turn_count
    assert len(next_packet["персонажи_подробно"]["pov"]["память"]["личные_события"]["03.09.2026"]) == 1 + turn_count // 5
    assert "aiden" not in next_packet["персонажи_подробно"]
    duration_s = round(time.perf_counter() - start, 3)
    output = {
        "test": f"synthetic_{turn_count}_turns", "turns": turn_count, "audits": turn_count // 15,
        "compactions": turn_count // 60, "api_chunk_followups": stats["chunk_calls"],
        "total_scene_utf8_bytes": total_bytes, "duration_seconds": duration_s,
        "prepare_ms_total": stats["prepare_ms_total"],
        "story_files_preserved": True,
    }
    print("NOVELLA_SIMULATION_METRICS " + json.dumps(output, ensure_ascii=False), flush=True)


def test_stale_writer_repeat_and_memory_isolation(ready):
    client, url, root = ready
    prepared, _, _ = action(client, "POST", url + "/prepare-turn", body={
        "user_input": "Одинаковая исходная сцена"
    })
    assert "aiden" not in prepared["персонажи_подробно"]
    bad = client.post(url + "/commit-turn", json={
        "turn_id": prepared["turn_id"], "user_input": prepared["ввод_игрока"],
        "context_sha256": prepared["контекст_sha256"], "scene": make_scene(1),
        "updates": {"память/aiden.json": [{
            "op": "append", "path": "/знания/03.09.2026",
            "value": "Незаконно переданное чужое знание"
        }]}
    })
    assert bad.status_code == 409
    assert "Незаконно" not in (root / "память/aiden.json").read_text(encoding="utf-8")
    payload = {
        "turn_id": prepared["turn_id"], "user_input": prepared["ввод_игрока"],
        "context_sha256": prepared["контекст_sha256"], "scene": make_scene(1),
        "updates": {},
    }
    success = client.post(url + "/commit-turn", json=payload)
    assert success.status_code == 200
    repeat = client.post(url + "/commit-turn", json=payload)
    assert repeat.status_code == 200 and repeat.json()["status"] == "already_saved"
    rejected = client.post(url + "/commit-turn", json={**payload, "scene": make_scene(2)})
    assert rejected.status_code == 409
    assert len((root / "ходы.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_critical_relationship_and_rollback_restores_everything(ready):
    client, url, root = ready
    packet, _, _ = action(client, "POST", url + "/prepare-turn", body={
        "user_input": "Произошло предательство"
    })
    payload = {
        "turn_id": packet["turn_id"], "user_input": packet["ввод_игрока"],
        "context_sha256": packet["контекст_sha256"], "scene": make_scene(1) + " Эйден передал врагу секрет.",
        "updates": {"отношения.json": [
            {"op": "set", "path": "/персонажи/aiden/к_POV/параметры/доверие", "value": 0},
            {"op": "set", "path": "/персонажи/aiden/к_POV/параметры/недоверие", "value": 30},
        ]},
        "relationship_exceptions": [
            {"owner_id": "aiden", "parameter": "доверие", "reason": "В сцене он передал врагу секрет и предал друга"},
            {"owner_id": "aiden", "parameter": "недоверие", "reason": "После доказанного предательства резко возникло недоверие"},
        ]
    }
    saved = client.post(url + "/commit-turn", json=payload)
    assert saved.status_code == 200, saved.text
    scores = json.loads((root/"отношения.json").read_text(encoding="utf-8"))["персонажи"]["aiden"]["к_POV"]["параметры"]
    assert scores == {"доверие": 0, "недоверие": 30}
    wrong = client.post(url+"/rollback-last-turn", json={"expected_turn_id": "wrong"})
    assert wrong.status_code == 409
    undone = client.post(url+"/rollback-last-turn", json={"expected_turn_id": packet["turn_id"]})
    assert undone.status_code == 200
    scores = json.loads((root/"отношения.json").read_text(encoding="utf-8"))["персонажи"]["aiden"]["к_POV"]["параметры"]
    assert scores == {"доверие": 42}
    assert not (root/"ходы.jsonl").read_text(encoding="utf-8").strip()


def test_simultaneous_commit_retries_and_competing_writers(ready):
    """Two simulated GPT calls must never duplicate or overwrite a turn."""
    from concurrent.futures import ThreadPoolExecutor

    client, url, root = ready
    first, _, _ = action(client, "POST", url + "/prepare-turn", body={
        "user_input": "(Первый многопоточный ход)"
    })
    payload = {
        "turn_id": first["turn_id"], "user_input": first["ввод_игрока"],
        "context_sha256": first["контекст_sha256"],
        "scene": make_scene(1), "updates": {}
    }

    def submit(body):
        r = client.post(url + "/commit-turn", json=body)
        return r.status_code, r.json()

    with ThreadPoolExecutor(max_workers=5) as threads:
        results = list(threads.map(submit, [payload] * 5))
    assert all(status == 200 for status, _ in results), results
    assert sorted(doc["status"] for _, doc in results) == (
        ["already_saved"] * 4 + ["saved"]
    )
    assert len((root / "ходы.jsonl").read_text(encoding="utf-8").splitlines()) == 1

    second, _, _ = action(client, "POST", url + "/prepare-turn", body={
        "user_input": "(Второй многопоточный ход)"
    })
    base = {
        "turn_id": second["turn_id"], "user_input": second["ввод_игрока"],
        "context_sha256": second["контекст_sha256"], "updates": {}
    }
    a, b = {**base, "scene": make_scene(2)}, {**base, "scene": make_scene(3)}
    with ThreadPoolExecutor(max_workers=2) as threads:
        competing = list(threads.map(submit, [a, b]))
    assert sorted(status for status, _ in competing) == [200, 409], competing
    archived = [json.loads(row) for row in (root / "ходы.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["номер"] for row in archived] == [1, 2]
    assert archived[-1]["сцена"] in (a["scene"], b["scene"])


def test_prepare_commit_refuses_direct_out_of_band_file_mutation(ready):
    """A silently changed memory file invalidates an old prepared context."""
    client, url, root = ready
    packet, _, _ = action(client, "POST", url + "/prepare-turn", body={
        "user_input": "(Проверяю устаревший контекст)"
    })
    memory_file = root / "память" / "pov.json"
    before = json.loads(memory_file.read_text(encoding="utf-8"))
    tampered = json.loads(memory_file.read_text(encoding="utf-8"))
    tampered["знания"]["03.09.2026"].append("внешнее изменение до сохранения")
    memory_file.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
    response = client.post(url + "/commit-turn", json={
        "turn_id": packet["turn_id"], "user_input": packet["ввод_игрока"],
        "context_sha256": packet["контекст_sha256"],
        "scene": make_scene(1), "updates": {}
    })
    assert response.status_code == 409
    assert not (root / "ходы.jsonl").exists()
    after = json.loads(memory_file.read_text(encoding="utf-8"))
    assert "внешнее изменение до сохранения" in after["знания"]["03.09.2026"]
    assert after != before
