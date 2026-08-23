"""Symbolic key names -> Linux keycodes.

Values transcribed from /usr/include/linux/input-event-codes.h on the
target Bazzite box (not guessed from memory) — see docs/hardware-notes.md.

Scoped for gaming use (Steam/Gamescope navigation and system control), not
media playback — no play/pause/rewind/etc. transport keys. See
docs/command-mapping.md.
"""

KEY_ESC = 1
KEY_1 = 2
KEY_2 = 3
KEY_6 = 7
KEY_BACKSPACE = 14
KEY_TAB = 15
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_LEFTALT = 56
KEY_SPACE = 57
KEY_F1 = 59
KEY_F2 = 60
KEY_F3 = 61
KEY_F4 = 62
KEY_F5 = 63
KEY_F6 = 64
KEY_F7 = 65
KEY_F8 = 66
KEY_F9 = 67
KEY_F10 = 68
KEY_F11 = 87
KEY_F12 = 88
KEY_HOME = 102
KEY_UP = 103
KEY_PAGEUP = 104
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_END = 107
KEY_DOWN = 108
KEY_PAGEDOWN = 109
KEY_DELETE = 111
KEY_MUTE = 113
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115

# Symbolic command name -> single keycode, for the dispatcher's simple presses.
SIMPLE_KEY_COMMANDS = {
    "arrow_up": KEY_UP,
    "arrow_down": KEY_DOWN,
    "arrow_left": KEY_LEFT,
    "arrow_right": KEY_RIGHT,
    "enter": KEY_ENTER,
    "escape": KEY_ESC,
    "back": KEY_ESC,
    "tab": KEY_TAB,
    "space": KEY_SPACE,
    "delete": KEY_DELETE,
    "backspace": KEY_BACKSPACE,
    "home": KEY_HOME,
    "end": KEY_END,
    "page_up": KEY_PAGEUP,
    "page_down": KEY_PAGEDOWN,
    "f1": KEY_F1,
    "f2": KEY_F2,
    "f3": KEY_F3,
    "f4": KEY_F4,
    "f5": KEY_F5,
    "f6": KEY_F6,
    "f7": KEY_F7,
    "f8": KEY_F8,
    "f9": KEY_F9,
    "f10": KEY_F10,
    "f11": KEY_F11,
    "f12": KEY_F12,
}

# Symbolic command name -> ordered keycode combo (held together), for
# Gamescope's own native hotkeys. See docs/command-mapping.md.
COMBO_KEY_COMMANDS = {
    "steam_home": (KEY_LEFTCTRL, KEY_1),  # Steam button
    "steam_qam": (KEY_LEFTCTRL, KEY_2),  # Quick Access Menu
    "steam_l3": (KEY_LEFTCTRL, KEY_6),  # L3 click
}

# Every keycode this module ever presses, for UI_SET_KEYBIT registration.
ALL_KEYCODES = sorted(
    set(SIMPLE_KEY_COMMANDS.values()) | {code for combo in COMBO_KEY_COMMANDS.values() for code in combo}
)
