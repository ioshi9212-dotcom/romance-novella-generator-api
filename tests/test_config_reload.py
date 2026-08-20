from app.config import get_settings


def test_settings_reload_data_dir_after_cache_clear(monkeypatch, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"

    monkeypatch.setenv("DATA_DIR", str(first))
    get_settings.cache_clear()
    assert get_settings().data_dir == first

    monkeypatch.setenv("DATA_DIR", str(second))
    get_settings.cache_clear()
    assert get_settings().data_dir == second
