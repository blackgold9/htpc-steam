"""Command-string -> uinput action dispatch.

Phase 1 scope: navigation, media transport, and Gamescope's own hotkeys
(docs/command-mapping.md). Power/volume/launch commands land in later
phases and aren't recognized here yet.
"""

import threading

from .keycodes import ALL_KEYCODES, COMBO_KEY_COMMANDS, SIMPLE_KEY_COMMANDS
from .uinput_device import UinputKeyboard


class UnknownCommandError(Exception):
    pass


class Dispatcher:
    """Owns a single lazily-created virtual keyboard and routes commands to it.

    ThreadingHTTPServer can call `dispatch` from multiple request threads at
    once; the lock keeps a combo's key-down/key-up sequence from interleaving
    with another request's.
    """

    def __init__(self, keyboard_factory=UinputKeyboard):
        self._keyboard_factory = keyboard_factory
        self._keyboard = None
        self._lock = threading.Lock()

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
            raise UnknownCommandError(command)

    def close(self) -> None:
        with self._lock:
            if self._keyboard is not None:
                self._keyboard.close()
                self._keyboard = None
