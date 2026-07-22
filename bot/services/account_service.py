"""Account linking business logic: validate UID, link/unlink, resolve stored UID."""

from __future__ import annotations

import re

from bot.database.repository import UserRepository
from bot.utils.errors import AccountNotLinked, InvalidUID

# Genshin UIDs are 9 digits. Server is encoded in the leading digit(s):
#   1-5 = CN (Celestia/Irminsul etc.), 6 = America, 7 = Europe, 8 = Asia, 9 = TW/HK/MO.
_UID_RE = re.compile(r"^[1-9]\d{8}$")


def validate_uid(raw: str) -> str:
    """Validate and normalize a UID string. Raises :class:`InvalidUID` if malformed."""
    uid = (raw or "").strip()
    if not _UID_RE.match(uid):
        raise InvalidUID(f"Not a valid 9-digit UID: {raw!r}")
    return uid


class AccountService:
    """Links a Telegram user to a Genshin UID (one-time), stored in the database."""

    def __init__(self, users: UserRepository, default_language: str = "en") -> None:
        self._users = users
        self._default_language = default_language

    async def link(self, telegram_user_id: int, raw_uid: str) -> tuple[str, bool]:
        """Link a UID. Returns (uid, was_relink).

        ``was_relink`` is True if the user already had a (different) UID linked.
        """
        uid = validate_uid(raw_uid)
        previous = await self._users.get_uid(telegram_user_id)
        await self._users.link_uid(telegram_user_id, uid, self._default_language)
        return uid, previous is not None and previous != uid

    async def unlink(self, telegram_user_id: int) -> bool:
        """Unlink the user's UID. Returns True if a UID was present."""
        return await self._users.unlink_uid(telegram_user_id)

    async def get_uid(self, telegram_user_id: int) -> str | None:
        return await self._users.get_uid(telegram_user_id)

    async def require_uid(self, telegram_user_id: int) -> str:
        """Return the linked UID or raise :class:`AccountNotLinked`."""
        uid = await self._users.get_uid(telegram_user_id)
        if not uid:
            raise AccountNotLinked()
        return uid
