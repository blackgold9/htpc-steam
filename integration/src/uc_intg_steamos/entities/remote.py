"""
SteamOS remote entity with UI pages and system commands.

Command set and pages differ from upstream (uc_intg_htpc): see
docs/command-mapping.md for the full Windows -> SteamOS/Gamescope mapping.
Only commands the agent (plugin/) actually implements as of this writing are
exposed here — app launching, shortcuts, and Bluetooth land in a later phase.

:license: MIT
"""

import logging
from typing import Any

from ucapi import StatusCodes, remote
from ucapi.ui import UiPage, create_ui_icon, create_ui_text
from ucapi_framework import RemoteEntity

from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.device import SteamOSDevice

_LOG = logging.getLogger(__name__)

COMMAND_MAP = {
    "POWER_ON": "power_on",
    "POWER_OFF": "power_shutdown",
}


class SteamOSRemote(RemoteEntity):
    """Remote entity for SteamOS HTPC control with UI pages."""

    def __init__(self, device_config: SteamOSConfig, device: SteamOSDevice) -> None:
        self._device = device
        self._config = device_config
        entity_id = f"remote.{device_config.identifier}"

        simple_commands = [
            "POWER_OFF",
            "arrow_up", "arrow_down", "arrow_left", "arrow_right", "enter", "escape",
            "back", "home", "end", "page_up", "page_down", "tab", "space", "delete",
            "backspace",
            "play_pause", "play", "pause", "stop", "previous", "next", "fast_forward",
            "rewind", "record", "volume_up", "volume_down", "mute",
            "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
            "steam_home", "steam_qam", "steam_l3", "steam_settings", "steam_library",
            "close_last_launch",
            "power_sleep", "power_hibernate", "power_shutdown", "power_restart",
        ]

        if device_config.wol_enabled:
            simple_commands.insert(0, "POWER_ON")

        pages = [
            _create_navigation_page(),
            _create_media_page(),
            _create_gamescope_page(),
            _create_function_keys_page(),
            _create_power_page(device_config.wol_enabled),
        ]

        super().__init__(
            entity_id,
            f"{device_config.name} Remote",
            [remote.Features.SEND_CMD],
            {remote.Attributes.STATE: remote.States.UNKNOWN},
            simple_commands=simple_commands,
            ui_pages=pages,
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        if self._device.state == "UNAVAILABLE":
            self.update({remote.Attributes.STATE: remote.States.UNAVAILABLE})
        else:
            self.update({remote.Attributes.STATE: remote.States.ON})

    async def _handle_command(self, entity: Any, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        if cmd_id == remote.Commands.SEND_CMD:
            command = params.get("command") if params else None
            if command:
                success = await self._execute_command(command)
                return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
        elif cmd_id == remote.Commands.SEND_CMD_SEQUENCE:
            if params and "sequence" in params:
                for command in params["sequence"]:
                    success = await self._execute_command(command)
                    if not success:
                        return StatusCodes.SERVER_ERROR
                return StatusCodes.OK
            elif params and "command" in params:
                success = await self._execute_command(params["command"])
                return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

        return StatusCodes.BAD_REQUEST

    async def _execute_command(self, command: str) -> bool:
        if command == "POWER_ON" or command == "power_on":
            return await self._device.power_on_wol()
        actual = COMMAND_MAP.get(command, command)
        return await self._device.send_command(actual)


def _create_navigation_page() -> UiPage:
    page = UiPage(page_id="navigation", name="Navigation")
    page.items.extend([
        create_ui_icon("uc:arrow-up", 1, 0, cmd="arrow_up"),
        create_ui_icon("uc:arrow-left", 0, 1, cmd="arrow_left"),
        create_ui_icon("uc:check-circle", 1, 1, cmd="enter"),
        create_ui_icon("uc:arrow-right", 2, 1, cmd="arrow_right"),
        create_ui_icon("uc:arrow-down", 1, 2, cmd="arrow_down"),
        create_ui_icon("uc:x-circle", 3, 1, cmd="escape"),
        create_ui_text("Back", 0, 3, cmd="back"),
        create_ui_text("Tab", 1, 3, cmd="tab"),
        create_ui_text("Space", 2, 3, cmd="space"),
        create_ui_text("Delete", 3, 3, cmd="delete"),
        create_ui_text("Home", 0, 4, cmd="home"),
        create_ui_text("End", 1, 4, cmd="end"),
        create_ui_text("PgUp", 2, 4, cmd="page_up"),
        create_ui_text("PgDn", 3, 4, cmd="page_down"),
    ])
    return page


def _create_media_page() -> UiPage:
    page = UiPage(page_id="media", name="Media Controls")
    page.items.extend([
        create_ui_icon("uc:rewind", 0, 0, cmd="rewind"),
        create_ui_icon("uc:skip-back", 1, 0, cmd="previous"),
        create_ui_icon("uc:play", 2, 0, cmd="play"),
        create_ui_icon("uc:pause", 3, 0, cmd="pause"),
        create_ui_icon("uc:skip-forward", 0, 1, cmd="next"),
        create_ui_icon("uc:fast-forward", 1, 1, cmd="fast_forward"),
        create_ui_icon("uc:square", 2, 1, cmd="stop"),
        create_ui_icon("uc:circle", 3, 1, cmd="record"),
        create_ui_icon("uc:volume-1", 0, 2, cmd="volume_down"),
        create_ui_icon("uc:volume-x", 1, 2, cmd="mute"),
        create_ui_icon("uc:volume-2", 2, 2, cmd="volume_up"),
        create_ui_text("Play/Pause", 3, 2, cmd="play_pause"),
    ])
    return page


def _create_gamescope_page() -> UiPage:
    """Gamescope's own native hotkeys (docs/command-mapping.md). Replaces
    upstream's Windows-Meta-key shortcuts page, which has no equivalent here:
    Gamescope discards Left-Windows/Super combos before apps ever see them.

    `Close Launch` is a deliberate safety valve: launching a URL (e.g. via
    the free-text Send Command widget with `launch_url:...`) was confirmed
    live to be able to strand the user on a full-screen app with no reliable
    way back through any other command here — see docs/command-mapping.md's
    Web URLs row. This button at least offers a one-tap attempt at recovery,
    even though it's confirmed NOT to work for a D-Bus-activated app like
    Firefox; it may still help for a freshly-launched process."""
    page = UiPage(page_id="gamescope", name="Gamescope")
    page.items.extend([
        create_ui_text("Steam Button", 0, 0, cmd="steam_home"),
        create_ui_text("Quick Access", 1, 0, cmd="steam_qam"),
        create_ui_text("L3", 2, 0, cmd="steam_l3"),
        create_ui_text("Settings", 0, 1, cmd="steam_settings"),
        create_ui_text("Library", 1, 1, cmd="steam_library"),
        create_ui_text("Close Launch", 2, 1, cmd="close_last_launch"),
    ])
    return page


def _create_function_keys_page() -> UiPage:
    page = UiPage(page_id="function_keys", name="Function Keys")
    page.items.extend([
        create_ui_text("F1", 0, 0, cmd="f1"),
        create_ui_text("F2", 1, 0, cmd="f2"),
        create_ui_text("F3", 2, 0, cmd="f3"),
        create_ui_text("F4", 3, 0, cmd="f4"),
        create_ui_text("F5", 0, 1, cmd="f5"),
        create_ui_text("F6", 1, 1, cmd="f6"),
        create_ui_text("F7", 2, 1, cmd="f7"),
        create_ui_text("F8", 3, 1, cmd="f8"),
        create_ui_text("F9", 0, 2, cmd="f9"),
        create_ui_text("F10", 1, 2, cmd="f10"),
        create_ui_text("F11", 2, 2, cmd="f11"),
        create_ui_text("F12", 3, 2, cmd="f12"),
    ])
    return page


def _create_power_page(wol_enabled: bool) -> UiPage:
    page = UiPage(page_id="power", name="Power & System")
    if wol_enabled:
        page.items.extend([
            create_ui_text("PowerOn", 0, 0, cmd="POWER_ON"),
            create_ui_text("Sleep", 1, 0, cmd="power_sleep"),
            create_ui_text("Hibernate", 2, 0, cmd="power_hibernate"),
            create_ui_text("PowerOff", 3, 0, cmd="power_shutdown"),
            create_ui_text("Restart", 0, 1, cmd="power_restart"),
        ])
    else:
        page.items.extend([
            create_ui_text("Sleep", 0, 0, cmd="power_sleep"),
            create_ui_text("Hibernate", 1, 0, cmd="power_hibernate"),
            create_ui_text("PowerOff", 2, 0, cmd="power_shutdown"),
            create_ui_text("Restart", 3, 0, cmd="power_restart"),
        ])
    return page
