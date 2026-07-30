"""Tests for the cookie encryption helper."""

from __future__ import annotations

from bot.utils.crypto import CookieCipher


def test_roundtrip():
    c = CookieCipher("a-long-random-secret")
    token = c.encrypt("cookie_token_v2=abc; account_id_v2=1")
    assert token != "cookie_token_v2=abc; account_id_v2=1"  # actually encrypted
    assert c.decrypt(token) == "cookie_token_v2=abc; account_id_v2=1"


def test_disabled_without_secret():
    c = CookieCipher("")
    assert c.available is False
    assert c.decrypt("anything") is None


def test_decrypt_garbage_returns_none():
    c = CookieCipher("secret")
    assert c.decrypt("not-a-valid-token") is None
    assert c.decrypt(None) is None


def test_wrong_secret_cannot_decrypt():
    token = CookieCipher("secret-one").encrypt("data")
    # A different secret derives a different key -> decrypt fails softly.
    assert CookieCipher("secret-two").decrypt(token) is None
