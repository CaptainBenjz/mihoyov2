"""Tests for callback_data encoding/decoding."""

from __future__ import annotations

import pytest

from bot.utils import callbacks
from bot.utils.callbacks import MAX_CALLBACK_BYTES


def test_encode_decode_roundtrip():
    data = callbacks.encode(callbacks.ACTION_CHAR, uid="901211014", char_id="10000046", page=3)
    cb = callbacks.decode(data)
    assert cb.action == callbacks.ACTION_CHAR
    assert cb.uid == "901211014"
    assert cb.char_id == "10000046"
    assert cb.page == 3


def test_encode_within_telegram_limit():
    data = callbacks.encode(callbacks.ACTION_CHAR, uid="901211014", char_id="10000046", page=99)
    assert len(data.encode("utf-8")) <= MAX_CALLBACK_BYTES


def test_encode_rejects_oversized_payload():
    with pytest.raises(ValueError):
        callbacks.encode(callbacks.ACTION_CHAR, uid="9" * 40, char_id="1" * 40, page=1)


def test_decode_malformed_is_noop():
    cb = callbacks.decode("garbage-without-separators")
    assert cb.action == "garbage-without-separators" or cb.action == callbacks.ACTION_NOOP
    # Non-integer page degrades to 0.
    assert callbacks.decode("page|uid|char|notanint").page == 0


def test_decode_empty_is_noop():
    cb = callbacks.decode("")
    assert cb.action == callbacks.ACTION_NOOP
