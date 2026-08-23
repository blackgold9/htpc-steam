import time

import pytest

from uc_steamos_agent.commands.dispatcher import Dispatcher, UnknownCommandError
from uc_steamos_agent.commands.keycodes import ALL_KEYCODES, KEY_1, KEY_LEFTCTRL, KEY_UP


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
