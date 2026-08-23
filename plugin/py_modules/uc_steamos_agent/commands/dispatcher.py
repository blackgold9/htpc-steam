"""Command-string -> action dispatch.

Full scope through Phase 4: navigation, media transport, Gamescope's own
hotkeys, power management, volume, and app/URL launching (docs/command-mapping.md).
"""

import threading

from . import launch, media, power, shortcuts
from .keycodes import ALL_KEYCODES, COMBO_KEY_COMMANDS, SIMPLE_KEY_COMMANDS
from .uinput_device import UinputKeyboard

# For power_* commands: let the HTTP response go out before the host
# potentially suspends/reboots/powers off, per docs/protocol.md.
POWER_RESPONSE_DELAY_S = 0.2

# Fixed steam:// destinations exposed as named commands, replacing upstream's
# win_i (Settings) with no direct equivalent otherwise. See docs/command-mapping.md.
LAUNCH_URL_COMMANDS = {
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
        launch_exe_execute=launch.launch_exe,
        launch_url_execute=launch.launch_url,
        close_process_group=launch.close_process_group,
        shortcuts_dir: str = "",
        power_delay_s=POWER_RESPONSE_DELAY_S,
    ):
        self._keyboard_factory = keyboard_factory
        self._keyboard = None
        self._lock = threading.Lock()
        self._power_execute = power_execute
        self._media_execute = media_execute
        self._launch_exe_execute = launch_exe_execute
        self._launch_url_execute = launch_url_execute
        self._close_process_group = close_process_group
        self._shortcuts_dir = shortcuts_dir
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
            if command in LAUNCH_URL_COMMANDS:
                self._last_launch_pid = self._launch_url_execute(LAUNCH_URL_COMMANDS[command])
                return
            if command.startswith("launch_exe:"):
                _, _, path = command.partition(":")
                self._last_launch_pid = self._launch_exe_execute(path)
                return
            if command.startswith("launch_url:"):
                _, _, url = command.partition(":")
                self._last_launch_pid = self._launch_url_execute(url)
                return
            if command.startswith("shortcut:"):
                self._dispatch_shortcut(command)
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

    def _dispatch_shortcut(self, command: str) -> None:
        _, _, name = command.partition(":")
        try:
            content = shortcuts.read_shortcut(self._shortcuts_dir, name)
        except shortcuts.ShortcutError as err:
            raise UnknownCommandError(str(err)) from err
        if shortcuts.is_url(content):
            self._last_launch_pid = self._launch_url_execute(content)
        else:
            self._last_launch_pid = self._launch_exe_execute(content)

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
