"""Byte-level checks that UinputKeyboard emits exactly what the kernel
uinput ABI expects, without touching a real /dev/uinput. os.open/write/close
and fcntl.ioctl are monkeypatched for the duration of each test only."""

import struct

import pytest

from uc_steamos_agent.commands import uinput_device as ud


class _Recorder:
    def __init__(self):
        self.ioctls = []
        self.writes = []
        self.opened_path = None
        self.opened_flags = None
        self.closed = False


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()

    def fake_open(path, flags):
        rec.opened_path = path
        rec.opened_flags = flags
        return 42  # arbitrary fake fd

    def fake_ioctl(fd, cmd, arg=0):
        assert fd == 42
        rec.ioctls.append((cmd, arg))
        return 0

    def fake_write(fd, data):
        assert fd == 42
        rec.writes.append(data)
        return len(data)

    def fake_close(fd):
        assert fd == 42
        rec.closed = True

    monkeypatch.setattr(ud.os, "open", fake_open)
    monkeypatch.setattr(ud.fcntl, "ioctl", fake_ioctl)
    monkeypatch.setattr(ud.os, "write", fake_write)
    monkeypatch.setattr(ud.os, "close", fake_close)
    monkeypatch.setattr(ud.time, "sleep", lambda s: None)
    return rec


def test_ioctl_constants_match_kernel_headers():
    # Cross-checked against /usr/include/linux/uinput.h on the target box.
    assert ud.UI_DEV_CREATE == 0x5501
    assert ud.UI_DEV_DESTROY == 0x5502
    assert ud.UI_SET_EVBIT == 0x40045564
    assert ud.UI_SET_KEYBIT == 0x40045565
    assert ud.UI_DEV_SETUP == 0x405C5503


def test_device_setup_sequence(recorder):
    kb = ud.UinputKeyboard([103, 108], device_name="test-kb")

    assert recorder.opened_path == "/dev/uinput"

    # UI_SET_EVBIT(EV_KEY), then one UI_SET_KEYBIT per keycode, then
    # UI_DEV_SETUP, then UI_DEV_CREATE, in that order.
    assert recorder.ioctls[0] == (ud.UI_SET_EVBIT, ud.EV_KEY)
    assert recorder.ioctls[1] == (ud.UI_SET_KEYBIT, 103)
    assert recorder.ioctls[2] == (ud.UI_SET_KEYBIT, 108)

    setup_cmd, setup_arg = recorder.ioctls[3]
    assert setup_cmd == ud.UI_DEV_SETUP
    assert len(setup_arg) == struct.calcsize(ud.UINPUT_SETUP_FMT) == 92
    bustype, vendor, product, version, name, ff_max = struct.unpack(ud.UINPUT_SETUP_FMT, setup_arg)
    assert name.rstrip(b"\x00") == b"test-kb"
    assert ff_max == 0

    assert recorder.ioctls[4] == (ud.UI_DEV_CREATE, 0)

    kb.close()
    assert recorder.ioctls[5] == (ud.UI_DEV_DESTROY, 0)
    assert recorder.closed is True


def test_press_emits_down_syn_up_syn(recorder):
    kb = ud.UinputKeyboard([103])
    kb.press(103)

    assert len(recorder.writes) == 4
    down, down_syn, up, up_syn = (struct.unpack(ud.INPUT_EVENT_FMT, w) for w in recorder.writes)

    # (sec, usec, type, code, value)
    assert down == (0, 0, ud.EV_KEY, 103, 1)
    assert down_syn == (0, 0, ud.EV_SYN, ud.SYN_REPORT, 0)
    assert up == (0, 0, ud.EV_KEY, 103, 0)
    assert up_syn == (0, 0, ud.EV_SYN, ud.SYN_REPORT, 0)


def test_press_combo_holds_in_order_releases_in_reverse(recorder):
    kb = ud.UinputKeyboard([29, 2])  # KEY_LEFTCTRL, KEY_1
    kb.press_combo(29, 2)

    events = [struct.unpack(ud.INPUT_EVENT_FMT, w) for w in recorder.writes]
    key_events = [e for e in events if e[2] == ud.EV_KEY]

    assert key_events == [
        (0, 0, ud.EV_KEY, 29, 1),  # ctrl down
        (0, 0, ud.EV_KEY, 2, 1),  # 1 down
        (0, 0, ud.EV_KEY, 2, 0),  # 1 up (reverse order release)
        (0, 0, ud.EV_KEY, 29, 0),  # ctrl up
    ]
