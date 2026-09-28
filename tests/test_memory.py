import pytest
import app.main as m


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "ROOT", tmp_path / "data")
    return m.ROOT


def new_session():
    return m.create_session(m.NewSession(session_id="test", title="Test"))


def setup_ready():
    new_session()
    m.append_setup_message("test", m.SetupChunk(message_number=1, text="Хочу мистический роман."))
    m.finalize_setup(
        "test",
        m.FinalizeSetup(
            novel="# Novel",
            novel_rules="# Rules",
            hidden_lore="# Lore",
            pov_character_id="pov",
            characters=[
                m.Character(
                    character_id="pov",
                    card="# POV",
                ),
                m.Character(
                    character_id="liam",
                    card="# Liam",
                    relationship_start="Относится настороженно.",
                ),
            ],
        ),
    )
    m.save_opening_scene("test", m.OpeningScene(scene_text="Opening scene"))


def turn(n, **kw):
    data = {
        "turn_number": n,
        "user_text": f"user {n}",
        "scene_text": f"scene {n}",
        "chronology_note": f"important {n}",
    }
    data.update(kw)
    return m.Turn(**data)


def test_setup_source_is_exact_and_idempotent(root):
    new_session()
    raw = "  Точный текст.\nНе исправлять!  "
    assert m.append_setup_message("test", m.SetupChunk(message_number=1, text=raw))["idempotent"] is False
    assert m.append_setup_message("test", m.SetupChunk(message_number=1, text=raw))["idempotent"] is True
    source = m.state("test")["setup_source"]
    assert raw in source


def test_setup_message_conflict(root):
    new_session()
    m.append_setup_message("test", m.SetupChunk(message_number=1, text="one"))
    with pytest.raises(m.HTTPException) as e:
        m.append_setup_message("test", m.SetupChunk(message_number=1, text="two"))
    assert e.value.status_code == 409


def test_turn_blocked_before_finalize_and_opening(root):
    new_session()
    with pytest.raises(m.HTTPException):
        m.save_turn("test", turn(1))
    m.append_setup_message("test", m.SetupChunk(message_number=1, text="x"))
    m.finalize_setup("test", m.FinalizeSetup(novel="# N", characters=[]))
    with pytest.raises(m.HTTPException):
        m.save_turn("test", turn(1))


def test_finalize_and_opening_are_idempotent(root):
    new_session()
    m.append_setup_message("test", m.SetupChunk(message_number=1, text="рандомная"))
    out = m.finalize_setup(
        "test",
        m.FinalizeSetup(novel="# Novel", characters=[m.Character(character_id="liam")]),
    )
    assert out["finalized"] is True
    first = m.save_opening_scene("test", m.OpeningScene(scene_text="Start"))
    second = m.save_opening_scene("test", m.OpeningScene(scene_text="Start"))
    assert first["idempotent"] is False
    assert second["idempotent"] is True


def test_idempotent_turn(root):
    setup_ready()
    assert m.save_turn("test", turn(1))["idempotent"] is False
    assert m.save_turn("test", turn(1))["idempotent"] is True


def test_different_duplicate_conflicts(root):
    setup_ready()
    m.save_turn("test", turn(1))
    with pytest.raises(m.HTTPException) as e:
        m.save_turn("test", turn(1, scene_text="different"))
    assert e.value.status_code == 409


def test_fifteen_turn_window_and_required_compaction(root):
    setup_ready()
    for n in range(1, 16):
        m.save_turn("test", turn(n))
    with pytest.raises(m.HTTPException) as e:
        m.save_turn("test", turn(16))
    assert e.value.status_code == 409

    assert m.compact("test", m.Compact(through_turn=15, content="first block"))["idempotent"] is False
    assert m.compact("test", m.Compact(through_turn=15, content="first block"))["idempotent"] is True

    m.save_turn("test", turn(16))
    recent = m.state("test")["recent_turns"]
    assert "## Ход 1\n" not in recent
    assert "## Ход 2\n" in recent
    assert "## Ход 16\n" in recent


def test_multiple_compactions_preserve_old_blocks(root):
    setup_ready()
    for n in range(1, 16):
        m.save_turn("test", turn(n))
    m.compact("test", m.Compact(through_turn=15, content="FIRST"))
    for n in range(16, 31):
        m.save_turn("test", turn(n))
    m.compact("test", m.Compact(through_turn=30, content="SECOND"))
    chronology = m.state("test")["chronology"]
    assert "FIRST" in chronology
    assert "SECOND" in chronology
    assert chronology.index("FIRST") < chronology.index("SECOND")


def test_knowledge_accumulates_from_receipts(root):
    setup_ready()
    m.save_turn("test", turn(1, knowledge_updates={"liam": "Увидел красную машину."}))
    m.save_turn("test", turn(2, knowledge_updates={"liam": "Услышал имя Маркус."}))
    knowledge = m.character_state("test", "liam")["knowledge"]
    assert "Увидел красную машину." in knowledge
    assert "Услышал имя Маркус." in knowledge


def test_relationship_history_accumulates(root):
    setup_ready()
    m.save_turn("test", turn(1, relationship_updates={"liam": "Стал меньше доверять после лжи."}))
    m.save_turn("test", turn(2, relationship_updates={"liam": "Ревность появилась после встречи с Маркусом."}))
    relationship = m.character_state("test", "liam")["relationship"]
    assert "Относится настороженно." in relationship
    assert "Стал меньше доверять" in relationship
    assert "Ревность появилась" in relationship


def test_invalid_character_does_not_leave_pending_turn(root):
    setup_ready()
    with pytest.raises(m.HTTPException) as e:
        m.save_turn("test", turn(1, knowledge_updates={"ghost": "x"}))
    assert e.value.status_code == 400
    assert not (root / "test" / "turn_receipts" / "00000001.json").exists()
    assert m.save_turn("test", turn(1))["saved"] is True


def test_new_character_and_continuity(root):
    setup_ready()
    m.save_turn(
        "test",
        turn(
            1,
            new_characters=[
                m.Character(
                    character_id="akira",
                    card="# Akira",
                    relationship_start="Не знаком с POV.",
                )
            ],
            continuity="# Current\nLiam стоит вплотную.",
            plot_threads="# Threads\nВстреча завтра.",
            relationship_updates={"akira": "Заинтересовался POV после разговора."},
        ),
    )
    st = m.state("test")
    assert "akira" in st["characters"]
    assert "стоит вплотную" in st["continuity"]
    assert "Встреча завтра" in st["plot_threads"]
    rel = m.character_state("test", "akira")["relationship"]
    assert "Не знаком с POV." in rel
    assert "Заинтересовался POV" in rel


def test_continuity_keeps_current_snapshot_and_event_history(root):
    setup_ready()
    m.save_turn(
        "test",
        turn(
            1,
            continuity="POV стоит у двери. Liam вплотную справа. В руке POV телефон.",
            continuity_events="POV сделала фото Liam. Фото сохранено в телефоне POV.",
        ),
    )
    m.save_turn(
        "test",
        turn(
            2,
            continuity="POV сидит за столом. Liam напротив. Телефон лежит на столе.",
            continuity_events="POV отправила фото Liam. Фото теперь есть у POV и Liam.",
        ),
    )
    state = m.state("test")
    text = state["continuity"]
    assert "POV сидит за столом" in text
    assert "POV стоит у двери" not in text
    assert "Фото сохранено в телефоне POV" in text
    assert "Фото теперь есть у POV и Liam" in text


def test_initial_hidden_thread_survives_later_updates(root):
    new_session()
    m.append_setup_message("test", m.SetupChunk(message_number=1, text="История с тайной."))
    m.finalize_setup(
        "test",
        m.FinalizeSetup(
            novel="# Novel",
            plot_threads="Тайный крючок: POV пока не знает. Должен привести к встрече.",
            characters=[m.Character(character_id="liam")],
        ),
    )
    m.save_opening_scene("test", m.OpeningScene(scene_text="Start"))
    m.save_turn(
        "test",
        turn(1, plot_threads="Новый крючок: Liam договорился позвонить завтра."),
    )
    threads = m.state("test")["plot_threads"]
    assert "Тайный крючок" in threads
    assert "позвонить завтра" in threads


def test_state_repairs_meta_and_ignores_uncommitted_turn(root):
    setup_ready()
    committed = turn(
        1,
        continuity="Канон: POV сидит.",
        continuity_events="POV положила ключ в карман.",
    )
    m.save_turn("test", committed)

    sd = root / "test"
    pending = turn(
        2,
        continuity="НЕ КАНОН: POV уже на крыше.",
        continuity_events="НЕ КАНОН: ключ выброшен.",
    )
    payload = pending.model_dump(mode="json")
    m.jwrite(
        sd / "turn_receipts" / "00000002.json",
        {"status": "pending", "hash": m.digest_obj(payload), "payload": payload},
    )

    meta = m.jread(sd / "meta.json")
    meta["last_saved_turn"] = 2
    meta["world_time"] = "23:59"
    m.jwrite(sd / "meta.json", meta)

    state = m.state("test")
    assert state["meta"]["last_saved_turn"] == 1
    assert "Канон: POV сидит." in state["continuity"]
    assert "НЕ КАНОН" not in state["continuity"]
    assert "ключ в карман" in state["continuity"]


def test_pending_turn_can_be_retried_and_committed(root):
    setup_ready()
    req = turn(
        1,
        continuity="POV у окна.",
        continuity_events="POV передала письмо Liam.",
    )
    sd = root / "test"
    payload = req.model_dump(mode="json")
    m.jwrite(
        sd / "turn_receipts" / "00000001.json",
        {"status": "pending", "hash": m.digest_obj(payload), "payload": payload},
    )
    result = m.save_turn("test", req)
    assert result["saved"] is True
    assert m.jread(sd / "turn_receipts" / "00000001.json")["status"] == "committed"
    assert "передала письмо" in m.state("test")["continuity"]


def test_three_compaction_cycles_keep_all_history(root):
    setup_ready()
    for n in range(1, 46):
        m.save_turn(
            "test",
            turn(
                n,
                knowledge_updates={"liam": f"Факт {n}"} if n in (3, 18, 34) else {},
                relationship_updates={"liam": f"Изменение {n}"} if n in (7, 22, 41) else {},
            ),
        )
        if n in (15, 30, 45):
            m.compact(
                "test",
                m.Compact(through_turn=n, content=f"СВЁРТКА {n - 14}-{n}"),
            )

    state = m.state("test")
    chronology = state["chronology"]
    assert "СВЁРТКА 1-15" in chronology
    assert "СВЁРТКА 16-30" in chronology
    assert "СВЁРТКА 31-45" in chronology
    assert state["meta"]["last_saved_turn"] == 45
    assert state["meta"]["last_compaction_turn"] == 45

    knowledge = m.character_state("test", "liam")["knowledge"]
    assert "Факт 3" in knowledge
    assert "Факт 18" in knowledge
    assert "Факт 34" in knowledge

    relationship = m.character_state("test", "liam")["relationship"]
    assert "Изменение 7" in relationship
    assert "Изменение 22" in relationship
    assert "Изменение 41" in relationship


def test_character_additions_accumulate_without_overwriting_card(root):
    setup_ready()
    m.save_turn(
        "test",
        turn(1, character_updates={"liam": "Любит очень крепкий кофе без сахара."}),
    )
    m.save_turn(
        "test",
        turn(2, character_updates={"liam": "По привычке крутит кольцо на пальце, когда нервничает."}),
    )
    card = m.character_state("test", "liam")["card"]
    assert "# Liam" in card
    assert "крепкий кофе" in card
    assert "крутит кольцо" in card


def test_pov_has_own_starting_knowledge(root):
    new_session()
    m.append_setup_message("test", m.SetupChunk(message_number=1, text="POV до старта читала досье Liam."))
    m.finalize_setup(
        "test",
        m.FinalizeSetup(
            novel="# Novel",
            pov_character_id="pov",
            characters=[
                m.Character(
                    character_id="pov",
                    card="# POV",
                    knowledge_start="До первой сцены читала досье Liam и знает, что ему 27 лет.",
                ),
                m.Character(character_id="liam", card="# Liam"),
            ],
        ),
    )
    knowledge = m.character_state("test", "pov")["knowledge"]
    assert "читала досье Liam" in knowledge
    assert "27 лет" in knowledge
