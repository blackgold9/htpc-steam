"""Command-string -> action dispatch.

Scoped for gaming use on a SteamOS/Gamescope HTPC, not media playback:
navigation, Gamescope's own hotkeys, power management, volume, and fixed
Steam URI shortcuts (docs/command-mapping.md). No media transport keys
(play/pause/rewind/etc.) -- those were built for controlling movie/TV
playback and don't fit a gaming-focused box. General-purpose app/URL
launching was also built and then removed after live testing found an
unrecoverable full-screen-takeover gap -- see launch.py's docstring.
"""

import threading

from . import launch, media, power
from .keycodes import ALL_KEYCODES, COMBO_KEY_COMMANDS, SIMPLE_KEY_COMMANDS
from .uinput_device import UinputKeyboard

# For power_* commands: let the HTTP response go out before the host
# potentially suspends/reboots/powers off, per docs/protocol.md.
POWER_RESPONSE_DELAY_S = 0.2

# Fixed steam:// destinations exposed as named commands, replacing upstream's
# win_i (Settings) with no direct equivalent otherwise. See docs/command-mapping.md.
STEAM_URI_COMMANDS = {
    "steam_settings": "steam://open/settings",
    "steam_library": "steam://open/games",
}


class UnknownCommandError(Exception):
    pass


class Dispatcher:
    """Owns a single lazily-created virtual keyboard and routes commands to it.

    ThreadingHTTPServer can call `dispatch` from multiple request threads at
    once; the lock keeps a combo's key-down/key-up sequence from interleaving
    with another request's.
    """

    def __init__(
        self,
        keyboard_factory=UinputKeyboard,
        power_execute=power.execute,
        media_execute=media.execute,
        launch_steam_uri_execute=launch.launch_steam_uri,
        close_process_group=launch.close_process_group,
        power_delay_s=POWER_RESPONSE_DELAY_S,
    ):
        self._keyboard_factory = keyboard_factory
        self._keyboard = None
        self._lock = threading.Lock()
        self._power_execute = power_execute
        self._media_execute = media_execute
        self._launch_steam_uri_execute = launch_steam_uri_execute
        self._close_process_group = close_process_group
        self._power_delay_s = power_delay_s
        self._last_launch_pid: int | None = None

    def _get_keyboard(self):
        if self._keyboard is None:
            self._keyboard = self._keyboard_factory(ALL_KEYCODES)
        return self._keyboard

    def dispatch(self, command: str) -> None:
        with self._lock:
            if command in SIMPLE_KEY_COMMANDS:
                self._get_keyboard().press(SIMPLE_KEY_COMMANDS[command])
                return
            if command in COMBO_KEY_COMMANDS:
                self._get_keyboard().press_combo(*COMBO_KEY_COMMANDS[command])
                return
            if command in power.POWER_COMMANDS:
                timer = threading.Timer(self._power_delay_s, self._power_execute, args=(command,))
                timer.daemon = True
                timer.start()
                return
            if command in media.SIMPLE_COMMANDS:
                self._media_execute(media.SIMPLE_COMMANDS[command])
                return
            if command.startswith("set_volume:"):
                self._dispatch_set_volume(command)
                return
            if command in STEAM_URI_COMMANDS:
                self._last_launch_pid = self._launch_steam_uri_execute(STEAM_URI_COMMANDS[command])
                return
            if command == "close_last_launch":
                self._dispatch_close_last_launch()
                return
            raise UnknownCommandError(command)

    def _dispatch_set_volume(self, command: str) -> None:
        _, _, value = command.partition(":")
        try:
            percent = int(value)
        except ValueError:
            raise UnknownCommandError(command) from None
        if not 0 <= percent <= 100:
            raise UnknownCommandError(command)
        self._media_execute(media.set_volume_argv(percent))

    def _dispatch_close_last_launch(self) -> None:
        """No-op (not an error) if nothing has been launched yet -- a client
        may call this defensively without tracking launch state itself."""
        if self._last_launch_pid is not None:
            self._close_process_group(self._last_launch_pid)
            self._last_launch_pid = None

    def close(self) -> None:
        with self._lock:
            if self._keyboard is not None:
                self._keyboard.close()
                self._keyboard = None
