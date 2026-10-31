import pytest

from lookaskew import config, db


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LA_TOKEN", "test-token-0123456789")
    monkeypatch.setenv("LA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LA_FORGEJO_URL", "https://forge.example.com")
    monkeypatch.setenv("LA_FORGEJO_TOKEN", "forgejo-secret")
    monkeypatch.setenv("LA_KIST_URL", "")
    monkeypatch.setenv("LA_SCAN_INTERVAL_MINUTES", "0")
    config.get_settings.cache_clear()
    db.init()
    yield config.get_settings()
    config.get_settings.cache_clear()
