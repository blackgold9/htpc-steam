"""Minimal /dev/uinput accessibility check.

Standalone from the full key-injection module (built in Phase 1) so `/health`
can report whether this plugin process actually has uinput access under
Decky's `_root` flag, ahead of implementing any key injection at all.
"""

import os

UINPUT_PATH = "/dev/uinput"


def uinput_writable(path: str = UINPUT_PATH) -> bool:
    return os.path.exists(path) and os.access(path, os.W_OK)
