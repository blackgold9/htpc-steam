import time

import pytest

from uc_steamos_agent.commands.dispatcher import Dispatcher, UnknownCommandError
from uc_steamos_agent.commands.keycodes import (
    ALL_KEYCODES,
    KEY_1,
    KEY_F4,
    KEY_LEFTALT,
    KEY_LEFTCTRL,
    KEY_LEFTSHIFT,
    KEY_TAB,
    KEY_UP,
)


class _FakeKeyboard:
    def __init__(self, keycodes):
        self.keycodes = keycodes
        self.presses = []
        self.combos = []
        self.closed = False

    def press(self, code, hold_s=0.02):
        self.presses.append(code)

    def press_combo(self, *codes, hold_s=0.02):
        self.combos.append(codes)

    def close(self):
        self.closed = True


def test_dispatch_simple_command_presses_key():
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard)
    dispatcher.dispatch("arrow_up")
    assert dispatcher._keyboard.presses == [KEY_UP]


def test_dispatch_combo_command_presses_combo():
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard)
    dispatcher.dispatch("steam_home")
    assert dispatcher._keyboard.combos == [(KEY_LEFTCTRL, KEY_1)]


def test_dispatch_unknown_command_raises():
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard)
    with pytest.raises(UnknownCommandError):
        dispatcher.dispatch("not_a_real_command")


def test_dispatch_power_command_is_deferred_and_fired_after_delay():
    calls = []
    dispatcher = Dispatcher(
        keyboard_factory=_FakeKeyboard,
        power_execute=lambda cmd: calls.append(cmd),
        power_delay_s=0.01,
    )
    dispatcher.dispatch("power_shutdown")
    assert calls == []  # not fired synchronously
    time.sleep(0.05)
    assert calls == ["power_shutdown"]


def test_dispatch_volume_simple_command():
    calls = []
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard, media_execute=lambda argv: calls.append(argv))
    dispatcher.dispatch("volume_up")
    assert calls == [["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"]]


def test_dispatch_set_volume_parses_percent():
    calls = []
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard, media_execute=lambda argv: calls.append(argv))
    dispatcher.dispatch("set_volume:42")
    assert calls == [["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "42%"]]


def test_dispatch_set_volume_rejects_out_of_range_and_non_numeric():
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard, media_execute=lambda argv: None)
    with pytest.raises(UnknownCommandError):
        dispatcher.dispatch("set_volume:101")
    with pytest.raises(UnknownCommandError):
        dispatcher.dispatch("set_volume:-1")
    with pytest.raises(UnknownCommandError):
        dispatcher.dispatch("set_volume:loud")


def test_dispatch_fixed_steam_uri_commands():
    calls = []
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard, launch_steam_uri_execute=lambda uri: calls.append(uri))
    dispatcher.dispatch("steam_settings")
    dispatcher.dispatch("steam_library")
    assert calls == ["steam://open/settings", "steam://open/games"]


def test_close_last_launch_closes_the_most_recent_pid():
    calls = []
    dispatcher = Dispatcher(
        keyboard_factory=_FakeKeyboard,
        launch_steam_uri_execute=lambda uri: 4242,
        close_process_group=lambda pid: calls.append(pid),
    )
    dispatcher.dispatch("steam_settings")
    dispatcher.dispatch("close_last_launch")
    assert calls == [4242]


def test_close_last_launch_is_a_noop_with_nothing_launched():
    calls = []
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard, close_process_group=lambda pid: calls.append(pid))
    dispatcher.dispatch("close_last_launch")  # must not raise
    assert calls == []


def test_close_last_launch_only_closes_once():
    calls = []
    dispatcher = Dispatcher(
        keyboard_factory=_FakeKeyboard,
        launch_steam_uri_execute=lambda uri: 4242,
        close_process_group=lambda pid: calls.append(pid),
    )
    dispatcher.dispatch("steam_settings")
    dispatcher.dispatch("close_last_launch")
    dispatcher.dispatch("close_last_launch")
    assert calls == [4242]  # second call is a no-op, pid already cleared


def test_dispatch_exit_game_combos_press_correct_keys():
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard)
    dispatcher.dispatch("steam_overlay")
    dispatcher.dispatch("alt_f4")
    assert dispatcher._keyboard.combos == [(KEY_LEFTSHIFT, KEY_TAB), (KEY_LEFTALT, KEY_F4)]


def test_dispatch_force_quit_game():
    calls = []
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard, force_quit_game_execute=lambda: calls.append(True))
    dispatcher.dispatch("force_quit_game")
    assert calls == [True]


def test_dispatch_launch_game_uses_rungameid_uri():
    calls = []
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard, launch_steam_uri_execute=lambda uri: calls.append(uri) or 4242)
    dispatcher.dispatch("launch_game:1686940")
    assert calls == ["steam://rungameid/1686940"]


def test_dispatch_launch_game_sets_last_launch_pid_for_close():
    close_calls = []
    dispatcher = Dispatcher(
        keyboard_factory=_FakeKeyboard,
        launch_steam_uri_execute=lambda uri: 4242,
        close_process_group=lambda pid: close_calls.append(pid),
    )
    dispatcher.dispatch("launch_game:1686940")
    dispatcher.dispatch("close_last_launch")
    assert close_calls == [4242]


def test_dispatch_launch_game_rejects_non_numeric_appid():
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard, launch_steam_uri_execute=lambda uri: 4242)
    with pytest.raises(UnknownCommandError):
        dispatcher.dispatch("launch_game:not_a_number")


def test_keyboard_created_lazily_and_reused():
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard)
    assert dispatcher._keyboard is None
    dispatcher.dispatch("enter")
    first = dispatcher._keyboard
    assert first.keycodes == ALL_KEYCODES
    dispatcher.dispatch("escape")
    assert dispatcher._keyboard is first  # not recreated


def test_close_tears_down_keyboard():
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard)
    dispatcher.dispatch("enter")
    kb = dispatcher._keyboard
    dispatcher.close()
    assert kb.closed is True
    assert dispatcher._keyboard is None
