"""
SteamOS remote entity with UI pages and system commands.

Scoped for gaming use on a SteamOS/Bazzite HTPC, not media playback — no
play/pause/rewind/etc. transport controls; those were built for controlling
movie/TV playback on upstream's Windows HTPC and don't fit here. Command set
and pages otherwise differ from upstream (uc_intg_htpc): see
docs/command-mapping.md for the full Windows -> SteamOS/Gamescope mapping.
Only commands the agent (plugin/) actually implements as of this writing are
exposed here — app launching, shortcuts, and Bluetooth land in a later phase.

Power is modelled with the entity's native `on_off`/`toggle` features rather
than a custom `power_on_wol` simple command, for two reasons:
docs/command-mapping.md's core-api guidance is that dedicated power on/off
commands should NOT be added as simple commands, and `remote.Commands.ON` is
the only identifier the Remote's physical POWER button can be mapped to
(`create_btn_mapping(Buttons.POWER, short="remote.on")`). A custom simple
command would render as a page button and nothing else.

ON therefore means "wake it" (a magic packet, if a MAC is configured) and OFF
means `power_shutdown`. Wake is never sent through `POST /command`: the agent
cannot receive it, since it is exactly the box being asleep.

:license: MIT
"""

import logging
from typing import Any

from ucapi import StatusCodes, remote
from ucapi.ui import UiPage, create_ui_icon, create_ui_text
from ucapi_framework import RemoteEntity

from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.device import STATE_OFF, STATE_ON, STATE_WAKING, SteamOSDevice

_LOG = logging.getLogger(__name__)

COMMAND_MAP = {
    "POWER_OFF": "power_shutdown",
}

FEATURES = [
    remote.Features.ON_OFF,
    remote.Features.TOGGLE,
    remote.Features.SEND_CMD,
]


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
            "volume_up", "volume_down", "mute",
            "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
            "steam_home", "steam_qam", "steam_l3", "steam_settings", "steam_library",
            "close_last_launch",
            "steam_overlay", "alt_f4", "force_quit_game",
            "power_sleep", "power_hibernate", "power_shutdown", "power_restart",
        ]

        pages = [
            _create_navigation_page(),
            _create_volume_page(),
            _create_gamescope_page(),
            _create_game_session_page(),
            _create_function_keys_page(),
            _create_power_page(device.wol_available),
        ]

        super().__init__(
            entity_id,
            f"{device_config.name} Remote",
            FEATURES,
            {remote.Attributes.STATE: remote.States.UNKNOWN},
            simple_commands=simple_commands,
            ui_pages=pages,
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        """Map the device's four states onto remote's ON/OFF/UNAVAILABLE.

        WAKING maps to OFF: `remote` has no transitional state, and showing OFF
        while a wake is in flight is honest (it is still off) and leaves the
        Power On affordance usable for a retry. The distinction lives in the
        media-player dashboard, which does have room for the text.
        """
        state = self._device.state
        if state == STATE_ON:
            self.update({remote.Attributes.STATE: remote.States.ON})
        elif state in (STATE_OFF, STATE_WAKING):
            self.update({remote.Attributes.STATE: remote.States.OFF})
        else:
            # UNAVAILABLE: the host answers but the agent doesn't. Not "off" —
            # the box is on and something is wrong with Decky/the plugin.
            self.update({remote.Attributes.STATE: remote.States.UNAVAILABLE})

    async def _handle_command(self, entity: Any, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        if cmd_id == remote.Commands.ON:
            return StatusCodes.OK if await self._wake() else StatusCodes.SERVER_ERROR
        if cmd_id == remote.Commands.OFF:
            return StatusCodes.OK if await self._device.send_command("power_shutdown") else StatusCodes.SERVER_ERROR
        if cmd_id == remote.Commands.TOGGLE:
            if self._device.state == STATE_ON:
                ok = await self._device.send_command("power_shutdown")
            else:
                ok = await self._wake()
            return StatusCodes.OK if ok else StatusCodes.SERVER_ERROR

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

    async def _wake(self) -> bool:
        """Wake the box locally — never via the agent's /command endpoint."""
        if not self._device.wol_available:
            _LOG.info(
                "%s Power On has no effect: no MAC address configured, so Wake-on-LAN is disabled",
                self._device.log_id,
            )
            return False
        return await self._device.wake_on_lan()

    async def _execute_command(self, command: str) -> bool:
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


def _create_volume_page() -> UiPage:
    page = UiPage(page_id="volume", name="Volume")
    page.items.extend([
        create_ui_icon("uc:volume-1", 0, 0, cmd="volume_down"),
        create_ui_icon("uc:volume-x", 1, 0, cmd="mute"),
        create_ui_icon("uc:volume-2", 2, 0, cmd="volume_up"),
    ])
    return page


def _create_gamescope_page() -> UiPage:
    """Gamescope's own native hotkeys (docs/command-mapping.md). Replaces
    upstream's Windows-Meta-key shortcuts page, which has no equivalent here:
    Gamescope discards Left-Windows/Super combos before apps ever see them.

    `Close Launch` is a safety valve: it SIGTERMs the process group of the
    last steam:// URI the agent launched (Settings/Library/launch_game). It
    does not reach a D-Bus-activated app like a browser, which is exactly why
    free-form URL launching was removed from the agent (see launch.py and
    docs/command-mapping.md's Web URLs row); for the fixed steam:// launches
    that are genuine children of the agent, it offers a one-tap recovery."""
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


def _create_game_session_page() -> UiPage:
    """Three separate, explicit ways to exit a running game — deliberately
    not one command that silently tries several approaches, so the user
    always knows which one actually fired (from the 2026-08-23 grilling
    session that scoped this whole area). All three confirmed live against
    a real running game — see docs/command-mapping.md's exit-game row."""
    page = UiPage(page_id="game_session", name="Game Session")
    page.items.extend([
        create_ui_text("Overlay", 0, 0, cmd="steam_overlay"),
        create_ui_text("Force Close", 1, 0, cmd="alt_f4"),
        create_ui_text("Force Quit", 2, 0, cmd="force_quit_game"),
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


def _create_power_page(wol_available: bool) -> UiPage:
    """Power On appears only when a MAC address is configured — a button that
    silently does nothing is worse than no button.

    Note it is a `remote.on` command, not an agent command: the agent can't be
    told to power itself on, since it is offline by definition. The remaining
    four are agent commands (`systemctl`), and Sleep/Hibernate/PowerOff here
    are what a WoL-capable NIC then has to be woken from — see
    docs/hardware-notes.md for which of those the target box actually wakes from.
    """
    page = UiPage(page_id="power", name="Power & System")
    items = []
    if wol_available:
        items.append(create_ui_text("Power On", 0, 0, cmd=remote.Commands.ON))
    items.extend([
        create_ui_text("Sleep", 1, 0, cmd="power_sleep"),
        create_ui_text("Hibernate", 2, 0, cmd="power_hibernate"),
        create_ui_text("PowerOff", 3, 0, cmd="power_shutdown"),
        create_ui_text("Restart", 0, 1, cmd="power_restart"),
    ])
    page.items.extend(items)
    return page
