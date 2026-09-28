from pathlib import Path
import pytest
import app.main as m

@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "ROOT", tmp_path / "data")
    return m.ROOT

def make():
    return m.create_session(m.NewSession(
        session_id="test", title="Test", novel="# Novel",
        characters=[m.Character(character_id="liam", card="# Liam")]
    ))

def turn(n, **kw):
    data={"turn_number":n,"user_text":f"user {n}","scene_text":f"scene {n}","chronology_note":f"important {n}"}
    data.update(kw)
    return m.Turn(**data)

def test_idempotent_turn(root):
    make()
    assert m.save_turn("test", turn(1))["idempotent"] is False
    assert m.save_turn("test", turn(1))["idempotent"] is True

def test_different_duplicate_conflicts(root):
    make(); m.save_turn("test", turn(1))
    with pytest.raises(m.HTTPException) as e:
        m.save_turn("test", turn(1, scene_text="different"))
    assert e.value.status_code == 409

def test_fifteen_turn_window_and_required_compaction(root):
    make()
    for n in range(1,16): m.save_turn("test", turn(n))
    with pytest.raises(m.HTTPException) as e:
        m.save_turn("test", turn(16))
    assert e.value.status_code == 409
    assert m.compact("test", m.Compact(through_turn=15, content="# Compact"))["idempotent"] is False
    assert m.compact("test", m.Compact(through_turn=15, content="# Compact"))["idempotent"] is True
    m.save_turn("test", turn(16))
    recent=m.state("test")["recent_turns"]
    assert "## Ход 1\n" not in recent
    assert "## Ход 2\n" in recent and "## Ход 16\n" in recent

def test_knowledge_is_character_scoped(root):
    make()
    m.save_turn("test", turn(1, knowledge_updates={"liam":"# Knowledge\nSaw it"}))
    assert "Saw it" in m.character_state("test","liam")["knowledge"]

def test_invalid_character_does_not_leave_pending_turn(root):
    make()
    with pytest.raises(m.HTTPException) as e:
        m.save_turn("test", turn(1, knowledge_updates={"ghost":"x"}))
    assert e.value.status_code == 400
    assert not (root/"test"/"turn_receipts"/"00000001.json").exists()
    assert m.save_turn("test", turn(1))["saved"] is True

def test_new_character_and_continuity(root):
    make()
    m.save_turn("test", turn(1,
        new_characters=[m.Character(character_id="akira", card="# Akira")],
        continuity="# Current\nLiam is standing close",
        plot_threads="# Threads\nMeeting tomorrow",
        relationship_updates={"akira":"# Relationship\nSuspicious of POV"}))
    st=m.state("test")
    assert "akira" in st["characters"]
    assert "standing close" in st["continuity"]
    assert "Meeting tomorrow" in st["plot_threads"]
