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
                    character_id="liam",
                    card="# Liam",
                    relationship_start="Относится настороженно.",
                )
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
