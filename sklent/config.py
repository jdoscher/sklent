from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    forgejo_url: str = ""
    forgejo_token: str = ""

    # Re-scan every source this often and render what changed; 0 turns it off.
    scan_interval_minutes: int = 360
    # Largest design file fetched from a repo.
    max_design_mb: int = 64
    # Per-design render timeout (seconds).
    render_timeout: int = 1800
    # Most SolidCraft processes rendering one design's frames at once. More are used only
    # when a frame is slow (big designs) and free memory holds them; each loads the design.
    render_processes: int = Field(default=4, ge=1, le=16)

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
