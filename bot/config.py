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

    # Bot administrators (comma/space-separated Telegram user ids). Only these users may
    # run owner commands such as /broadcast. Empty = no admins (owner commands are dormant).
    admin_ids: str = ""

    # HoYoLAB session cookie for the bot's configured account, used by /redeem to claim
    # gift codes automatically (no UID/login prompt, no website redirect). Paste the full
    # cookie string from an authenticated HoYoLAB session (must include cookie_token_v2 /
    # account_id_v2 or the legacy cookie_token / account_id). Empty = /redeem reports that
    # the session must be configured. Never commit this — keep it in the environment only.
    hoyolab_cookie: str = ""

    # Redis — the primary persistent datastore (Upstash-compatible).
    # Upstash redis:// URLs are auto-upgraded to TLS (rediss://) by the Redis client.
    redis_url: str = ""

    # Redis fast-fail tuning. Kept low so that when Redis is unreachable a command fails
    # in a couple of seconds (with a clear message) instead of hanging on long timeouts.
    # Upstash round-trips are well under a second, so these are comfortably safe.
    redis_connect_timeout: float = 4.0
    redis_socket_timeout: float = 4.0
    redis_retries: int = 1
    # After a Redis failure, bypass it for this many seconds (circuit breaker) so commands
    # don't repeatedly wait on a dead connection — they use the local fallback instead.
    redis_breaker_cooldown: float = 30.0

    # Local fallback store: keeps logins/settings working when Redis is unreachable.
    # Relative paths resolve under the repo root. Point at a mounted volume for durability.
    local_store_path: str = "data/local_store.json"

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
    def admin_id_set(self) -> set[int]:
        """Parsed set of admin Telegram user ids (tolerant of commas/spaces + junk)."""
        out: set[int] = set()
        for part in self.admin_ids.replace(",", " ").split():
            try:
                out.add(int(part))
            except ValueError:
                continue
        return out

    @property
    def assets_path(self) -> Path:
        """Absolute path to the assets root directory."""
        p = Path(self.assets_dir)
        return p if p.is_absolute() else (ROOT_DIR / p)

    @property
    def translations_path(self) -> Path:
        """Absolute path to the bundled locale files."""
        return ROOT_DIR / "bot" / "translations" / "locales"

    @property
    def local_store_file(self) -> Path:
        """Absolute path to the local fallback store file."""
        p = Path(self.local_store_path)
        return p if p.is_absolute() else (ROOT_DIR / p)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton settings instance."""
    return Settings()
