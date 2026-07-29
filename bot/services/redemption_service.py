"""Redemption-code business logic.

Turns a raw ``/redeem <code>`` request into a structured :class:`RedeemResult` that the
command layer renders. No Telegram or rendering here.

A note on capability
--------------------
Actually *performing* a HoYoverse redemption requires an authenticated HoYoLAB session
(the account's cookies), which this public-data bot does not hold — ``/genshinlogin`` stores
only a public UID. So redemption is modelled behind a small :class:`Redeemer` seam:

  * the default :class:`LinkRedeemer` validates the code and hands the user the official
    one-tap redemption link (the honest behaviour for a UID-only bot), and
  * a real cookie-authenticated backend can be dropped in later **without touching the
    command or the response layouts** — it just returns richer :class:`RedeemStatus` values
    (``SUCCESS`` / ``EXPIRED`` / ``ALREADY_REDEEMED`` / ``WRONG_REGION`` …) that already have
    rendered layouts.

The service never raises: every outcome (including an upstream failure) is a result object
with a status, so the command can always render a friendly, localized reply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from bot.services.account_service import uid_region
from bot.utils.logging import get_logger

logger = get_logger(__name__)

# Official global redemption page. It redeems for whichever account is logged into HoYoLAB
# in the user's browser; the code is prefilled so redemption is a single tap.
_GIFT_URL = "https://genshin.hoyoverse.com/en/gift?code={code}"

# HoYoverse gift codes are ASCII letters + digits (commonly 8–16 chars). Accept 4–20 to stay
# tolerant of future formats; anything with spaces/symbols is rejected as malformed.
_CODE_RE = re.compile(r"^[A-Za-z0-9]{4,20}$")


class RedeemStatus(str, Enum):
    """Outcome of a redemption attempt. Each value has a dedicated response layout."""

    SUCCESS = "success"                 # ✅ redeemed; rewards on the way
    INVALID = "invalid"                 # ❌ the code is malformed or not accepted
    EXPIRED = "expired"                 # ⌛ the code is no longer valid
    ALREADY_REDEEMED = "already"        # ⚠️ this account already claimed it
    WRONG_REGION = "wrong_region"       # 🌍 code isn't valid for the account's server
    SERVER_ERROR = "server_error"       # 🚫 upstream was unreachable / errored
    LINK = "link"                       # 🎁 default: open the official page to redeem


@dataclass(slots=True)
class RedeemResult:
    """Structured result the command layer renders. Never contains Telegram/UI concerns."""

    status: RedeemStatus
    code: str
    uid: str | None = None
    region: str | None = None
    nickname: str | None = None
    rewards: list[str] = field(default_factory=list)
    redeem_url: str | None = None
    detail: str | None = None  # technical note for logs; never shown to users


def normalize_code(raw: str) -> str | None:
    """Return an upper-cased, trimmed code, or ``None`` if the format is implausible."""
    code = (raw or "").strip()
    if not _CODE_RE.match(code):
        return None
    return code.upper()


def gift_url(code: str) -> str:
    """Return the official prefilled redemption URL for a (normalized) code."""
    return _GIFT_URL.format(code=code)


class Redeemer(Protocol):
    """Pluggable redemption backend.

    Implement this to perform real, authenticated redemption later. The default backend
    (:class:`LinkRedeemer`) simply returns the official link. Implementations should not
    raise — return a :class:`RedeemResult` with an appropriate status — but the service
    still guards against exceptions defensively.
    """

    async def redeem(self, uid: str, code: str, region: str | None) -> RedeemResult: ...


class LinkRedeemer:
    """Default backend: hand the user the official one-tap redemption link.

    The bot cannot authenticate to the redemption API with only a public UID, so rather than
    pretend, it validates the code and produces the official gift URL (with the code
    prefilled). Rewards are then claimed on the official site and arrive via in-game mail.
    """

    async def redeem(self, uid: str, code: str, region: str | None) -> RedeemResult:
        return RedeemResult(
            status=RedeemStatus.LINK,
            code=code,
            uid=uid,
            region=region,
            redeem_url=gift_url(code),
        )


class RedemptionService:
    """Validates redemption codes and delegates to a :class:`Redeemer` backend."""

    def __init__(self, redeemer: Redeemer | None = None) -> None:
        self._redeemer = redeemer or LinkRedeemer()

    async def redeem(self, uid: str, raw_code: str) -> RedeemResult:
        """Validate ``raw_code`` and attempt redemption for ``uid``. Never raises."""
        code = normalize_code(raw_code)
        if code is None:
            return RedeemResult(status=RedeemStatus.INVALID, code=(raw_code or "").strip())

        region = uid_region(uid)
        try:
            return await self._redeemer.redeem(uid, code, region)
        except Exception as exc:  # noqa: BLE001 - a backend hiccup must never crash the command
            logger.warning("Redeem backend failed for uid=%s code=%s: %s", uid, code, exc)
            return RedeemResult(
                status=RedeemStatus.SERVER_ERROR,
                code=code,
                uid=uid,
                region=region,
                detail=str(exc),
            )
