import sqlite3

from sklent import config, db


def test_legacy_db_is_adopted(tmp_path, monkeypatch):
    data = tmp_path / "old"
    data.mkdir()
    legacy = data / db.LEGACY_DB_NAME
    with sqlite3.connect(legacy) as conn:
        conn.executescript(db.SCHEMA)
        conn.execute("INSERT INTO settings (key, value) VALUES ('palette', '\"white\"')")
    monkeypatch.setenv("SK_DATA_DIR", str(data))
    config.get_settings.cache_clear()
    db.init()
    assert not legacy.exists()
    assert (data / "sklent.db").exists()
    with db.connect() as conn:
        assert conn.execute("SELECT value FROM settings WHERE key = 'palette'").fetchone()[0] == '"white"'


def test_new_db_wins_over_legacy(tmp_path, monkeypatch):
    data = tmp_path / "both"
    data.mkdir()
    monkeypatch.setenv("SK_DATA_DIR", str(data))
    config.get_settings.cache_clear()
    db.init()  # creates sklent.db
    (data / db.LEGACY_DB_NAME).write_bytes(b"old")
    db.init()
    assert (data / db.LEGACY_DB_NAME).read_bytes() == b"old"
    with db.connect() as conn:
        conn.execute("SELECT count(*) FROM settings").fetchone()
