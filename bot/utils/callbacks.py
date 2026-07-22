"""Compact encoding/decoding for Telegram inline-button ``callback_data``.

Telegram limits ``callback_data`` to 64 bytes. We encode navigation state as a
pipe-delimited string so the character-showcase flow can switch pages and open/close
character views **without rerunning the command** — the full state is reconstructable
from the button that was pressed (combined with the cached showcase).

Format::

    <action>|<uid>|<char_id>|<page>

Empty fields are allowed (rendered as an empty segment). Example::

    char|901211014|10000046|0     -> open character 10000046 for UID, from page 0
    list|901211014||2             -> show character list page 2
    noop|||                       -> disabled / decorative button
"""

from __future__ import annotations

from dataclasses import dataclass

SEP = "|"
MAX_CALLBACK_BYTES = 64

# Navigation actions.
ACTION_LIST = "list"      # show the character-selection list (a given page)
ACTION_CHAR = "char"      # open a specific character's build
ACTION_PAGE = "page"      # change page within the list
ACTION_BACK = "back"      # return to the list from a character view
ACTION_NOOP = "noop"      # decorative / disabled button


@dataclass(frozen=True)
class Callback:
    """Decoded callback payload."""

    action: str
    uid: str = ""
    char_id: str = ""
    page: int = 0


def encode(action: str, *, uid: str = "", char_id: str = "", page: int = 0) -> str:
    """Encode a callback payload into a ``callback_data`` string.

    Raises:
        ValueError: if the encoded payload exceeds Telegram's 64-byte limit.
    """
    data = SEP.join([action, str(uid), str(char_id), str(page)])
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        raise ValueError(f"callback_data too long ({len(data)} chars): {data!r}")
    return data


def decode(data: str) -> Callback:
    """Decode a ``callback_data`` string into a :class:`Callback`.

    Tolerates malformed input by returning a NOOP callback rather than raising, so a
    stale or corrupt button can never crash the handler.
    """
    parts = (data or "").split(SEP)
    # Pad to 4 fields so unpacking is always safe.
    parts += [""] * (4 - len(parts))
    action, uid, char_id, page_raw = parts[:4]
    try:
        page = int(page_raw) if page_raw else 0
    except ValueError:
        page = 0
    return Callback(action=action or ACTION_NOOP, uid=uid, char_id=char_id, page=page)
