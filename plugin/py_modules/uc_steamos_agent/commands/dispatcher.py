"""Command-string -> action dispatch.

Phase 1+2 scope: navigation, media transport, Gamescope's own hotkeys,
power management, and volume (docs/command-mapping.md). Launch/shortcuts
commands land in a later phase and aren't recognized here yet.
"""

import threading

from . import media, power
from .keycodes import ALL_KEYCODES, COMBO_KEY_COMMANDS, SIMPLE_KEY_COMMANDS
from .uinput_device import UinputKeyboard

# For power_* commands: let the HTTP response go out before the host
# potentially suspends/reboots/powers off, per docs/protocol.md.
POWER_RESPONSE_DELAY_S = 0.2


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
        power_delay_s=POWER_RESPONSE_DELAY_S,
    ):
        self._keyboard_factory = keyboard_factory
        self._keyboard = None
        self._lock = threading.Lock()
        self._power_execute = power_execute
        self._media_execute = media_execute
        self._power_delay_s = power_delay_s

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

    def close(self) -> None:
        with self._lock:
            if self._keyboard is not None:
                self._keyboard.close()
                self._keyboard = None
