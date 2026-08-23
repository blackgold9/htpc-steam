"""
SteamOS Game Launcher entity: getting the user INTO a game without a keyboard.

Separate media_player entity from SteamOSMediaPlayer (the monitoring
dashboard) — that one is a stats display with a fixed SOURCE_LIST; this one's
SOURCE_LIST is the agent's live recently-played games list (GET /games,
recents-first per the 2026-08-23 grilling session), and SELECT_SOURCE
launches the chosen game via launch_game:<appid>. See
docs/command-mapping.md's "Getting into a game" row.

:license: MIT
"""

import logging
from typing import Any

from ucapi import StatusCodes, media_player
from ucapi_framework import MediaPlayerEntity

from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.device import SteamOSDevice

_LOG = logging.getLogger(__name__)

FEATURES = [
    media_player.Features.SELECT_SOURCE,
    media_player.Features.MEDIA_TITLE,
]


class SteamOSGameLauncher(MediaPlayerEntity):
    """Media player entity used purely as a source-list game launcher."""

    def __init__(self, device_config: SteamOSConfig, device: SteamOSDevice) -> None:
        self._device = device
        entity_id = f"media_player.{device_config.identifier}_games"
        super().__init__(
            entity_id,
            f"{device_config.name} Games",
            FEATURES,
            {
                media_player.Attributes.STATE: media_player.States.STANDBY,
                media_player.Attributes.SOURCE_LIST: [],
                media_player.Attributes.SOURCE: "",
                media_player.Attributes.MEDIA_TITLE: "Select a game to launch",
            },
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        if self._device.state == "UNAVAILABLE":
            self.update({media_player.Attributes.STATE: media_player.States.UNAVAILABLE})
            return

        self.update({
            media_player.Attributes.STATE: media_player.States.ON,
            media_player.Attributes.SOURCE_LIST: [game["name"] for game in self._device.games],
        })

    async def _handle_command(self, entity: Any, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        if cmd_id != media_player.Commands.SELECT_SOURCE:
            return StatusCodes.NOT_IMPLEMENTED

        name = params.get("source", "") if params else ""
        appid = self._device.appid_for_game(name)
        if appid is None:
            return StatusCodes.BAD_REQUEST

        await self._device.launch_game(appid)
        self.update({
            media_player.Attributes.SOURCE: name,
            media_player.Attributes.MEDIA_TITLE: f"Launching {name}...",
        })
        self._device.push_update()
        return StatusCodes.OK
