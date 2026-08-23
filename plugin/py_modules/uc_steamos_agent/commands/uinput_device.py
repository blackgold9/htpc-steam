"""Raw /dev/uinput virtual keyboard device.

Implements just enough of the uinput ioctl protocol to create a virtual
keyboard and inject key press/release events. ioctl numbers are computed
from the same _IO/_IOW formula <asm-generic/ioctl.h> and <linux/uinput.h>
use, rather than transcribed as magic numbers — cross-checked against
/usr/include/linux/{uinput.h,input.h,input-event-codes.h} on the target
Bazzite box.
"""

import fcntl
import os
import struct
import time

_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14

_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS

_IOC_NONE = 0
_IOC_WRITE = 1


def _ioc(direction: int, type_char: str, nr: int, size: int) -> int:
    return (
        (direction << _IOC_DIRSHIFT)
        | (ord(type_char) << _IOC_TYPESHIFT)
        | (nr << _IOC_NRSHIFT)
        | (size << _IOC_SIZESHIFT)
    )


def _io(type_char: str, nr: int) -> int:
    return _ioc(_IOC_NONE, type_char, nr, 0)


def _iow(type_char: str, nr: int, size: int) -> int:
    return _ioc(_IOC_WRITE, type_char, nr, size)


_UINPUT_IOCTL_BASE = "U"

UI_DEV_CREATE = _io(_UINPUT_IOCTL_BASE, 1)
UI_DEV_DESTROY = _io(_UINPUT_IOCTL_BASE, 2)
UI_SET_EVBIT = _iow(_UINPUT_IOCTL_BASE, 100, struct.calcsize("i"))
UI_SET_KEYBIT = _iow(_UINPUT_IOCTL_BASE, 101, struct.calcsize("i"))

# struct input_id { __u16 bustype, vendor, product, version; } -- 8 bytes
# struct uinput_setup { struct input_id id; char name[80]; __u32 ff_effects_max; }
UINPUT_SETUP_FMT = "HHHH80sI"
UI_DEV_SETUP = _iow(_UINPUT_IOCTL_BASE, 3, struct.calcsize(UINPUT_SETUP_FMT))

EV_SYN = 0x00
EV_KEY = 0x01
SYN_REPORT = 0
_KEY_DOWN = 1
_KEY_UP = 0

# struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
# timeval's tv_sec/tv_usec are `long`, which is 8 bytes on x86_64 Linux userspace.
INPUT_EVENT_FMT = "llHHi"

UINPUT_PATH = "/dev/uinput"


class UinputKeyboard:
    """A virtual keyboard uinput device supporting a fixed set of keycodes."""

    def __init__(self, keycodes, device_name: str = "uc-steamos-agent-keyboard", path: str = UINPUT_PATH):
        self._fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_KEY)
            for code in keycodes:
                fcntl.ioctl(self._fd, UI_SET_KEYBIT, code)

            setup = struct.pack(
                UINPUT_SETUP_FMT,
                0x03,  # bustype: BUS_USB
                0x1234,  # vendor: unregistered/test range
                0x5678,  # product
                1,  # version
                device_name.encode("utf-8"),
                0,  # ff_effects_max
            )
            fcntl.ioctl(self._fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(self._fd, UI_DEV_CREATE)
            # The kernel needs a moment to register the new device with
            # udev/libinput before events are reliably picked up.
            time.sleep(0.2)
        except Exception:
            os.close(self._fd)
            raise

    def _write_event(self, ev_type: int, code: int, value: int) -> None:
        event = struct.pack(INPUT_EVENT_FMT, 0, 0, ev_type, code, value)
        os.write(self._fd, event)

    def _syn(self) -> None:
        self._write_event(EV_SYN, SYN_REPORT, 0)

    def key_down(self, code: int) -> None:
        self._write_event(EV_KEY, code, _KEY_DOWN)
        self._syn()

    def key_up(self, code: int) -> None:
        self._write_event(EV_KEY, code, _KEY_UP)
        self._syn()

    def press(self, code: int, hold_s: float = 0.02) -> None:
        self.key_down(code)
        time.sleep(hold_s)
        self.key_up(code)

    def press_combo(self, *codes: int, hold_s: float = 0.02) -> None:
        """Press all codes down in order, hold, then release in reverse order."""
        for code in codes:
            self.key_down(code)
        time.sleep(hold_s)
        for code in reversed(codes):
            self.key_up(code)

    def close(self) -> None:
        try:
            fcntl.ioctl(self._fd, UI_DEV_DESTROY)
        finally:
            os.close(self._fd)
