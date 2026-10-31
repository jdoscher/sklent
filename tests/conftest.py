import pytest

from sklent import config, db


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SK_TOKEN", "test-token-0123456789")
    monkeypatch.setenv("SK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SK_FORGEJO_URL", "https://forge.example.com")
    monkeypatch.setenv("SK_FORGEJO_TOKEN", "forgejo-secret")
    monkeypatch.setenv("SK_KIST_URL", "")
    monkeypatch.setenv("SK_SCAN_INTERVAL_MINUTES", "0")
    config.get_settings.cache_clear()
    db.init()
    yield config.get_settings()
    config.get_settings.cache_clear()
