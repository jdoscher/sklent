from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SK_", extra="ignore")

    token: str = "change-me"
    data_dir: Path = Path("/data")
    solidcraft_cli: str = "solidcraft-cli"

    # Where render sets are filed. Empty URL = keep renders local only.
    kist_url: str = ""
    kist_token: str = ""
    kist_root_folder: str = "SolidCraft"

    # API tokens for private repos (optional for public ones).
    github_token: str = ""
    forgejo_url: str = "https://forge.example.com"
    forgejo_token: str = ""

    # Re-scan every source this often and render what changed; 0 turns it off.
    scan_interval_minutes: int = 360
    # Largest design file fetched from a repo.
    max_design_mb: int = 64
    # Per-design render timeout (seconds).
    render_timeout: int = 1800

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sklent.db"

    @property
    def renders_dir(self) -> Path:
        return self.data_dir / "renders"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"


@lru_cache
def get_settings() -> Settings:
    return Settings()
