"""Application configuration.

All settings are read from environment variables (or a local ``.env`` file) via
``pydantic-settings``. Nothing here is hardcoded so the same code runs in dev and prod.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (two levels up from this file: bot/config.py -> repo root).
ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed application settings loaded from the environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: str = ""

    # Redis — the primary persistent datastore (Upstash-compatible).
    # Upstash redis:// URLs are auto-upgraded to TLS (rediss://) by the Redis client.
    redis_url: str = ""

    # Localization
    default_language: str = "en"

    # Caching (seconds)
    enka_cache_ttl: int = 300
    akasha_cache_ttl: int = 600

    # Assets
    assets_dir: str = "assets"

    # Logging
    log_level: str = "INFO"

    @property
    def assets_path(self) -> Path:
        """Absolute path to the assets root directory."""
        p = Path(self.assets_dir)
        return p if p.is_absolute() else (ROOT_DIR / p)

    @property
    def translations_path(self) -> Path:
        """Absolute path to the bundled locale files."""
        return ROOT_DIR / "bot" / "translations" / "locales"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton settings instance."""
    return Settings()
