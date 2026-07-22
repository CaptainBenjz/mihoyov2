"""Tests for UID validation and the account service."""

from __future__ import annotations

import pytest

from bot.database.repository import UserRepository
from bot.services.account_service import AccountService, validate_uid
from bot.utils.errors import AccountNotLinked, InvalidUID


@pytest.mark.parametrize("uid", ["901211014", "600000000", "123456789"])
def test_validate_uid_accepts_valid(uid):
    assert validate_uid(uid) == uid


@pytest.mark.parametrize("uid", ["", "123", "0123456789", "abcdefghi", "12345678", "1234567890"])
def test_validate_uid_rejects_invalid(uid):
    with pytest.raises(InvalidUID):
        validate_uid(uid)


async def test_link_and_relink(session_factory):
    users = UserRepository(session_factory)
    service = AccountService(users)

    uid, relink = await service.link(111, "901211014")
    assert uid == "901211014"
    assert relink is False

    # Relinking to a different UID reports was_relink=True.
    uid2, relink2 = await service.link(111, "600000000")
    assert uid2 == "600000000"
    assert relink2 is True


async def test_require_uid_raises_when_not_linked(session_factory):
    users = UserRepository(session_factory)
    service = AccountService(users)
    with pytest.raises(AccountNotLinked):
        await service.require_uid(999)


async def test_unlink(session_factory):
    users = UserRepository(session_factory)
    service = AccountService(users)
    await service.link(222, "901211014")
    assert await service.unlink(222) is True
    # Second unlink returns False (nothing to remove).
    assert await service.unlink(222) is False
