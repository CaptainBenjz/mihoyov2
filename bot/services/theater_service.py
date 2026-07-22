"""Imaginarium Theater business logic.

Like Abyss, detailed Theater records require an authenticated HoYoLAB session. This
foundation exposes the model and a service seam; it returns :class:`DataUnavailable`
until a data source is wired in, without ever crashing.
"""

from __future__ import annotations

from bot.models.theater import TheaterData
from bot.services.character_service import CharacterService
from bot.utils.errors import DataUnavailable


class TheaterService:
    def __init__(self, characters: CharacterService) -> None:
        self._characters = characters

    async def get_theater(self, uid: str, language: str = "en") -> TheaterData:
        # Ensure the profile is reachable/public before reporting availability.
        await self._characters.get_showcase(uid, language)
        data = TheaterData(uid=uid)
        if not data.available:
            raise DataUnavailable(f"No theater data for {uid}")
        return data
